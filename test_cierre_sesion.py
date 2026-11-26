import os
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt

from app import app
from database import Database
from utils.seguridad import Seguridad


class ConexionDePrueba:
    """Ejecuta las consultas del servicio sobre un almacén aislado."""

    def __init__(self, conexion):
        self.conexion = conexion

    def cursor(self, **_):
        cursor = self.conexion.cursor()

        class Cursor:
            def execute(self, consulta, parametros):
                cursor.execute(consulta.replace("%s", "?"), parametros)

            def __getattr__(self, nombre):
                return getattr(cursor, nombre)

        return Cursor()

    def close(self):
        pass

    def __getattr__(self, nombre):
        return getattr(self.conexion, nombre)


class CierreSesionTest(unittest.TestCase):
    def test_revoca_dos_tokens_de_la_misma_cuenta_y_respeta_los_demas(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())
        db.executescript("""
            CREATE TABLE usuarios (
                id INTEGER, usuario TEXT, nombre_completo TEXT, correo TEXT,
                rol TEXT, estado BOOLEAN
            );
            CREATE TABLE tokens (
                usuario_id INTEGER, token TEXT, fecha_expiracion TEXT,
                activo BOOLEAN
            );
            INSERT INTO usuarios VALUES
                (1, 'cliente1', 'Cliente 1', '', 'cliente', TRUE),
                (2, 'cliente2', 'Cliente 2', '', 'cliente', TRUE);
        """)
        with patch.dict(os.environ, {
            "JWT_SECRET": "secreto-exclusivo-de-prueba-para-jwt",
            "JWT_EXPIRATION_MINUTES": "3",
        }):
            def emitir(usuario_id):
                token, jti, exp = Seguridad.generar_token(
                    {"id": usuario_id, "rol": "cliente"},
                )
                db.execute(
                    "INSERT INTO tokens VALUES (?, ?, ?, TRUE)",
                    (usuario_id, jti, exp.isoformat()),
                )
                return {"Authorization": f"Bearer {token}"}

            primera = emitir(1)
            segunda = emitir(1)
            otra_cuenta = emitir(2)
            payload = Seguridad.decodificar_token(primera["Authorization"].split()[1])
            self.assertEqual(payload["exp"] - payload["iat"], 180)
            payload["iat"] -= 240
            payload["exp"] += 3600
            legado = jwt.encode(payload, Seguridad._jwt_secret(), algorithm="HS256")
            sesion_anterior = {"Authorization": f"Bearer {legado}"}
            payload["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            vencido = jwt.encode(payload, Seguridad._jwt_secret(), algorithm="HS256")
            expirado = {"Authorization": f"Bearer {vencido}"}
            db.commit()

            with patch.object(Database, "obtener_conexion", return_value=ConexionDePrueba(db)):
                cliente = app.test_client()
                consultar = lambda headers: cliente.get("/api/auth/session", headers=headers)
                cerrar = lambda headers: cliente.post("/api/auth/logout", headers=headers)
                self.assertEqual(consultar(primera).status_code, 204)
                self.assertEqual(consultar(segunda).status_code, 204)
                self.assertEqual(consultar(expirado).status_code, 401)
                respuesta = consultar(sesion_anterior)
                self.assertEqual(respuesta.status_code, 401)
                self.assertEqual(respuesta.get_json()["codigo"], "SESION_EXPIRADA")
                self.assertEqual(cerrar(expirado).status_code, 401)
                self.assertEqual(consultar(segunda).status_code, 204)
                self.assertEqual(cerrar(primera).status_code, 200)
                self.assertEqual(consultar(primera).status_code, 401)
                self.assertEqual(consultar(segunda).status_code, 401)
                self.assertEqual(consultar(otra_cuenta).status_code, 204)
                nueva = emitir(1)
                self.assertEqual(cerrar(primera).status_code, 401)
                self.assertEqual(consultar(nueva).status_code, 204)
