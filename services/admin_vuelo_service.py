import psycopg2.extras
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from database import Database


class AdminVueloService:
    @staticmethod
    def _validar_itinerario(datos, actual=None):
        zona = timezone(timedelta(hours=-5))
        ahora = datetime.now(zona)
        try:
            fecha = date.fromisoformat(datos["fecha"])
            salida = time.fromisoformat(datos["hora_salida"])
            llegada = time.fromisoformat(datos["hora_llegada"])
            if fecha.isoformat() != datos["fecha"] or salida.tzinfo or llegada.tzinfo:
                raise ValueError
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("Ingrese una fecha y horarios válidos") from error

        # Permite actualizar datos de un vuelo histórico si conserva sus horarios.
        if actual and (fecha, salida, llegada) == (
            actual["fecha"], actual["hora_salida"], actual["hora_llegada"]
        ):
            return
        if fecha < ahora.date() or fecha > ahora.date() + timedelta(days=730):
            raise ValueError("La fecha debe estar entre hoy y los próximos 730 días")
        if datetime.combine(fecha, salida, zona) <= ahora:
            raise ValueError("La fecha y hora de salida deben ser posteriores a las actuales")
        if llegada <= salida:
            raise ValueError("La hora de llegada debe ser posterior a la de salida")

    @staticmethod
    def _tarifas(datos, avion_id, precio_actual=None):
        try:
            turista = Decimal(str(datos["precio"])).quantize(Decimal("0.01"))
            if not turista.is_finite() or turista <= 0:
                raise ValueError("La tarifa turista debe ser mayor a cero")
            if avion_id is None:
                return turista, None
            valor = datos.get("precio_ejecutiva")
            if valor is None:
                valor = precio_actual if precio_actual is not None else max(
                    turista * Decimal("1.5"), turista + Decimal("0.01"))
            ejecutiva = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if not ejecutiva.is_finite() or ejecutiva <= turista:
                raise ValueError("La tarifa ejecutiva debe ser mayor que la turista")
            return turista, ejecutiva
        except InvalidOperation as error:
            raise ValueError("Las tarifas deben ser importes válidos") from error

    def listar_aviones(self):
        conexion = Database.obtener_conexion()
        try:
            with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, modelo, asientos_ejecutiva, asientos_turista,
                           asientos_ejecutiva + asientos_turista AS capacidad
                    FROM aviones ORDER BY capacidad, modelo
                """)
                return cursor.fetchall()
        finally:
            conexion.close()

    def _obtener_avion(self, cursor, avion_id):
        cursor.execute("""
            SELECT id, modelo, asientos_ejecutiva, asientos_turista
            FROM aviones WHERE id = %s
        """, (avion_id,))
        avion = cursor.fetchone()
        if avion is None:
            raise ValueError("Seleccione una aeronave del catálogo")
        return avion

    def _configurar_asientos(self, avion):
        ejecutiva = avion["asientos_ejecutiva"]
        cantidad = ejecutiva + avion["asientos_turista"]
        return {
            numero: "EJECUTIVA" if indice < ejecutiva else "TURISTA"
            for indice, numero in enumerate(self.generar_asientos(cantidad))
        }

    def crear_vuelo_con_asientos(self, datos):
        self._validar_itinerario(datos)
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            avion_id = datos.get("avion_id")
            if avion_id is not None:
                avion = self._obtener_avion(cursor, avion_id)
                asientos = self._configurar_asientos(avion)
            else:
                cantidad = int(datos["cantidad_asientos"])
                asientos = dict.fromkeys(self.generar_asientos(cantidad), "TURISTA")
            cantidad_asientos = len(asientos)
            precio, precio_ejecutiva = self._tarifas(datos, avion_id)

            if cantidad_asientos <= 0:
                raise Exception("La cantidad de asientos debe ser mayor a cero")

            cursor.execute("""
                INSERT INTO vuelos (
                    aerolinea,
                    origen,
                    destino,
                    fecha,
                    hora_salida,
                    hora_llegada,
                    precio,
                    precio_ejecutiva,
                    asientos_disponibles,
                    estado,
                    avion_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                RETURNING id, aerolinea, origen, destino, fecha, hora_salida, hora_llegada, precio, asientos_disponibles
            """, (
                datos["aerolinea"],
                datos["origen"],
                datos["destino"],
                datos["fecha"],
                datos["hora_salida"],
                datos["hora_llegada"],
                precio,
                precio_ejecutiva,
                cantidad_asientos,
                avion_id
            ))

            vuelo = cursor.fetchone()
            vuelo_id = vuelo["id"]

            psycopg2.extras.execute_values(cursor, """
                    INSERT INTO asientos_vuelo (
                        vuelo_id,
                        numero_asiento,
                        estado,
                        clase
                    )
                    VALUES %s
                """, [(vuelo_id, numero, 'DISPONIBLE', clase)
                      for numero, clase in asientos.items()])

            conexion.commit()

            return {
                "id": vuelo["id"],
                "aerolinea": vuelo["aerolinea"],
                "origen": vuelo["origen"],
                "destino": vuelo["destino"],
                "fecha": str(vuelo["fecha"]),
                "hora_salida": str(vuelo["hora_salida"]),
                "hora_llegada": str(vuelo["hora_llegada"]),
                "precio": float(vuelo["precio"]),
                "precio_ejecutiva": float(precio_ejecutiva) if precio_ejecutiva is not None else None,
                "asientos_disponibles": vuelo["asientos_disponibles"],
                "avion_id": avion_id,
                "total_asientos": cantidad_asientos,
                "asientos_generados": list(asientos)
            }

        except Exception as e:
            conexion.rollback()
            raise e

        finally:
            cursor.close()
            conexion.close()

    def generar_asientos(self, cantidad):
        letras = ["A", "B", "C", "D"]
        asientos = []

        fila = 1

        while len(asientos) < cantidad:
            for letra in letras:
                if len(asientos) < cantidad:
                    asientos.append(f"{fila}{letra}")
            fila += 1

        return asientos

    def editar_vuelo(self, vuelo_id, datos):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("""
                SELECT id, avion_id, asientos_disponibles, precio_ejecutiva,
                       fecha, hora_salida, hora_llegada
                FROM vuelos
                WHERE id = %s
                FOR UPDATE
            """, (vuelo_id,))
            actual = cursor.fetchone()
            if actual is None:
                raise Exception("Vuelo no encontrado")
            self._validar_itinerario(datos, actual)

            cursor.execute("""
                SELECT id, numero_asiento, reserva_id
                FROM asientos_vuelo
                WHERE vuelo_id = %s
                ORDER BY
                    CAST(regexp_replace(numero_asiento, '[^0-9]', '', 'g') AS INT),
                    regexp_replace(numero_asiento, '[0-9]', '', 'g')
                FOR UPDATE
            """, (vuelo_id,))
            asientos_actuales = cursor.fetchall()
            reservados = [a for a in asientos_actuales if a["reserva_id"] is not None]
            avion_id = datos.get("avion_id")
            if avion_id is None:
                avion_id = actual["avion_id"]
            precio, precio_ejecutiva = self._tarifas(datos, avion_id, actual["precio_ejecutiva"])
            total_actual = len(asientos_actuales)
            if avion_id is not None:
                avion = self._obtener_avion(cursor, avion_id)
                plantilla = self._configurar_asientos(avion)
                cantidad_asientos = len(plantilla)
                if avion_id != actual["avion_id"]:
                    cursor.execute("SELECT 1 FROM reservas WHERE vuelo_id = %s LIMIT 1", (vuelo_id,))
                    if reservados or cursor.fetchone():
                        raise ValueError("No se puede cambiar la aeronave de un vuelo con reservas")
                    cursor.execute("DELETE FROM asientos_vuelo WHERE vuelo_id = %s", (vuelo_id,))
                    psycopg2.extras.execute_values(cursor, """
                        INSERT INTO asientos_vuelo (vuelo_id, numero_asiento, estado, clase)
                        VALUES %s
                    """, [(vuelo_id, numero, 'DISPONIBLE', clase)
                          for numero, clase in plantilla.items()])
                    total_actual = cantidad_asientos
                elif total_actual != cantidad_asientos:
                    raise ValueError("La capacidad del vuelo no coincide con su aeronave")
            else:
                cantidad_asientos = int(datos.get("cantidad_asientos", total_actual or actual["asientos_disponibles"]))
            if cantidad_asientos <= 0:
                raise Exception("La capacidad debe ser mayor a cero")

            if cantidad_asientos < len(reservados):
                raise Exception(
                    f"La capacidad no puede ser menor a los {len(reservados)} asientos ya reservados"
                )

            if cantidad_asientos > total_actual:
                existentes = {a["numero_asiento"] for a in asientos_actuales}
                for numero_asiento in self.generar_asientos(cantidad_asientos):
                    if numero_asiento not in existentes:
                        cursor.execute("""
                            INSERT INTO asientos_vuelo (vuelo_id, numero_asiento, estado)
                            VALUES (%s, %s, 'DISPONIBLE')
                        """, (vuelo_id, numero_asiento))
            elif cantidad_asientos < total_actual:
                eliminar = total_actual - cantidad_asientos
                disponibles = [
                    a for a in reversed(asientos_actuales)
                    if a["reserva_id"] is None
                ]
                if len(disponibles) < eliminar:
                    raise Exception(
                        "No existen suficientes asientos libres para reducir la capacidad"
                    )
                cursor.execute(
                    "DELETE FROM asientos_vuelo WHERE id = ANY(%s)",
                    ([a["id"] for a in disponibles[:eliminar]],),
                )

            asientos_disponibles = cantidad_asientos - len(reservados)
            cursor.execute("""
                UPDATE vuelos
                SET aerolinea = %s,
                    origen = %s,
                    destino = %s,
                    fecha = %s,
                    hora_salida = %s,
                    hora_llegada = %s,
                    precio = %s,
                    precio_ejecutiva = %s,
                    estado = %s,
                    avion_id = %s,
                    asientos_disponibles = %s,
                    version = version + 1
                WHERE id = %s
                RETURNING id, aerolinea, origen, destino, fecha, hora_salida, hora_llegada, precio, asientos_disponibles, estado
            """, (
                datos["aerolinea"],
                datos["origen"],
                datos["destino"],
                datos["fecha"],
                datos["hora_salida"],
                datos["hora_llegada"],
                precio,
                precio_ejecutiva,
                datos.get("estado", True),
                avion_id,
                asientos_disponibles,
                vuelo_id
            ))

            vuelo = cursor.fetchone()
            if not vuelo:
                raise Exception("Vuelo no encontrado")

            conexion.commit()

            return {
                "id": vuelo["id"],
                "aerolinea": vuelo["aerolinea"],
                "origen": vuelo["origen"],
                "destino": vuelo["destino"],
                "fecha": str(vuelo["fecha"]),
                "hora_salida": str(vuelo["hora_salida"]),
                "hora_llegada": str(vuelo["hora_llegada"]),
                "precio": float(vuelo["precio"]),
                "precio_ejecutiva": float(precio_ejecutiva) if precio_ejecutiva is not None else None,
                "asientos_disponibles": vuelo["asientos_disponibles"],
                "total_asientos": cantidad_asientos,
                "avion_id": avion_id,
                "estado": vuelo["estado"]
            }

        except Exception as e:
            conexion.rollback()
            raise e

        finally:
            cursor.close()
            conexion.close()

    def eliminar_vuelo(self, vuelo_id):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            # El mismo bloqueo utilizado al reservar serializa ambas operaciones.
            cursor.execute("""
                SELECT id FROM vuelos WHERE id = %s FOR UPDATE
            """, (vuelo_id,))
            if cursor.fetchone() is None:
                raise ValueError("Vuelo no encontrado")

            # Las reservas canceladas son historial y no bloquean la desactivación.
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM reservas
                WHERE vuelo_id = %s AND estado = 'ACTIVA'
            """, (vuelo_id,))
            res = cursor.fetchone()
            if res and res["total"] > 0:
                raise ValueError("No se puede desactivar el vuelo porque tiene reservas activas.")

            cursor.execute("""
                UPDATE vuelos
                SET estado = FALSE,
                    fecha_desactivacion = CURRENT_TIMESTAMP,
                    version = version + 1
                WHERE id = %s
                RETURNING id
            """, (vuelo_id,))

            vuelo = cursor.fetchone()
            if not vuelo:
                raise Exception("Vuelo no encontrado")

            conexion.commit()
            return True

        except Exception as e:
            conexion.rollback()
            raise e

        finally:
            cursor.close()
            conexion.close()

    def obtener_dashboard(self):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("""
                SELECT
                    COUNT(*) FILTER (
                        WHERE v.estado = TRUE
                          AND (v.fecha + v.hora_salida) >
                              (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                    ) AS vuelos_vigentes,
                    COUNT(*) FILTER (
                        WHERE v.estado = TRUE
                          AND (v.fecha + v.hora_salida) <=
                              (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                    ) AS vuelos_finalizados,
                    COUNT(*) FILTER (WHERE v.estado = FALSE) AS vuelos_inactivos,
                    COALESCE(SUM(v.asientos_disponibles) FILTER (
                        WHERE v.estado = TRUE
                          AND (v.fecha + v.hora_salida) >
                              (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                    ), 0) AS asientos_disponibles,
                    (SELECT COUNT(*) FROM reservas r WHERE r.estado = 'ACTIVA')
                        AS reservas_activas,
                    (SELECT COALESCE(SUM(r.cantidad_asientos), 0)
                     FROM reservas r WHERE r.estado = 'ACTIVA')
                        AS pasajeros_confirmados,
                    (SELECT COALESCE(SUM(r.total), 0)
                     FROM reservas r WHERE r.estado = 'ACTIVA')
                        AS ingresos_confirmados,
                    (SELECT COUNT(*) FROM usuarios u
                     WHERE u.estado = TRUE AND u.rol <> 'admin')
                        AS clientes_activos
                FROM vuelos v
            """)
            resumen = cursor.fetchone()

            cursor.execute("""
                SELECT id, aerolinea, origen, destino, fecha,
                       hora_salida, hora_llegada, precio,
                       asientos_disponibles
                FROM vuelos
                WHERE estado = TRUE
                  AND (fecha + hora_salida) >
                      (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                ORDER BY fecha, hora_salida
                LIMIT 5
            """)
            proximos = [self._serializar_vuelo(fila) for fila in cursor.fetchall()]

            cursor.execute("""
                SELECT v.id, v.aerolinea, v.origen, v.destino, v.fecha,
                       v.hora_salida, v.hora_llegada, v.precio,
                       v.asientos_disponibles, v.fecha_desactivacion,
                       COUNT(r.id) AS reservas_relacionadas
                FROM vuelos v
                LEFT JOIN reservas r ON r.vuelo_id = v.id
                WHERE v.estado = FALSE
                GROUP BY v.id
                ORDER BY v.fecha_desactivacion DESC NULLS LAST, v.id DESC
            """)
            auditoria = []
            for fila in cursor.fetchall():
                item = self._serializar_vuelo(fila)
                item["fecha_desactivacion"] = (
                    fila["fecha_desactivacion"].isoformat()
                    if fila["fecha_desactivacion"] else None
                )
                item["reservas_relacionadas"] = fila["reservas_relacionadas"]
                auditoria.append(item)

            return {
                "resumen": {
                    "vuelos_vigentes": resumen["vuelos_vigentes"],
                    "vuelos_finalizados": resumen["vuelos_finalizados"],
                    "vuelos_inactivos": resumen["vuelos_inactivos"],
                    "asientos_disponibles": resumen["asientos_disponibles"],
                    "reservas_activas": resumen["reservas_activas"],
                    "pasajeros_confirmados": resumen["pasajeros_confirmados"],
                    "ingresos_confirmados": float(resumen["ingresos_confirmados"]),
                    "clientes_activos": resumen["clientes_activos"],
                },
                "proximos_vuelos": proximos,
                "auditoria": auditoria,
            }
        finally:
            cursor.close()
            conexion.close()

    @staticmethod
    def _serializar_vuelo(fila):
        return {
            "id": fila["id"],
            "aerolinea": fila["aerolinea"],
            "origen": fila["origen"],
            "destino": fila["destino"],
            "fecha": str(fila["fecha"]),
            "hora_salida": str(fila["hora_salida"]),
            "hora_llegada": str(fila["hora_llegada"]),
            "precio": float(fila["precio"]),
            "asientos_disponibles": fila["asientos_disponibles"],
        }
