from datetime import date, timedelta
from uuid import uuid4

import psycopg2.extras

from database import Database
from services.asiento_service import AsientoService
from services.boleto_pdf_service import BoletoPdfService
from utils.seguridad import Seguridad
from app import app


def ejecutar():
    conexion = Database.obtener_conexion()
    cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    vuelo_id = None
    reserva_id = None
    jti = None
    try:
        cursor.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1")
        usuario_id = cursor.fetchone()["id"]
        cursor.execute("""
            INSERT INTO vuelos (
                aerolinea, origen, destino, fecha, hora_salida, hora_llegada,
                precio, asientos_disponibles, estado, version
            ) VALUES (%s, 'Quito', 'Guayaquil', %s, '08:00', '09:00', 25, 3, TRUE, 1)
            RETURNING id
        """, (f"TEST-AMPLIACION-{uuid4().hex[:8]}", date.today() + timedelta(days=20)))
        vuelo_id = cursor.fetchone()["id"]
        for asiento in ("1A", "1B", "1C"):
            cursor.execute("""
                INSERT INTO asientos_vuelo (vuelo_id, numero_asiento, estado)
                VALUES (%s, %s, 'DISPONIBLE')
            """, (vuelo_id, asiento))
        conexion.commit()

        reserva = AsientoService().crear_reserva_con_asientos(usuario_id, vuelo_id, ["1A"])
        reserva_id = reserva["id"]
        AsientoService().actualizar_reserva_con_asientos(
            usuario_id, reserva_id, ["1A", "1B"]
        )

        cursor.execute("""
            SELECT r.cantidad_asientos, r.total, r.modificada,
                   v.asientos_disponibles,
                   ARRAY_AGG(av.numero_asiento ORDER BY av.numero_asiento) AS asientos
            FROM reservas r
            JOIN vuelos v ON v.id = r.vuelo_id
            JOIN asientos_vuelo av ON av.reserva_id = r.id
            WHERE r.id = %s
            GROUP BY r.id, v.id
        """, (reserva_id,))
        estado = cursor.fetchone()
        assert estado["cantidad_asientos"] == 2
        assert float(estado["total"]) == 50.0
        assert estado["modificada"] is True
        assert estado["asientos_disponibles"] == 1
        assert list(estado["asientos"]) == ["1A", "1B"]

        datos_pdf = BoletoPdfService().obtener_reserva(usuario_id, reserva_id)
        pdf = BoletoPdfService().generar(datos_pdf)
        assert len(pdf.getvalue()) > 2000

        cursor.execute(
            "SELECT id, rol FROM usuarios WHERE id = %s", (usuario_id,)
        )
        token, jti, expiracion = Seguridad.generar_token(cursor.fetchone())
        cursor.execute("""
            INSERT INTO tokens (usuario_id, token, fecha_expiracion, activo)
            VALUES (%s, %s, %s, TRUE)
        """, (usuario_id, jti, expiracion))
        conexion.commit()
        with app.test_client() as cliente:
            respuesta_pdf = cliente.get(
                f"/api/reservas/{reserva_id}/boletos.pdf",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert respuesta_pdf.status_code == 200, respuesta_pdf.get_json()
            assert respuesta_pdf.mimetype == "application/pdf"
            assert len(respuesta_pdf.data) > 2000
            conflicto = cliente.put(
                f"/api/reservas/{reserva_id}/asientos",
                headers={"Authorization": f"Bearer {token}"},
                json={"asientos": ["1A", "1B", "1C"]},
            )
            assert conflicto.status_code == 409, conflicto.get_json()
            assert "ya fue modificada" in conflicto.get_json()["detalle"]

        try:
            AsientoService().actualizar_reserva_con_asientos(
                usuario_id, reserva_id, ["1A", "1B", "1C"]
            )
            raise AssertionError("La segunda modificación debió ser rechazada")
        except ValueError as error:
            assert "ya fue modificada" in str(error)

        print("MODIFICACION AMPLIADA CORRECTA", dict(estado))
    finally:
        conexion.rollback()
        if vuelo_id is not None:
            if jti is not None:
                cursor.execute("DELETE FROM tokens WHERE token = %s", (jti,))
            cursor.execute("DELETE FROM asientos_vuelo WHERE vuelo_id = %s", (vuelo_id,))
            cursor.execute("DELETE FROM reservas WHERE vuelo_id = %s", (vuelo_id,))
            cursor.execute("DELETE FROM vuelos WHERE id = %s", (vuelo_id,))
            conexion.commit()
        cursor.close()
        conexion.close()


if __name__ == "__main__":
    ejecutar()
