ALTER TABLE reservas
ADD COLUMN IF NOT EXISTS modificada BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN reservas.modificada IS
'Indica que el cliente ya utilizó el único cambio permitido para la reserva.';
