ALTER TABLE vuelos
ADD COLUMN IF NOT EXISTS fecha_desactivacion TIMESTAMPTZ;

COMMENT ON COLUMN vuelos.fecha_desactivacion IS
'Fecha en que el administrador aplicó el borrado lógico al vuelo.';
