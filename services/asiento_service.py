import psycopg2.extras
from decimal import Decimal, InvalidOperation
from database import Database
from models.asiento_model import AsientoModel


class AsientoService:
    @staticmethod
    def _verificar_total(total, esperado):
        if esperado is None:
            return
        try:
            correcto = Decimal(str(esperado)).quantize(Decimal("0.01")) == total
        except InvalidOperation:
            correcto = False
        if not correcto:
            raise ValueError("La tarifa cambió. Revise el total actualizado antes de confirmar.")

    def listar_asientos_por_vuelo(self, vuelo_id):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Check if seats are already generated
            cursor.execute("SELECT COUNT(*) as total FROM asientos_vuelo WHERE vuelo_id = %s", (vuelo_id,))
            resultado = cursor.fetchone()

            if resultado["total"] == 0:
                # Fetch flight capacity to auto-generate seats
                cursor.execute("SELECT asientos_disponibles FROM vuelos WHERE id = %s", (vuelo_id,))
                vuelo = cursor.fetchone()
                if vuelo:
                    cantidad = vuelo["asientos_disponibles"]
                    letras = ["A", "B", "C", "D"]
                    asientos = []
                    fila = 1
                    while len(asientos) < cantidad:
                        for letra in letras:
                            if len(asientos) < cantidad:
                                asientos.append(f"{fila}{letra}")
                        fila += 1

                    for numero_asiento in asientos:
                        cursor.execute("""
                            INSERT INTO asientos_vuelo (vuelo_id, numero_asiento, estado)
                            VALUES (%s, %s, 'DISPONIBLE')
                            ON CONFLICT DO NOTHING
                        """, (vuelo_id, numero_asiento))
                    conexion.commit()

            cursor.execute("""
                SELECT 
                    av.id, av.vuelo_id, av.numero_asiento, av.estado,
                    av.reserva_id, av.clase,
                    CASE WHEN av.clase = 'EJECUTIVA' THEN v.precio_ejecutiva ELSE v.precio END AS precio
                FROM asientos_vuelo av JOIN vuelos v ON v.id = av.vuelo_id
                WHERE av.vuelo_id = %s
                ORDER BY 
                    CAST(regexp_replace(numero_asiento, '[^0-9]', '', 'g') AS INT),
                    regexp_replace(numero_asiento, '[0-9]', '', 'g')
            """, (vuelo_id,))

            asientos = []

            for fila in cursor.fetchall():
                asiento = AsientoModel.from_row(fila)
                asientos.append(asiento.to_dict())

            return asientos

        finally:
            cursor.close()
            conexion.close()

    def crear_reserva_con_asientos(self, usuario_id, vuelo_id, asientos, total_esperado=None):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("""
                SELECT id
                FROM vuelos
                WHERE id = %s
                  AND estado = TRUE
                  AND (fecha + hora_salida) >
                      (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                FOR UPDATE
            """, (vuelo_id,))
            if cursor.fetchone() is None:
                raise ValueError("El vuelo ya finalizó o no se encuentra vigente")

            cursor.execute("""
                SELECT 
                    reserva_id,
                    codigo_reserva,
                    total,
                    estado
                FROM crear_reserva_asientos_segura(%s, %s, %s)
            """, (
                usuario_id,
                vuelo_id,
                asientos
            ))

            fila = cursor.fetchone()
            self._verificar_total(fila["total"], total_esperado)

            conexion.commit()

            return {
                "id": fila["reserva_id"],
                "codigo_reserva": fila["codigo_reserva"],
                "total": float(fila["total"]),
                "estado": fila["estado"],
                "asientos": asientos
            }

        except Exception as e:
            conexion.rollback()
            raise e

        finally:
            cursor.close()
            conexion.close()

    def actualizar_reserva_con_asientos(self, usuario_id, reserva_id, asientos, total_esperado=None):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("""
                SELECT modificada
                FROM reservas
                WHERE id = %s AND usuario_id = %s
                FOR UPDATE
            """, (reserva_id, usuario_id))
            reserva = cursor.fetchone()

            if reserva is None:
                raise ValueError("Reserva no encontrada")

            if reserva["modificada"]:
                raise ValueError("Esta reserva ya fue modificada y no admite nuevos cambios")

            cursor.execute("""
                SELECT actualizar_reserva_asientos_segura(%s, %s, %s)
            """, (
                usuario_id,
                reserva_id,
                asientos
            ))
            cursor.execute("SELECT total FROM reservas WHERE id = %s", (reserva_id,))
            self._verificar_total(cursor.fetchone()["total"], total_esperado)
            cursor.execute("""
                UPDATE reservas
                SET modificada = TRUE
                WHERE id = %s AND usuario_id = %s
            """, (reserva_id, usuario_id))
            conexion.commit()
        except Exception as e:
            conexion.rollback()
            raise e
        finally:
            cursor.close()
            conexion.close()
