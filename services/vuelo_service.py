import psycopg2.extras
from database import Database
from models.vuelo_model import VueloModel


class VueloService:

    def buscar_vuelos(
        self, origen=None, destino=None, fecha_inicio=None, fecha_fin=None,
        incluir_agotados=False, incluir_historial=False
    ):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("""
                SELECT id, aerolinea, origen, destino, fecha,
                       hora_salida, hora_llegada, precio,
                       asientos_disponibles, estado,
                       CASE
                           WHEN estado = FALSE THEN 'INACTIVO'
                           WHEN (fecha + hora_salida) <=
                                (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil')
                               THEN 'FINALIZADO'
                           WHEN asientos_disponibles <= 0 THEN 'AGOTADO'
                           ELSE 'VIGENTE'
                       END AS situacion,
                       (SELECT COUNT(*) FROM asientos_vuelo av WHERE av.vuelo_id = vuelos.id) AS total_asientos
                FROM vuelos
                WHERE (%s = TRUE OR estado = TRUE)
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
