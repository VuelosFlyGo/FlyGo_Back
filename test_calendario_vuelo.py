import unittest
from datetime import datetime, time, timedelta, timezone

from services.admin_vuelo_service import AdminVueloService


class CalendarioVueloTest(unittest.TestCase):
    def test_fechas_y_horarios(self):
        hoy = datetime.now(timezone(timedelta(hours=-5))).date()
        datos = {
            "fecha": (hoy + timedelta(days=1)).isoformat(),
            "hora_salida": "08:00",
            "hora_llegada": "09:00",
        }
        AdminVueloService._validar_itinerario(datos)
        for fecha in [(hoy - timedelta(days=1)).isoformat(),
                      (hoy + timedelta(days=731)).isoformat(), "2027-02-30"]:
            with self.subTest(fecha=fecha), self.assertRaises(ValueError):
                AdminVueloService._validar_itinerario(dict(datos, fecha=fecha))
        with self.assertRaises(ValueError):
            AdminVueloService._validar_itinerario(dict(datos, hora_llegada="07:59"))
        with self.assertRaises(ValueError):
            AdminVueloService._validar_itinerario(dict(datos, hora_salida="25:00"))
        with self.assertRaises(ValueError):
            AdminVueloService._validar_itinerario(dict(datos, fecha=hoy.isoformat(), hora_salida="00:00"))

        historico = {
            "fecha": hoy - timedelta(days=2),
            "hora_salida": time(8),
            "hora_llegada": time(9),
        }
        AdminVueloService._validar_itinerario(
            dict(datos, fecha=historico["fecha"].isoformat()), historico,
        )
        with self.assertRaises(ValueError):
            AdminVueloService._validar_itinerario(
                dict(datos, fecha=historico["fecha"].isoformat(), hora_llegada="10:00"),
                historico,
            )
