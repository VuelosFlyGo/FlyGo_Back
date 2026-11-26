ALTER TABLE vuelos ADD COLUMN IF NOT EXISTS precio_ejecutiva NUMERIC(10,2);
UPDATE vuelos SET precio_ejecutiva = GREATEST(ROUND(precio * 1.5, 2), precio + 0.01)
WHERE avion_id IS NOT NULL AND precio_ejecutiva IS NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'vuelos_tarifa_ejecutiva') THEN
        ALTER TABLE vuelos ADD CONSTRAINT vuelos_tarifa_ejecutiva CHECK (
            (avion_id IS NULL AND precio_ejecutiva IS NULL)
            OR (avion_id IS NOT NULL AND precio_ejecutiva IS NOT NULL AND precio_ejecutiva > precio)
        );
    END IF;
END $$;

ALTER TABLE asientos_vuelo ADD COLUMN IF NOT EXISTS precio_reservado NUMERIC(10,2);
-- Los importes históricos proceden del total pagado, no de tarifas actuales.
UPDATE asientos_vuelo a
SET precio_reservado = ROUND(r.total / r.cantidad_asientos, 2)
FROM reservas r
WHERE a.reserva_id = r.id AND a.precio_reservado IS NULL
  AND r.cantidad_asientos > 0
  AND ROUND(r.total / r.cantidad_asientos, 2) * r.cantidad_asientos = r.total
  AND (SELECT COUNT(*) FROM asientos_vuelo b WHERE b.reserva_id = r.id) = r.cantidad_asientos;

CREATE OR REPLACE FUNCTION crear_reserva_asientos_segura(
    p_usuario_id BIGINT, p_vuelo_id BIGINT, p_asientos TEXT[]
)
RETURNS TABLE(reserva_id BIGINT, codigo_reserva VARCHAR, total NUMERIC, estado VARCHAR)
LANGUAGE plpgsql AS $$
DECLARE
    v_vuelo vuelos%ROWTYPE;
    v_cantidad INT := cardinality(p_asientos);
    v_total NUMERIC(10,2);
    v_id BIGINT;
    v_codigo VARCHAR(50);
    v_encontrados INT;
    v_libres INT;
BEGIN
    IF v_cantidad IS NULL OR v_cantidad = 0 THEN
        RAISE EXCEPTION 'Debe seleccionar al menos un asiento';
    END IF;
    IF (SELECT COUNT(DISTINCT a) FROM unnest(p_asientos) a WHERE btrim(a) <> '') <> v_cantidad THEN
        RAISE EXCEPTION 'No se permiten asientos inválidos o duplicados';
    END IF;
    SELECT * INTO v_vuelo FROM vuelos v WHERE v.id = p_vuelo_id AND v.estado = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Vuelo no encontrado o inactivo'; END IF;
    IF v_vuelo.fecha + v_vuelo.hora_salida <= (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil') THEN
        RAISE EXCEPTION 'No se pueden realizar reservas para vuelos finalizados';
    END IF;
    IF v_vuelo.asientos_disponibles < v_cantidad THEN
        RAISE EXCEPTION 'No existen asientos suficientes disponibles';
    END IF;
    PERFORM av.id FROM asientos_vuelo av
    WHERE av.vuelo_id = p_vuelo_id AND av.numero_asiento = ANY(p_asientos)
    ORDER BY av.id FOR UPDATE;
    SELECT COUNT(*), COUNT(*) FILTER (WHERE av.estado = 'DISPONIBLE' AND av.reserva_id IS NULL),
           SUM(CASE WHEN av.clase = 'EJECUTIVA' THEN v_vuelo.precio_ejecutiva ELSE v_vuelo.precio END)
    INTO v_encontrados, v_libres, v_total
    FROM asientos_vuelo av
    WHERE av.vuelo_id = p_vuelo_id AND av.numero_asiento = ANY(p_asientos);
    IF v_encontrados <> v_cantidad THEN RAISE EXCEPTION 'Uno o más asientos no existen para este vuelo'; END IF;
    IF v_libres <> v_cantidad THEN RAISE EXCEPTION 'Uno o más asientos ya no están disponibles por otra reserva'; END IF;
    v_codigo := 'FG-' || upper(substr(md5(clock_timestamp()::text || p_usuario_id::text || random()::text), 1, 16));
    INSERT INTO reservas(usuario_id, vuelo_id, codigo_reserva, cantidad_asientos, total, estado)
    VALUES(p_usuario_id, p_vuelo_id, v_codigo, v_cantidad, v_total, 'ACTIVA') RETURNING id INTO v_id;
    UPDATE asientos_vuelo av
    SET estado = 'RESERVADO', reserva_id = v_id,
        precio_reservado = CASE WHEN av.clase = 'EJECUTIVA' THEN v_vuelo.precio_ejecutiva ELSE v_vuelo.precio END
    WHERE av.vuelo_id = p_vuelo_id AND av.numero_asiento = ANY(p_asientos);
    UPDATE vuelos v SET asientos_disponibles = v.asientos_disponibles - v_cantidad,
                        version = v.version + 1 WHERE v.id = p_vuelo_id;
    RETURN QUERY SELECT v_id, v_codigo, v_total, 'ACTIVA'::VARCHAR;
END $$;

CREATE OR REPLACE FUNCTION actualizar_reserva_asientos_segura(
    p_usuario_id BIGINT, p_reserva_id BIGINT, p_asientos TEXT[]
)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    v_reserva reservas%ROWTYPE;
    v_vuelo vuelos%ROWTYPE;
    v_solicitados INT := cardinality(p_asientos);
    v_delta INT;
    v_validos INT;
    v_ocupados INT;
    v_actuales TEXT[];
    v_total NUMERIC(10,2);
BEGIN
    IF v_solicitados IS NULL OR v_solicitados = 0 THEN RAISE EXCEPTION 'Debe seleccionar al menos un asiento'; END IF;
    IF (SELECT COUNT(DISTINCT a) FROM unnest(p_asientos) a WHERE btrim(a) <> '') <> v_solicitados THEN
        RAISE EXCEPTION 'No se permiten asientos inválidos o duplicados';
    END IF;
    SELECT * INTO v_reserva FROM reservas WHERE id = p_reserva_id AND usuario_id = p_usuario_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Reserva no encontrada'; END IF;
    IF v_reserva.estado <> 'ACTIVA' THEN RAISE EXCEPTION 'Solo se pueden modificar reservas activas'; END IF;
    IF v_reserva.modificada THEN RAISE EXCEPTION 'Esta reserva ya fue modificada y no admite nuevos cambios'; END IF;
    IF v_solicitados < v_reserva.cantidad_asientos THEN
        RAISE EXCEPTION 'La modificación debe conservar al menos % asientos', v_reserva.cantidad_asientos;
    END IF;
    SELECT * INTO v_vuelo FROM vuelos WHERE id = v_reserva.vuelo_id AND estado = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Vuelo no encontrado o inactivo'; END IF;
    IF v_vuelo.fecha + v_vuelo.hora_salida <= (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil') THEN
        RAISE EXCEPTION 'No se pueden realizar cambios en vuelos finalizados';
    END IF;
    v_delta := v_solicitados - v_reserva.cantidad_asientos;
    IF v_vuelo.asientos_disponibles < v_delta THEN RAISE EXCEPTION 'No existen cupos suficientes para añadir esos asientos'; END IF;
    PERFORM id FROM asientos_vuelo WHERE vuelo_id = v_vuelo.id
    AND (reserva_id = p_reserva_id OR numero_asiento = ANY(p_asientos)) ORDER BY id FOR UPDATE;
    SELECT array_agg(numero_asiento ORDER BY numero_asiento) INTO v_actuales
    FROM asientos_vuelo WHERE reserva_id = p_reserva_id;
    IF v_actuales = (SELECT array_agg(a ORDER BY a) FROM unnest(p_asientos) a) THEN
        RAISE EXCEPTION 'Debe seleccionar asientos diferentes antes de confirmar';
    END IF;
    SELECT COUNT(*), COUNT(*) FILTER (WHERE av.estado <> 'DISPONIBLE' AND av.reserva_id IS DISTINCT FROM p_reserva_id),
           SUM(CASE WHEN av.clase = 'EJECUTIVA' THEN v_vuelo.precio_ejecutiva ELSE v_vuelo.precio END)
    INTO v_validos, v_ocupados, v_total FROM asientos_vuelo av
    WHERE av.vuelo_id = v_vuelo.id AND av.numero_asiento = ANY(p_asientos);
    IF v_validos <> v_solicitados THEN RAISE EXCEPTION 'Uno o más asientos no pertenecen a este vuelo'; END IF;
    IF v_ocupados > 0 THEN RAISE EXCEPTION 'Uno o más asientos ya no están disponibles por otra reserva'; END IF;
    UPDATE asientos_vuelo SET estado = 'DISPONIBLE', reserva_id = NULL, precio_reservado = NULL
        WHERE reserva_id = p_reserva_id;
    UPDATE asientos_vuelo av SET estado = 'RESERVADO', reserva_id = p_reserva_id,
        precio_reservado = CASE WHEN av.clase = 'EJECUTIVA' THEN v_vuelo.precio_ejecutiva ELSE v_vuelo.precio END
        WHERE av.vuelo_id = v_vuelo.id AND av.numero_asiento = ANY(p_asientos);
    UPDATE vuelos SET asientos_disponibles = asientos_disponibles - v_delta, version = version + 1
        WHERE id = v_vuelo.id;
    UPDATE reservas SET cantidad_asientos = v_solicitados, total = v_total, modificada = TRUE WHERE id = p_reserva_id;
END $$;

-- La API anterior por cantidad asigna plazas turista en vuelos con aeronave.
CREATE OR REPLACE FUNCTION crear_reserva_segura(p_usuario_id BIGINT, p_vuelo_id BIGINT, p_cantidad_asientos INTEGER)
RETURNS TABLE(reserva_id BIGINT, codigo_reserva VARCHAR, total NUMERIC, estado VARCHAR)
LANGUAGE plpgsql AS $$
DECLARE
    v_vuelo vuelos%ROWTYPE;
    v_asientos TEXT[];
    v_total NUMERIC(10,2);
    v_id BIGINT;
    v_codigo VARCHAR(50);
BEGIN
    IF p_cantidad_asientos IS NULL OR p_cantidad_asientos <= 0 THEN
        RAISE EXCEPTION 'La cantidad de asientos debe ser mayor a cero';
    END IF;
    SELECT v.* INTO v_vuelo FROM vuelos v WHERE v.id = p_vuelo_id AND v.estado = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Vuelo no encontrado o inactivo'; END IF;
    IF v_vuelo.fecha + v_vuelo.hora_salida <= (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guayaquil') THEN
        RAISE EXCEPTION 'No se pueden realizar reservas para vuelos finalizados';
    END IF;
    IF v_vuelo.asientos_disponibles < p_cantidad_asientos THEN RAISE EXCEPTION 'No existen asientos suficientes disponibles'; END IF;
    IF v_vuelo.avion_id IS NOT NULL OR EXISTS(SELECT 1 FROM asientos_vuelo WHERE vuelo_id = p_vuelo_id) THEN
        SELECT ARRAY(SELECT av.numero_asiento::TEXT FROM asientos_vuelo av
                     WHERE av.vuelo_id = p_vuelo_id AND av.clase = 'TURISTA' AND av.estado = 'DISPONIBLE' AND av.reserva_id IS NULL
                     ORDER BY av.id LIMIT p_cantidad_asientos) INTO v_asientos;
        IF cardinality(v_asientos) <> p_cantidad_asientos THEN RAISE EXCEPTION 'No existen asientos suficientes disponibles en turista'; END IF;
        RETURN QUERY SELECT * FROM crear_reserva_asientos_segura(p_usuario_id, p_vuelo_id, v_asientos);
        RETURN;
    END IF;
    v_total := v_vuelo.precio * p_cantidad_asientos;
    v_codigo := 'FG-' || upper(substr(md5(clock_timestamp()::text || p_usuario_id::text || random()::text), 1, 16));
    INSERT INTO reservas(usuario_id, vuelo_id, codigo_reserva, cantidad_asientos, total, estado)
        VALUES(p_usuario_id, p_vuelo_id, v_codigo, p_cantidad_asientos, v_total, 'ACTIVA') RETURNING id INTO v_id;
    UPDATE vuelos SET asientos_disponibles = asientos_disponibles - p_cantidad_asientos, version = version + 1
        WHERE id = p_vuelo_id;
    RETURN QUERY SELECT v_id, v_codigo, v_total, 'ACTIVA'::VARCHAR;
END $$;
