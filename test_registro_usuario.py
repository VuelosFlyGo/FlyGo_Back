"""Prueba integral del registro, duplicados y login JWT."""

from uuid import uuid4

from app import app
from database import Database


def ejecutar():
    sufijo = uuid4().hex[:10]
    usuario = f"test{sufijo}"
    segundo_usuario = f"otro{sufijo}"
    correo = f"{usuario}@flygo.test"
    password = "FlyGo123*"
    cedula = "1710034065"
    ids = []

    try:
        with app.test_client() as cliente:
            registro = cliente.post("/api/usuarios/registro", json={
                "usuario": usuario,
                "password": password,
                "nombre_completo": "Usuario Temporal",
                "correo": correo,
                "cedula": cedula,
            })
            assert registro.status_code == 201, registro.get_json()
            ids.append(registro.get_json()["usuario_id"])

            login = cliente.post("/api/auth/login", json={
                "usuario": usuario,
                "password": password,
            })
            assert login.status_code == 200, login.get_json()
            assert len(login.get_json()["token"].split(".")) == 3

            duplicado_usuario = cliente.post("/api/usuarios/registro", json={
                "usuario": usuario,
                "password": password,
                "nombre_completo": "Usuario Repetido",
                "correo": f"otro{sufijo}@flygo.test",
                "cedula": cedula,
            })
            assert duplicado_usuario.status_code == 409, duplicado_usuario.get_json()

            duplicado_correo = cliente.post("/api/usuarios/registro", json={
                "usuario": segundo_usuario,
                "password": password,
                "nombre_completo": "Correo Repetido",
                "correo": correo,
                "cedula": cedula,
            })
            assert duplicado_correo.status_code == 409, duplicado_correo.get_json()

            print("REGISTRO CORRECTO", {
                "registro": registro.status_code,
                "login_jwt": login.status_code,
                "usuario_duplicado": duplicado_usuario.status_code,
                "correo_duplicado": duplicado_correo.status_code,
            })
    finally:
        if ids:
            conexion = Database.obtener_conexion()
            cursor = conexion.cursor()
            cursor.execute("DELETE FROM tokens WHERE usuario_id = ANY(%s)", (ids,))
            cursor.execute("DELETE FROM usuarios WHERE id = ANY(%s)", (ids,))
            conexion.commit()
            cursor.close()
            conexion.close()


if __name__ == "__main__":
    ejecutar()
