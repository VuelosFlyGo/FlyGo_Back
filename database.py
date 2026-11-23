import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


class Database:
    @staticmethod
    def obtener_conexion():
        try:
            conexion = psycopg2.connect(
                host=os.getenv("DB_HOST"),
                database=os.getenv("DB_NAME", "postgres"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD"),
                port=os.getenv("DB_PORT", "5432"),
                sslmode="require",
                connect_timeout=10
            )

            return conexion

        except Exception:
            raise
