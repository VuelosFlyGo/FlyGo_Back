import psycopg2.extras
from datetime import date, datetime, timedelta, timezone
from database import Database
from models.vuelo_model import VueloModel


class VueloService:

    @staticmethod
    def validar_fechas_busqueda(fecha_inicio, fecha_fin, incluir_historial=False):
        hoy = datetime.now(timezone(timedelta(hours=-5))).date()
        limite = hoy + timedelta(days=730)

        def validar(valor):
            if valor is None or valor == "":
                return None
            try:
                fecha = date.fromisoformat(valor) if isinstance(valor, str) else valor
                if (not isinstance(fecha, date) or isinstance(fecha, datetime)
                        or (isinstance(valor, str) and fecha.isoformat() != valor)):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("Ingrese una fecha válida en formato AAAA-MM-DD.") from None
            if not incluir_historial and fecha < hoy:
                raise ValueError("No se pueden consultar vuelos con fechas pasadas.")
            if fecha > limite:
                raise ValueError("La fecha excede el límite de 730 días.")
            return fecha

        inicio, fin = validar(fecha_inicio), validar(fecha_fin)
        if inicio is not None and fin is not None and inicio > fin:
            raise ValueError("La fecha final no puede ser anterior a la fecha inicial.")
        return inicio, fin

    def buscar_vuelos(
        self, origen=None, destino=None, fecha_inicio=None, fecha_fin=None,
        incluir_agotados=False, incluir_historial=False
    ):
        fecha_inicio, fecha_fin = self.validar_fechas_busqueda(
            fecha_inicio, fecha_fin, incluir_historial)
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("""
                SELECT id, aerolinea, origen, destino, fecha,
                       hora_salida, hora_llegada, precio, precio_ejecutiva,
                       asientos_disponibles, estado, avion_id,
                       (SELECT modelo FROM aviones WHERE id = vuelos.avion_id) AS avion_modelo,
                       CASE
                           WHEN estado = FALSE THEN 'INACTIVO'
                           WHEN (fecha + hora_salida) <=
                                (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                               THEN 'FINALIZADO'
                           WHEN asientos_disponibles <= 0 THEN 'AGOTADO'
                           ELSE 'VIGENTE'
                       END AS situacion,
                       (SELECT COUNT(*) FROM asientos_vuelo av WHERE av.vuelo_id = vuelos.id) AS total_asientos,
                       (SELECT COUNT(*) FROM reservas r WHERE r.vuelo_id = vuelos.id AND r.estado = 'ACTIVA') AS reservas_activas,
                       (SELECT COUNT(*) FROM asientos_vuelo av WHERE av.vuelo_id = vuelos.id
                          AND av.clase = 'EJECUTIVA' AND av.estado = 'DISPONIBLE') AS ejecutiva_disponibles,
                       CASE WHEN avion_id IS NULL THEN asientos_disponibles ELSE
                           (SELECT COUNT(*) FROM asientos_vuelo av WHERE av.vuelo_id = vuelos.id
                              AND av.clase = 'TURISTA' AND av.estado = 'DISPONIBLE')
                       END AS turista_disponibles
                FROM vuelos
                WHERE estado = TRUE
                  AND (
                      %s = TRUE
                      OR (fecha + hora_salida) >
                         (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                  )
                  AND (%s = TRUE OR asientos_disponibles > 0)
                  AND (%s IS NULL OR origen ILIKE %s)
                  AND (%s IS NULL OR destino ILIKE %s)
                  AND (%s IS NULL OR fecha >= %s)
                  AND (%s IS NULL OR fecha <= %s)
                ORDER BY fecha, hora_salida
            """, (
                incluir_historial,
                incluir_agotados,
                origen, f"%{origen}%" if origen else None,
                destino, f"%{destino}%" if destino else None,
                fecha_inicio, fecha_inicio,
                fecha_fin, fecha_fin
            ))

            vuelos = []

            for fila in cursor.fetchall():
                vuelos.append(VueloModel.from_row(fila).to_dict())

            return vuelos

        finally:
            cursor.close()
            conexion.close()
