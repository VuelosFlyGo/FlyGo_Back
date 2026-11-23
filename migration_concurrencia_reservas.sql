-- Reglas de integridad y concurrencia para reservas de asientos.
-- Orden obligatorio de bloqueos: reserva (si existe) -> vuelo -> asientos por id.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'asientos_estado_valido'
    ) THEN
        ALTER TABLE asientos_vuelo
        ADD CONSTRAINT asientos_estado_valido
        CHECK (estado IN ('DISPONIBLE', 'RESERVADO')) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'asientos_reserva_coherente'
    ) THEN
        ALTER TABLE asientos_vuelo
        ADD CONSTRAINT asientos_reserva_coherente
        CHECK (
            (estado = 'DISPONIBLE' AND reserva_id IS NULL)
            OR (estado = 'RESERVADO' AND reserva_id IS NOT NULL)
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION crear_reserva_asientos_segura(
    p_usuario_id BIGINT,
    p_vuelo_id BIGINT,
    p_asientos TEXT[]
)
RETURNS TABLE (
    reserva_id BIGINT,
    codigo_reserva VARCHAR,
    total NUMERIC,
    estado VARCHAR
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_precio NUMERIC(10,2);
    v_cantidad INT;
    v_disponibles INT;
    v_fecha DATE;
    v_hora TIME;
    v_total NUMERIC(10,2);
    v_id BIGINT;
    v_codigo VARCHAR(50);
    v_encontrados INT;
    v_libres INT;
    v_actualizados INT;
BEGIN
    v_cantidad := cardinality(p_asientos);
    IF v_cantidad IS NULL OR v_cantidad = 0 THEN
        RAISE EXCEPTION 'Debe seleccionar al menos un asiento';
    END IF;

    IF EXISTS (SELECT 1 FROM unnest(p_asientos) a WHERE a IS NULL OR btrim(a) = '') THEN
        RAISE EXCEPTION 'La selección contiene un asiento inválido';
    END IF;

    IF (SELECT COUNT(DISTINCT a) FROM unnest(p_asientos) a) <> v_cantidad THEN
        RAISE EXCEPTION 'No se permiten asientos duplicados';
    END IF;

    -- Serializa operaciones del mismo vuelo y mantiene el contador consistente.
    SELECT v.precio, v.asientos_disponibles, v.fecha, v.hora_salida
    INTO v_precio, v_disponibles, v_fecha, v_hora
    FROM vuelos v
    WHERE v.id = p_vuelo_id AND v.estado = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Vuelo no encontrado o inactivo';
    END IF;
    IF (v_fecha + v_hora) < NOW() THEN
        RAISE EXCEPTION 'No se pueden realizar reservas para vuelos finalizados';
    END IF;
    IF v_disponibles < v_cantidad THEN
        RAISE EXCEPTION 'No existen asientos suficientes disponibles';
    END IF;

    -- Todos los procesos toman los asientos en el mismo orden para evitar deadlocks.
    PERFORM av.id
    FROM asientos_vuelo av
    WHERE av.vuelo_id = p_vuelo_id AND av.numero_asiento = ANY(p_asientos)
    ORDER BY av.id
    FOR UPDATE;

    SELECT COUNT(*), COUNT(*) FILTER (
        WHERE av.estado = 'DISPONIBLE' AND av.reserva_id IS NULL
    )
    INTO v_encontrados, v_libres
    FROM asientos_vuelo av
    WHERE av.vuelo_id = p_vuelo_id AND av.numero_asiento = ANY(p_asientos);

    IF v_encontrados <> v_cantidad THEN
        RAISE EXCEPTION 'Uno o más asientos no existen para este vuelo';
    END IF;
    IF v_libres <> v_cantidad THEN
        RAISE EXCEPTION 'Uno o más asientos ya no están disponibles por otra reserva';
    END IF;

    v_total := v_precio * v_cantidad;
    v_codigo := 'FG-' || upper(substr(md5(
        clock_timestamp()::text || p_usuario_id::text || random()::text
    ), 1, 16));

    INSERT INTO reservas (
        usuario_id, vuelo_id, codigo_reserva, cantidad_asientos, total, estado
    ) VALUES (
        p_usuario_id, p_vuelo_id, v_codigo, v_cantidad, v_total, 'ACTIVA'
    ) RETURNING id INTO v_id;

    UPDATE asientos_vuelo av
    SET estado = 'RESERVADO', reserva_id = v_id
    WHERE av.vuelo_id = p_vuelo_id
      AND av.numero_asiento = ANY(p_asientos)
      AND av.estado = 'DISPONIBLE'
      AND av.reserva_id IS NULL;
    GET DIAGNOSTICS v_actualizados = ROW_COUNT;

    IF v_actualizados <> v_cantidad THEN
        RAISE EXCEPTION 'Conflicto de concurrencia: la disponibilidad cambió';
    END IF;

    UPDATE vuelos v
    SET asientos_disponibles = v.asientos_disponibles - v_cantidad,
        version = v.version + 1
    WHERE v.id = p_vuelo_id AND v.asientos_disponibles >= v_cantidad;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Conflicto de concurrencia al actualizar los cupos';
    END IF;

    RETURN QUERY SELECT v_id, v_codigo, v_total, 'ACTIVA'::VARCHAR;
END;
$$;

CREATE OR REPLACE FUNCTION actualizar_reserva_asientos_segura(
    p_usuario_id BIGINT,
    p_reserva_id BIGINT,
    p_asientos TEXT[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_vuelo_id BIGINT;
    v_cantidad INT;
    v_estado VARCHAR(20);
    v_modificada BOOLEAN;
    v_fecha DATE;
    v_hora TIME;
    v_precio NUMERIC(10,2);
    v_disponibles INT;
    v_delta INT;
    v_solicitados INT;
    v_validos INT;
    v_ocupados INT;
    v_actualizados INT;
    v_actuales TEXT[];
BEGIN
    v_solicitados := cardinality(p_asientos);
    IF v_solicitados IS NULL OR v_solicitados = 0 THEN
        RAISE EXCEPTION 'Debe seleccionar al menos un asiento';
    END IF;
    IF (SELECT COUNT(DISTINCT a) FROM unnest(p_asientos) a) <> v_solicitados THEN
        RAISE EXCEPTION 'No se permiten asientos duplicados';
    END IF;

    SELECT vuelo_id, cantidad_asientos, estado, modificada
    INTO v_vuelo_id, v_cantidad, v_estado, v_modificada
    FROM reservas
    WHERE id = p_reserva_id AND usuario_id = p_usuario_id
    FOR UPDATE;

    IF NOT FOUND THEN RAISE EXCEPTION 'Reserva no encontrada'; END IF;
    IF v_estado <> 'ACTIVA' THEN RAISE EXCEPTION 'Solo se pueden modificar reservas activas'; END IF;
    IF v_modificada THEN RAISE EXCEPTION 'Esta reserva ya fue modificada y no admite nuevos cambios'; END IF;
    IF v_solicitados < v_cantidad THEN
        RAISE EXCEPTION 'La modificación debe conservar al menos % asientos', v_cantidad;
    END IF;

    SELECT fecha, hora_salida, precio, asientos_disponibles
    INTO v_fecha, v_hora, v_precio, v_disponibles
    FROM vuelos WHERE id = v_vuelo_id FOR UPDATE;
    IF (v_fecha + v_hora) < NOW() THEN
        RAISE EXCEPTION 'No se pueden realizar cambios en vuelos finalizados';
    END IF;

    v_delta := v_solicitados - v_cantidad;
    IF v_disponibles < v_delta THEN
        RAISE EXCEPTION 'No existen cupos suficientes para añadir esos asientos';
    END IF;

    PERFORM id
    FROM asientos_vuelo
    WHERE vuelo_id = v_vuelo_id
      AND (reserva_id = p_reserva_id OR numero_asiento = ANY(p_asientos))
    ORDER BY id
    FOR UPDATE;

    SELECT array_agg(numero_asiento ORDER BY numero_asiento)
    INTO v_actuales
    FROM asientos_vuelo WHERE reserva_id = p_reserva_id;

    IF v_actuales = (SELECT array_agg(a ORDER BY a) FROM unnest(p_asientos) a) THEN
        RAISE EXCEPTION 'Debe seleccionar asientos diferentes antes de confirmar';
    END IF;

    SELECT COUNT(*), COUNT(*) FILTER (
        WHERE av.estado = 'RESERVADO'
          AND av.reserva_id IS DISTINCT FROM p_reserva_id
    )
    INTO v_validos, v_ocupados
    FROM asientos_vuelo av
    WHERE av.vuelo_id = v_vuelo_id AND av.numero_asiento = ANY(p_asientos);

    IF v_validos <> v_solicitados THEN
        RAISE EXCEPTION 'Uno o más asientos no pertenecen a este vuelo';
    END IF;
    IF v_ocupados > 0 THEN
        RAISE EXCEPTION 'Uno o más asientos ya no están disponibles por otra reserva';
    END IF;

    UPDATE asientos_vuelo
    SET estado = 'DISPONIBLE', reserva_id = NULL
    WHERE reserva_id = p_reserva_id;

    UPDATE asientos_vuelo
    SET estado = 'RESERVADO', reserva_id = p_reserva_id
    WHERE vuelo_id = v_vuelo_id
      AND numero_asiento = ANY(p_asientos)
      AND estado = 'DISPONIBLE'
      AND reserva_id IS NULL;
    GET DIAGNOSTICS v_actualizados = ROW_COUNT;

    IF v_actualizados <> v_solicitados THEN
        RAISE EXCEPTION 'Conflicto de concurrencia: la disponibilidad cambió';
    END IF;

    UPDATE vuelos
    SET asientos_disponibles = asientos_disponibles - v_delta,
        version = version + 1
    WHERE id = v_vuelo_id AND asientos_disponibles >= v_delta;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Conflicto de concurrencia al ampliar la reserva';
    END IF;

    UPDATE reservas
    SET cantidad_asientos = v_solicitados,
        total = v_precio * v_solicitados,
        modificada = TRUE
    WHERE id = p_reserva_id;
END;
$$;
