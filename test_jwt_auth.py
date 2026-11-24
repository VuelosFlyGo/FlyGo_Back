"""Prueba integral y reproducible del contrato JWT de FlyGo."""

import os
from datetime import datetime, timedelta, timezone

import jwt

from app import app
from utils.seguridad import Seguridad


def ejecutar():
    usuario = os.environ["JWT_TEST_USER"]
    password = os.environ["JWT_TEST_PASSWORD"]

    with app.test_client() as cliente:
        login = cliente.post(
            "/api/auth/login",
            json={"usuario": usuario, "password": password},
        )
        assert login.status_code == 200, login.get_json()
        cuerpo = login.get_json()
        token = cuerpo["token"]
        assert len(token.split(".")) == 3

        payload = Seguridad.decodificar_token(token)
        for claim in ("sub", "rol", "iat", "exp", "jti", "iss", "aud"):
            assert claim in payload, claim

        headers = {"Authorization": f"Bearer {token}"}
        acceso = cliente.get("/api/vuelos", headers=headers)
        assert acceso.status_code == 200, acceso.get_json()

        ultimo = "A" if token[-1] != "A" else "B"
        alterado = cliente.get(
            "/api/vuelos",
            headers={"Authorization": f"Bearer {token[:-1]}{ultimo}"},
        )
        assert alterado.status_code == 401, alterado.get_json()

        ahora = datetime.now(timezone.utc)
        vencido = jwt.encode(
            {
                "sub": payload["sub"],
                "rol": payload["rol"],
                "iat": ahora - timedelta(hours=2),
                "exp": ahora - timedelta(hours=1),
                "jti": payload["jti"],
                "iss": "flygo-api",
                "aud": "flygo-app",
            },
            Seguridad._jwt_secret(),
            algorithm="HS256",
        )
        expirado = cliente.get(
            "/api/vuelos",
            headers={"Authorization": f"Bearer {vencido}"},
        )
        assert expirado.status_code == 401, expirado.get_json()

        logout = cliente.post("/api/auth/logout", headers=headers)
        assert logout.status_code == 200, logout.get_json()

        revocado = cliente.get("/api/vuelos", headers=headers)
        assert revocado.status_code == 401, revocado.get_json()

        print(
            "JWT CORRECTO",
            {
                "claims": sorted(payload.keys()),
                "acceso": acceso.status_code,
                "alterado": alterado.status_code,
                "expirado": expirado.status_code,
                "logout": logout.status_code,
                "revocado": revocado.status_code,
            },
        )


if __name__ == "__main__":
    ejecutar()
