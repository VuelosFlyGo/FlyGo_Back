"""Pruebas de las reglas de cancelación con datos temporales, sin persistirlos."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from database import Database
from services.admin_vuelo_service import AdminVueloService
from services.asiento_service import AsientoService
from services.reserva_service import ReservaService
from services.vuelo_service import VueloService


class ConexionPrueba:
    def __init__(self, conexion):
        self.conexion = conexion
        with conexion.cursor() as cursor:
            cursor.execute("SAVEPOINT operacion_prueba")

    def __getattr__(self, nombre):
        return getattr(self.conexion, nombre)

    def commit(self):
        with self.conexion.cursor() as cursor:
            cursor.execute("RELEASE SAVEPOINT operacion_prueba")

    def rollback(self):
        with self.conexion.cursor() as cursor:
            cursor.execute("ROLLBACK TO SAVEPOINT operacion_prueba")
            cursor.execute("RELEASE SAVEPOINT operacion_prueba")

    def close(self):
        pass


def ejecutar():
    conexion = Database.obtener_conexion()
    admin = AdminVueloService()
    reservas = ReservaService()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT id FROM usuarios WHERE estado = TRUE LIMIT 1")
            usuario = cursor.fetchone()
            assert usuario, "Se requiere un usuario de prueba existente"
            usuario_id = usuario[0]

        with patch.object(Database, "obtener_conexion",
                          side_effect=lambda: ConexionPrueba(conexion)):
            avion = admin.listar_aviones()[0]
            ahora = datetime.now(timezone(timedelta(hours=-5)))
            for horas in (23, 25):
                salida = ahora + timedelta(hours=horas)
                # Evitar cambios de día en los horarios de llegada.
                if salida.hour == 23:
                    salida = (salida.replace(hour=22, minute=30) if horas == 23
                              else (salida + timedelta(days=1)).replace(hour=0, minute=5))
                llegada = salida + timedelta(minutes=20)
                vuelo = admin.crear_vuelo_con_asientos({
                    "aerolinea": "FlyGo Prueba Cancelación",
                    "origen": "Quito",
                    "destino": "Cuenca",
                    "fecha": salida.date().isoformat(),
                    "hora_salida": salida.strftime("%H:%M"),
                    "hora_llegada": llegada.strftime("%H:%M"),
                    "precio": 80,
                    "avion_id": avion["id"],
                })
                id_vuelo = vuelo["id"]
                reserva = AsientoService().crear_reserva_con_asientos(
                    usuario_id, id_vuelo, ["1A"])
                id_reserva = reserva["id"]

                def estado():
                    items = reservas.listar_mis_reservas(usuario_id)
                    r = next(item for item in items if item["id"] == id_reserva)
                    v = next(item for item in VueloService().buscar_vuelos()
                             if item["id"] == id_vuelo)
                    return r, v

                r, v = estado()
                assert r["puede_cancelar"] == (horas == 25)
                assert v["reservas_activas"] == 1
                try:
                    admin.eliminar_vuelo(id_vuelo)
                except ValueError as e:
                    assert "reservas activas" in str(e)
                else:
                    raise AssertionError("No se debe desactivar un vuelo reservado")

                resultado = reservas.cancelar_reserva(usuario_id, id_reserva)
                r, despues = estado()
                if horas == 23:
                    assert resultado == "PLAZO_CANCELACION_VENCIDO"
                    assert r["estado"] == "ACTIVA"
                    assert r["asientos"] == ["1A"]
                    assert despues["asientos_disponibles"] == v["asientos_disponibles"]
                else:
                    assert resultado == "CANCELADA"
                    assert r["estado"] == "CANCELADA" and not r["asientos"]
                    assert despues["asientos_disponibles"] == v["asientos_disponibles"] + 1
                    assert despues["reservas_activas"] == 0
                    assert admin.eliminar_vuelo(id_vuelo)
                    assert all(item["id"] != id_vuelo for item in VueloService().buscar_vuelos())
            print("23 h: bloqueo sin pérdida de asientos; 25 h: cancelación, liberación y desactivación lógica: OK")
    finally:
        conexion.rollback()
        conexion.close()


if __name__ == "__main__":
    ejecutar()
