# FlyGo API

## Configuracion local

1. Copia `.env.example` como `.env`.
2. Completa los datos de conexión que aparecen en Supabase, en **Project Settings > Database**.
3. Define `JWT_SECRET` con un valor aleatorio de al menos 32 caracteres. En Render debe configurarse también como variable secreta del servicio.
4. Ejecuta `supabase_schema.sql`, `migration_reserva_un_solo_cambio.sql`, `migration_concurrencia_reservas.sql` y `migration_jwt.sql`, en ese orden, desde el **SQL Editor** de Supabase.
5. Instala las dependencias con `pip install -r requirements.txt`.
6. Activa el entorno virtual y ejecuta `python app.py`.

## Autenticación

- JWT firmado con HS256.
- Claims: `sub`, `rol`, `iat`, `exp`, `jti`, `iss` y `aud`.
- Duración predeterminada: 120 minutos, configurable con `JWT_EXPIRATION_MINUTES`.
- Supabase almacena únicamente el `jti` para revocación; nunca guarda el JWT completo.
- Cerrar sesión invalida el `jti` inmediatamente.

La API se inicia en `http://127.0.0.1:5000`.
