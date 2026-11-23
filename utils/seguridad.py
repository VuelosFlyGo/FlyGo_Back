import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt


class Seguridad:
    @staticmethod
    def generar_hash(password):
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _jwt_secret():
        secret = os.getenv("JWT_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError(
                "JWT_SECRET debe existir y tener al menos 32 caracteres"
            )
        return secret

    @staticmethod
    def generar_token(usuario):
        ahora = datetime.now(timezone.utc)
        minutos = int(os.getenv("JWT_EXPIRATION_MINUTES", "120"))
        expiracion = ahora + timedelta(minutes=minutos)
        jti = secrets.token_hex(16)
        payload = {
            "sub": str(usuario["id"]),
            "rol": usuario["rol"],
            "iat": ahora,
            "exp": expiracion,
            "jti": jti,
            "iss": "flygo-api",
            "aud": "flygo-app",
        }
        token = jwt.encode(
            payload,
            Seguridad._jwt_secret(),
            algorithm="HS256",
        )
        return token, jti, expiracion

    @staticmethod
    def decodificar_token(token, verificar_expiracion=True):
        return jwt.decode(
            token,
            Seguridad._jwt_secret(),
            algorithms=["HS256"],
            audience="flygo-app",
            issuer="flygo-api",
            options={"verify_exp": verificar_expiracion},
        )
