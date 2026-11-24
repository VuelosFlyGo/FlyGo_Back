-- Corte de sesiones opacas y soporte para revocación JWT mediante jti.
UPDATE tokens SET activo = FALSE WHERE activo = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tokens_jti
ON tokens(token);

CREATE INDEX IF NOT EXISTS idx_tokens_validacion
ON tokens(token, usuario_id, activo, fecha_expiracion);

COMMENT ON COLUMN tokens.token IS
'Identificador jti del JWT. El JWT completo nunca se almacena en la base de datos.';
