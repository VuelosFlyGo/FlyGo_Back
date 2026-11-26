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
- `GET /api/auth/session` verifica un token Bearer y responde `204` si sigue activo o `401` si venció o fue revocado.
- `POST /api/auth/logout` requiere un token activo y revoca todas las sesiones activas de su cuenta.

## Catálogo de aeronaves

- Ejecutar `migration_catalogo_aviones.sql` antes de desplegar este cambio.
- `GET /api/admin/aviones` lista los modelos preconfigurados y las plazas de cada clase. Requiere rol administrador.
- Ejecutar también `migration_tarifas_clase.sql`. La tarifa turista se conserva en `precio` y `precio_ejecutiva` debe ser mayor en vuelos con aeronave.
- `POST /api/admin/vuelos` requiere `avion_id` y genera las plazas en una transacción a partir del catálogo. Si un cliente anterior omite la tarifa ejecutiva, se calcula una tarifa inicial un 50 % mayor.
- `PUT /api/admin/vuelos/{id}` admite seleccionar otra aeronave si el vuelo carece de reservas. Los vuelos anteriores conservan su cabina al actualizar el itinerario.
- `GET /api/vuelos` incluye `avion_id` y `avion_modelo`; `GET /api/vuelos/{id}/asientos` incluye `clase` (EJECUTIVA o TURISTA).
- La consulta de vuelos incluye cupos y tarifas por clase. La consulta de asientos devuelve su tarifa actual. Las operaciones de reserva admiten `total_esperado` y devuelven HTTP 409 con `TARIFA_ACTUALIZADA` si la cotización cambió. Cada asiento reservado guarda su tarifa confirmada para facturación.
- Cerrar sesión invalida el `jti` inmediatamente.

La API se inicia en `http://127.0.0.1:5000`.
