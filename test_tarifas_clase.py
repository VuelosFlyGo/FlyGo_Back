"""Validación de importes y cupos con una transacción que siempre se revierte."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from xml.etree import ElementTree

from database import Database
from services.admin_vuelo_service import AdminVueloService
from services.asiento_service import AsientoService
from services.factura_service import FacturaService
from services.reserva_service import ReservaService
from services.vuelo_service import VueloService
from test_catalogo_aviones import ConexionTransaccional


def ejecutar():
    conexion = Database.obtener_conexion()
    admin, asientos = AdminVueloService(), AsientoService()
    factura, reservas = FacturaService(), ReservaService()
    try:
        with patch.object(Database, "obtener_conexion",
                          return_value=ConexionTransaccional(conexion)):
            avion = admin.listar_aviones()[0]
            primera_turista = f"{avion['asientos_ejecutiva'] // 4 + 1}A"
            otra_turista = primera_turista[:-1] + "B"
            datos = dict(
                aerolinea="Prueba tarifas", origen="Quito", destino="Cuenca",
                fecha=str(date.today() + timedelta(days=30)), hora_salida="10:00",
                hora_llegada="11:00", precio=80, precio_ejecutiva=140, avion_id=avion["id"],
            )
            try:
                admin._tarifas(dict(datos, precio_ejecutiva=80), avion["id"])
            except ValueError as error:
                assert "mayor" in str(error)
            else:
                raise AssertionError("Las clases deben tener tarifas distintas")
            vuelo_id = admin.crear_vuelo_con_asientos(datos)["id"]
            with conexion.cursor() as cursor:
                cursor.execute("SELECT id FROM usuarios WHERE estado = TRUE LIMIT 1")
                usuario_id = cursor.fetchone()[0]
            reserva = asientos.crear_reserva_con_asientos(
                usuario_id, vuelo_id, ["1A", primera_turista], total_esperado=220,
            )
            reserva_id = reserva["id"]
            assert reserva["total"] == 220
            v = next(v for v in VueloService().buscar_vuelos() if v["id"] == vuelo_id)
            assert v["precio_ejecutiva"] == 140 and v["precio"] == 80
            assert v["ejecutiva_disponibles"] == avion["asientos_ejecutiva"] - 1
            assert v["turista_disponibles"] == avion["asientos_turista"] - 1
            datos.update(precio=90, precio_ejecutiva=150)
            admin.editar_vuelo(vuelo_id, datos)
            mapa = {a["numero_asiento"]: a for a in asientos.listar_asientos_por_vuelo(vuelo_id)}
            assert mapa["1A"]["precio"] == 150 and mapa[primera_turista]["precio"] == 90
            original = factura.obtener_factura(usuario_id, reserva_id)
            assert original["total"] == Decimal("220.00")
            xml = ElementTree.parse(factura.generar_xml(original))
            assert {a.attrib["precioUnitario"] for a in xml.findall("./detalle/asientos/asiento")} == {"140.00", "80.00"}
            assert factura.generar_pdf(original).read(4) == b"%PDF"
            asientos.actualizar_reserva_con_asientos(
                usuario_id, reserva_id, ["1B", primera_turista, otra_turista],
                total_esperado=330,
            )
            modificada = factura.obtener_factura(usuario_id, reserva_id)
            assert modificada["total"] == Decimal("330.00")
            assert {a["precio"] for a in modificada["detalle_asientos"]} == {90, 150}
            assert reservas.cancelar_reserva(usuario_id, reserva_id) == "CANCELADA"
            cantidad = reservas.crear_reserva(usuario_id, vuelo_id, 1)
            assert cantidad["total"] == 90
            dato = factura.obtener_factura(usuario_id, cantidad["id"])
            assert dato["detalle_asientos"][0]["clase"] == "TURISTA"
            # Última operación: su rollback debe eliminar la transacción de prueba.
            try:
                asientos.crear_reserva_con_asientos(usuario_id, vuelo_id, ["1A"], total_esperado=80)
            except ValueError as error:
                assert "tarifa cambió" in str(error)
            else:
                raise AssertionError("La tarifa desactualizada no debe confirmarse")
            print("Tarifas mixtas, cupos, modificación, factura y cambio de precio: OK")
    finally:
        conexion.rollback()
        conexion.close()


if __name__ == "__main__":
    ejecutar()
