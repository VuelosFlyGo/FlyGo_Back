from datetime import date, timedelta
from uuid import uuid4

import psycopg2.extras

from database import Database
from services.admin_vuelo_service import AdminVueloService
from services.asiento_service import AsientoService
from services.vuelo_service import VueloService


def ejecutar():
    conexion = Database.obtener_conexion()
    cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    vuelo_id = None
    try:
        cursor.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1")
        usuario_id = cursor.fetchone()["id"]
        datos = {
            "aerolinea": f"TEST-CAPACIDAD-{uuid4().hex[:8]}",
            "origen": "Quito",
            "destino": "Cuenca",
            "fecha": str(date.today() + timedelta(days=30)),
            "hora_salida": "10:00",
            "hora_llegada": "11:00",
            "precio": 40,
            "cantidad_asientos": 4,
        }
        vuelo = AdminVueloService().crear_vuelo_con_asientos(datos)
        vuelo_id = vuelo["id"]
        publicados = VueloService().buscar_vuelos(
            origen="Quito", destino="Cuenca"
        )
        assert any(v["id"] == vuelo_id for v in publicados)
        AsientoService().crear_reserva_con_asientos(usuario_id, vuelo_id, ["1A"])

        datos["cantidad_asientos"] = 6
        ampliado = AdminVueloService().editar_vuelo(vuelo_id, datos)
        assert ampliado["total_asientos"] == 6
        assert ampliado["asientos_disponibles"] == 5

        datos["cantidad_asientos"] = 2
        reducido = AdminVueloService().editar_vuelo(vuelo_id, datos)
        assert reducido["total_asientos"] == 2
        assert reducido["asientos_disponibles"] == 1

        datos["cantidad_asientos"] = 0
        try:
            AdminVueloService().editar_vuelo(vuelo_id, datos)
            raise AssertionError("La capacidad cero debió rechazarse")
        except Exception as error:
            assert "mayor a cero" in str(error)

        print("EDICION DE CAPACIDAD CORRECTA", reducido)
    finally:
        conexion.rollback()
        if vuelo_id is not None:
            cursor.execute("DELETE FROM asientos_vuelo WHERE vuelo_id = %s", (vuelo_id,))
            cursor.execute("DELETE FROM reservas WHERE vuelo_id = %s", (vuelo_id,))
            cursor.execute("DELETE FROM vuelos WHERE id = %s", (vuelo_id,))
            conexion.commit()
        cursor.close()
        conexion.close()


if __name__ == "__main__":
    ejecutar()
