"""Comprueba la integración con PostgreSQL sin conservar vuelos de prueba."""

from datetime import date, timedelta
from unittest.mock import patch

from database import Database
from services.admin_vuelo_service import AdminVueloService
from services.asiento_service import AsientoService
from services.vuelo_service import VueloService


class ConexionTransaccional:
    def __init__(self, conexion):
        self.conexion = conexion

    def commit(self):
        pass

    def close(self):
        pass

    def __getattr__(self, atributo):
        return getattr(self.conexion, atributo)


def ejecutar():
    admin = AdminVueloService()
    conexion = Database.obtener_conexion()
    try:
        with patch.object(Database, "obtener_conexion",
                          return_value=ConexionTransaccional(conexion)):
            aviones = admin.listar_aviones()
            assert len(aviones) >= 2
            primero, segundo = aviones[:2]
            datos = {
                "aerolinea": "Prueba de cabina",
                "origen": "Quito",
                "destino": "Cuenca",
                "fecha": str(date.today() + timedelta(days=30)),
                "hora_salida": "10:00",
                "hora_llegada": "11:00",
                "precio": 80,
                "avion_id": primero["id"],
            }
            vuelo = admin.crear_vuelo_con_asientos(datos)
            vuelo_id = vuelo["id"]

            def comprobar(avion):
                asientos = AsientoService().listar_asientos_por_vuelo(vuelo_id)
                assert len(asientos) == avion["capacidad"]
                assert len({a["numero_asiento"] for a in asientos}) == len(asientos)
                assert sum(a["clase"] == "EJECUTIVA" for a in asientos) == avion["asientos_ejecutiva"]
                assert sum(a["clase"] == "TURISTA" for a in asientos) == avion["asientos_turista"]
                registro = next(v for v in VueloService().buscar_vuelos()
                                if v["id"] == vuelo_id)
                assert registro["avion_id"] == avion["id"]
                assert registro["total_asientos"] == avion["capacidad"]
                assert registro["avion_modelo"] == avion["modelo"]

            comprobar(primero)
            datos["avion_id"] = segundo["id"]
            admin.editar_vuelo(vuelo_id, datos)
            comprobar(segundo)

            with conexion.cursor() as cursor:
                cursor.execute("SELECT id FROM usuarios WHERE estado = TRUE LIMIT 1")
                usuario_id = cursor.fetchone()[0]
            AsientoService().crear_reserva_con_asientos(usuario_id, vuelo_id, ["1A"])
            admin.editar_vuelo(vuelo_id, datos)
            reservado = next(a for a in AsientoService().listar_asientos_por_vuelo(vuelo_id)
                             if a["numero_asiento"] == "1A")
            assert reservado["estado"] == "RESERVADO" and reservado["clase"] == "EJECUTIVA"
            datos["avion_id"] = primero["id"]
            try:
                admin.editar_vuelo(vuelo_id, datos)
            except ValueError as error:
                assert "con reservas" in str(error)
            else:
                raise AssertionError("El avión de un vuelo reservado debe conservarse")
            print("Catálogo, clases, cambio de aeronave y protección de reservas: OK")
    finally:
        conexion.rollback()
        conexion.close()


if __name__ == "__main__":
    ejecutar()
