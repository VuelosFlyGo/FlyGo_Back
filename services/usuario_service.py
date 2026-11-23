from database import Database
from utils.seguridad import Seguridad


class UsuarioService:

    def registrar_usuario(self, datos):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor()

        try:
            password_hash = Seguridad.generar_hash(datos["password"])

            cursor.execute("""
                INSERT INTO usuarios
                (usuario, password_hash, nombre_completo, correo, cedula)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                datos["usuario"],
                password_hash,
                datos["nombre_completo"],
                datos["correo"],
                datos["cedula"]
            ))

            usuario_id = cursor.fetchone()[0]
            conexion.commit()
            return usuario_id

        except Exception as e:
            conexion.rollback()
            raise e

        finally:
            cursor.close()
            conexion.close()
