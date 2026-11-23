"""Prueba reproducible: dos clientes compiten por el mismo asiento."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from uuid import uuid4

import psycopg2.extras

from database import Database
from services.asiento_service import AsientoService


def preparar_escenario():
    conexion = Database.obtener_conexion()
    cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    etiqueta = f"TEST-CONCURRENCIA-{uuid4().hex[:8]}"
    try:
        cursor.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1")
        usuario = cursor.fetchone()
        if usuario is None:
            raise RuntimeError("Se necesita al menos un usuario para ejecutar la prueba")

        cursor.execute("""
            INSERT INTO vuelos (
                aerolinea, origen, destino, fecha, hora_salida, hora_llegada,
                precio, asientos_disponibles, estado, version
            ) VALUES (%s, 'Quito', 'Guayaquil', %s, '10:00', '11:00', 10, 1, TRUE, 1)
            RETURNING id
        """, (etiqueta, date.today() + timedelta(days=30)))
        vuelo_id = cursor.fetchone()["id"]
        cursor.execute("""
            INSERT INTO asientos_vuelo (vuelo_id, numero_asiento, estado)
            VALUES (%s, '1A', 'DISPONIBLE')
        """, (vuelo_id,))
        conexion.commit()
        return usuario["id"], vuelo_id
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.close()
        conexion.close()


def limpiar_escenario(vuelo_id):
    conexion = Database.obtener_conexion()
    cursor = conexion.cursor()
    try:
        cursor.execute("DELETE FROM asientos_vuelo WHERE vuelo_id = %s", (vuelo_id,))
        cursor.execute("DELETE FROM reservas WHERE vuelo_id = %s", (vuelo_id,))
        cursor.execute("DELETE FROM vuelos WHERE id = %s", (vuelo_id,))
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.close()
        conexion.close()


def ejecutar():
    usuario_id, vuelo_id = preparar_escenario()
    barrera = Barrier(2)

    def reservar():
        barrera.wait()
        try:
            resultado = AsientoService().crear_reserva_con_asientos(
                usuario_id, vuelo_id, ["1A"]
            )
            return "CONFIRMADA", resultado["id"]
        except Exception as error:
            return "CONFLICTO", str(error).splitlines()[0]

    try:
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            resultados = list(ejecutor.map(lambda _: reservar(), range(2)))

        estados = sorted(resultado[0] for resultado in resultados)
        if estados != ["CONFIRMADA", "CONFLICTO"]:
            raise AssertionError(f"Resultado inesperado: {resultados}")

        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM reservas WHERE vuelo_id = %s AND estado = 'ACTIVA') AS reservas,
                (SELECT asientos_disponibles FROM vuelos WHERE id = %s) AS cupos,
                (SELECT COUNT(*) FROM asientos_vuelo
                 WHERE vuelo_id = %s AND estado = 'RESERVADO') AS asientos_reservados
        """, (vuelo_id, vuelo_id, vuelo_id))
        verificacion = cursor.fetchone()
        cursor.close()
        conexion.close()

        esperado = {"reservas": 1, "cupos": 0, "asientos_reservados": 1}
        if dict(verificacion) != esperado:
            raise AssertionError(f"Estado inconsistente: {dict(verificacion)}")

        print("PRUEBA CORRECTA", resultados, dict(verificacion))
    finally:
        limpiar_escenario(vuelo_id)


if __name__ == "__main__":
    ejecutar()
