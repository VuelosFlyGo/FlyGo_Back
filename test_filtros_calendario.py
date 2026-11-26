import unittest
from datetime import datetime, timedelta, timezone

from services.vuelo_service import VueloService


class FiltrosCalendarioTest(unittest.TestCase):
    def test_rangos_de_busqueda(self):
        hoy = datetime.now(timezone(timedelta(hours=-5))).date()
        ayer = hoy - timedelta(days=1)
        limite = hoy + timedelta(days=730)
        validar = VueloService.validar_fechas_busqueda
        self.assertEqual(validar(None, None), (None, None))
        self.assertEqual(validar(hoy.isoformat(), limite.isoformat()), (hoy, limite))
        self.assertEqual(validar(hoy.isoformat(), hoy.isoformat()), (hoy, hoy))
        self.assertEqual(validar(ayer.isoformat(), hoy.isoformat(), True), (ayer, hoy))
        for inicio, fin in [
            (ayer.isoformat(), None),
            (None, (limite + timedelta(days=1)).isoformat()),
            (limite.isoformat(), hoy.isoformat()),
            ("2027-02-30", None),
            ("20270101", None),
        ]:
            with self.subTest(inicio=inicio, fin=fin), self.assertRaises(ValueError):
                validar(inicio, fin)
        with self.assertRaises(ValueError):
            validar(hoy.isoformat(), ayer.isoformat(), True)


if __name__ == "__main__":
    unittest.main()
