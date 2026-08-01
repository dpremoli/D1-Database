\restrict dbmate

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: audit_trigger_function(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.audit_trigger_function() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
    v_row_before    JSONB;
    v_row_after     JSONB;
    v_record_id     TEXT;
    v_changed       JSONB;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row_before := to_jsonb(OLD);
        v_row_after  := NULL;
        v_record_id  := COALESCE(
            v_row_before ->> 'sample_id',
            v_row_before ->> 'operation_id',
            v_row_before ->> 'session_id',
            v_row_before ->> 'lot_id',
            v_row_before ->> 'material_id',
            v_row_before ->> 'project_id',
            v_row_before ->> 'tool_box_id',
            v_row_before ->> 'insert_id',
            v_row_before ->> 'edge_id',
            v_row_before ->> 'equipment_id',
            v_row_before ->> 'tool_id',
            v_row_before ->> 'insert_type_id',
            v_row_before ->> 'method_id',
            v_row_before ->> 'parameter_id',
            v_row_before ->> 'symbol',
            v_row_before ->> 'iso_code',
            'unknown'
        );
        v_changed := NULL;
    ELSIF TG_OP = 'INSERT' THEN
        v_row_before := NULL;
        v_row_after  := to_jsonb(NEW);
        v_record_id  := COALESCE(
            v_row_after ->> 'sample_id',
            v_row_after ->> 'operation_id',
            v_row_after ->> 'session_id',
            v_row_after ->> 'lot_id',
            v_row_after ->> 'material_id',
            v_row_after ->> 'project_id',
            v_row_after ->> 'tool_box_id',
            v_row_after ->> 'insert_id',
            v_row_after ->> 'edge_id',
            v_row_after ->> 'equipment_id',
            v_row_after ->> 'tool_id',
            v_row_after ->> 'insert_type_id',
            v_row_after ->> 'method_id',
            v_row_after ->> 'parameter_id',
            v_row_after ->> 'symbol',
            v_row_after ->> 'iso_code',
            'unknown'
        );
        v_changed := NULL;
    ELSE
        -- UPDATE
        v_row_before := to_jsonb(OLD);
        v_row_after  := to_jsonb(NEW);
        v_record_id  := COALESCE(
            v_row_after ->> 'sample_id',
            v_row_after ->> 'operation_id',
            v_row_after ->> 'session_id',
            v_row_after ->> 'lot_id',
            v_row_after ->> 'material_id',
            v_row_after ->> 'project_id',
            v_row_after ->> 'tool_box_id',
            v_row_after ->> 'insert_id',
            v_row_after ->> 'edge_id',
            v_row_after ->> 'equipment_id',
            v_row_after ->> 'tool_id',
            v_row_after ->> 'insert_type_id',
            v_row_after ->> 'method_id',
            v_row_after ->> 'parameter_id',
            v_row_after ->> 'symbol',
            v_row_after ->> 'iso_code',
            'unknown'
        );
        SELECT jsonb_object_agg(
            k,
            jsonb_build_object('old', v_row_before -> k, 'new', v_row_after -> k)
        )
        INTO v_changed
        FROM jsonb_each(v_row_after) AS t (k, v)
        WHERE (v_row_before -> k) IS DISTINCT FROM (v_row_after -> k);
    END IF;

    INSERT INTO audit_logs (
        table_name,
        record_id,
        action_type,
        actor_identity,
        row_before,
        row_after,
        changed_fields
    ) VALUES (
        TG_TABLE_NAME,
        v_record_id,
        TG_OP,
        current_setting('d1.actor_identity', TRUE),
        v_row_before,
        v_row_after,
        v_changed
    );

    RETURN NEW;
END;
$$;


--
-- Name: f_sample_timeline(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.f_sample_timeline(p_sample_id uuid) RETURNS TABLE(event_date timestamp with time zone, event_type text, event_id uuid, label text, detail jsonb)
    LANGUAGE sql STABLE
    AS $$
    SELECT
        mo.operation_date            AS event_date,
        'manufacturing_operation'    AS event_type,
        mo.operation_id              AS event_id,
        mo.pass_code::TEXT           AS label,
        jsonb_build_object(
            'method_id', mo.method_id,
            'sequence', mo.operation_sequence,
            'operator', mo.operator_name
        )                            AS detail
    FROM manufacturing_operations AS mo
    WHERE mo.sample_id = p_sample_id

    UNION ALL

    SELECT
        ts.session_date,
        'test_session',
        ts.session_id,
        ts.test_type,
        jsonb_build_object(
            'status', ts.status,
            'file_storage_pointer', ts.file_storage_pointer
        )
    FROM test_sessions AS ts
    WHERE ts.sample_id = p_sample_id

    ORDER BY event_date ASC NULLS LAST;
$$;


--
-- Name: FUNCTION f_sample_timeline(p_sample_id uuid); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.f_sample_timeline(p_sample_id uuid) IS 'Chronological cradle-to-grave event stream (manufacturing operations + test sessions) for a single sample, ordered by date.';


--
-- Name: f_trace_ancestors(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.f_trace_ancestors(p_sample_id uuid) RETURNS TABLE(depth integer, sample_id uuid, sample_code text, form text, relationship_type text, fraction numeric, path uuid[])
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE up AS (
        SELECT
            0                       AS depth,
            ps.sample_id,
            ps.sample_code::TEXT    AS sample_code,
            ps.form,
            NULL::TEXT              AS relationship_type,
            NULL::NUMERIC           AS fraction,
            ARRAY[ps.sample_id]     AS path
        FROM physical_samples AS ps
        WHERE ps.sample_id = p_sample_id

        UNION ALL

        SELECT
            up.depth + 1,
            parent.sample_id,
            parent.sample_code::TEXT,
            parent.form,
            sg.relationship_type,
            sg.fraction,
            up.path || parent.sample_id
        FROM up
        INNER JOIN sample_genealogy AS sg ON sg.child_sample_id = up.sample_id
        INNER JOIN physical_samples AS parent
            ON parent.sample_id = sg.parent_sample_id
        WHERE NOT (parent.sample_id = ANY (up.path))
    )
    SELECT depth, sample_id, sample_code, form, relationship_type, fraction, path
    FROM up;
$$;


--
-- Name: FUNCTION f_trace_ancestors(p_sample_id uuid); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.f_trace_ancestors(p_sample_id uuid) IS 'Reverse traceability: every ancestor of a sample (depth 0 = the sample itself), walking child→parent through sample_genealogy. Cycle-guarded.';


--
-- Name: f_trace_descendants(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.f_trace_descendants(p_sample_id uuid) RETURNS TABLE(depth integer, sample_id uuid, sample_code text, form text, relationship_type text, fraction numeric, path uuid[])
    LANGUAGE sql STABLE
    AS $$
    WITH RECURSIVE down AS (
        SELECT
            0                       AS depth,
            ps.sample_id,
            ps.sample_code::TEXT    AS sample_code,
            ps.form,
            NULL::TEXT              AS relationship_type,
            NULL::NUMERIC           AS fraction,
            ARRAY[ps.sample_id]     AS path
        FROM physical_samples AS ps
        WHERE ps.sample_id = p_sample_id

        UNION ALL

        SELECT
            down.depth + 1,
            child.sample_id,
            child.sample_code::TEXT,
            child.form,
            sg.relationship_type,
            sg.fraction,
            down.path || child.sample_id
        FROM down
        INNER JOIN sample_genealogy AS sg ON sg.parent_sample_id = down.sample_id
        INNER JOIN physical_samples AS child
            ON child.sample_id = sg.child_sample_id
        WHERE NOT (child.sample_id = ANY (down.path))
    )
    SELECT depth, sample_id, sample_code, form, relationship_type, fraction, path
    FROM down;
$$;


--
-- Name: FUNCTION f_trace_descendants(p_sample_id uuid); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.f_trace_descendants(p_sample_id uuid) IS 'Forward traceability: every descendant of a sample (depth 0 = the sample itself), walking parent→child through sample_genealogy. Cycle-guarded.';


--
-- Name: f_trace_stock_origins(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.f_trace_stock_origins(p_sample_id uuid) RETURNS TABLE(via_sample_id uuid, via_sample_code text, depth integer, lot_id uuid, lot_code text, stock_type text, supplier_name text, mass_used_grams numeric)
    LANGUAGE sql STABLE
    AS $$
    SELECT
        a.sample_id          AS via_sample_id,
        a.sample_code        AS via_sample_code,
        a.depth,
        rsl.lot_id,
        rsl.lot_code::TEXT   AS lot_code,
        rsl.stock_type,
        rsl.supplier_name,
        ssp.mass_used_grams
    FROM f_trace_ancestors(p_sample_id) AS a
    INNER JOIN sample_stock_provenance AS ssp ON ssp.sample_id = a.sample_id
    INNER JOIN raw_stock_lots AS rsl ON rsl.lot_id = ssp.lot_id;
$$;


--
-- Name: FUNCTION f_trace_stock_origins(p_sample_id uuid); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.f_trace_stock_origins(p_sample_id uuid) IS 'Full reverse traceability to raw material: every raw_stock_lot feeding a sample or any of its ancestors, with the ancestor it entered through.';


--
-- Name: generate_force_file_id(text, numeric, numeric, numeric); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.generate_force_file_id(p_pass_code text, p_cutting_speed_m_per_min numeric, p_feed_mm_per_rev numeric, p_depth_of_cut_mm numeric) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT
    AS $$
    SELECT
        p_pass_code
        || '-' || p_cutting_speed_m_per_min::TEXT || 'MPM'
        || '_' || p_feed_mm_per_rev::TEXT || 'feed'
        || '_' || p_depth_of_cut_mm::TEXT || 'DoC'
$$;


--
-- Name: FUNCTION generate_force_file_id(p_pass_code text, p_cutting_speed_m_per_min numeric, p_feed_mm_per_rev numeric, p_depth_of_cut_mm numeric); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.generate_force_file_id(p_pass_code text, p_cutting_speed_m_per_min numeric, p_feed_mm_per_rev numeric, p_depth_of_cut_mm numeric) IS 'Generates the force-file human-readable ID from pass parameters. Pattern: {pass_code}-{Vc}MPM_{feed}feed_{DoC}DoC. The MinIO object key is built from this ID; it is regenerable from the operation row.';


--
-- Name: generate_pass_code(text, text, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.generate_pass_code(p_sample_code text, p_pass_type text, p_pass_number integer) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT
    AS $$
    SELECT p_sample_code || '-' || p_pass_type || p_pass_number::TEXT
$$;


--
-- Name: FUNCTION generate_pass_code(p_sample_code text, p_pass_type text, p_pass_number integer); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.generate_pass_code(p_sample_code text, p_pass_type text, p_pass_number integer) IS 'Generates the machining-pass pseudonym. Pattern: {sample_code}-{pass_type}{n}. Pass types: F=facing, R=roughing. E.g. generate_pass_code(''9-AA-MR-2023-03-23'', ''F'', 9) → 9-AA-MR-2023-03-23-F9.';


--
-- Name: generate_sample_code(integer, text, text, date); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.generate_sample_code(p_sequence integer, p_alloy_code text, p_method_code text, p_manufactured_date date) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT
    AS $$
    SELECT
        p_sequence::TEXT
        || '-' || p_alloy_code
        || '-' || p_method_code
        || '-' || TO_CHAR(p_manufactured_date, 'YYYY-MM-DD')
$$;


--
-- Name: FUNCTION generate_sample_code(p_sequence integer, p_alloy_code text, p_method_code text, p_manufactured_date date); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.generate_sample_code(p_sequence integer, p_alloy_code text, p_method_code text, p_manufactured_date date) IS 'Generates the human-readable sample pseudonym. Pattern: {seq}-{alloy_code}-{method_code}-{YYYY-MM-DD}. E.g. generate_sample_code(10, ''AA'', ''MF'', ''2023-06-03'') → 10-AA-MF-2023-06-03.';


--
-- Name: occ_update_trigger_function(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.occ_update_trigger_function() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.version    := OLD.version + 1;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alloying_elements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alloying_elements (
    symbol character varying(4) NOT NULL,
    element_name text NOT NULL,
    atomic_number integer NOT NULL,
    atomic_weight numeric(10,4),
    density_g_per_cm3 numeric(10,4),
    melting_point_k numeric(10,2),
    boiling_point_k numeric(10,2),
    electronegativity numeric(6,3),
    atomic_radius_pm numeric(8,2)
);


--
-- Name: TABLE alloying_elements; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.alloying_elements IS 'Periodic-table reference for elements used in alloy compositions.';


--
-- Name: COLUMN alloying_elements.symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.symbol IS 'Chemical symbol, e.g. Ti, Al, V. Primary key.';


--
-- Name: COLUMN alloying_elements.element_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.element_name IS 'Full element name, e.g. Titanium.';


--
-- Name: COLUMN alloying_elements.atomic_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.atomic_number IS 'Atomic number (Z). Unique.';


--
-- Name: COLUMN alloying_elements.atomic_weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.atomic_weight IS 'Standard atomic weight (g/mol).';


--
-- Name: COLUMN alloying_elements.density_g_per_cm3; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.density_g_per_cm3 IS 'Elemental density at STP (g/cm³).';


--
-- Name: COLUMN alloying_elements.melting_point_k; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.melting_point_k IS 'Melting point in Kelvin.';


--
-- Name: COLUMN alloying_elements.boiling_point_k; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.boiling_point_k IS 'Boiling point in Kelvin.';


--
-- Name: COLUMN alloying_elements.electronegativity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.electronegativity IS 'Pauling electronegativity.';


--
-- Name: COLUMN alloying_elements.atomic_radius_pm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.alloying_elements.atomic_radius_pm IS 'Atomic radius in picometres.';


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    log_id bigint NOT NULL,
    event_timestamp timestamp with time zone DEFAULT now() NOT NULL,
    table_name text NOT NULL,
    record_id text NOT NULL,
    action_type text NOT NULL,
    actor_identity text,
    row_before jsonb,
    row_after jsonb,
    changed_fields jsonb,
    CONSTRAINT audit_logs_action_type_check CHECK ((action_type = ANY (ARRAY['INSERT'::text, 'UPDATE'::text, 'DELETE'::text])))
);


--
-- Name: TABLE audit_logs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.audit_logs IS 'Append-only immutable audit trail. Every INSERT/UPDATE/DELETE on a core table produces one row here via the audit_trigger_function trigger.';


--
-- Name: COLUMN audit_logs.record_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_logs.record_id IS 'Primary-key value of the affected row, cast to TEXT for portability.';


--
-- Name: COLUMN audit_logs.actor_identity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_logs.actor_identity IS 'User ID or machine-token identity, set via SET LOCAL d1.actor_identity.';


--
-- Name: COLUMN audit_logs.row_before; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_logs.row_before IS 'Full row state before the mutation (NULL for INSERT).';


--
-- Name: COLUMN audit_logs.row_after; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_logs.row_after IS 'Full row state after the mutation (NULL for DELETE).';


--
-- Name: COLUMN audit_logs.changed_fields; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_logs.changed_fields IS 'For UPDATE: JSONB object keyed by column with {old, new} sub-objects.';


--
-- Name: audit_logs_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_log_id_seq OWNED BY public.audit_logs.log_id;


--
-- Name: cutting_inserts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cutting_inserts (
    insert_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    insert_code character varying(64) NOT NULL,
    tool_box_id uuid NOT NULL,
    insert_type_id uuid,
    insert_number integer,
    is_depleted boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    location text,
    owner text
);


--
-- Name: TABLE cutting_inserts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cutting_inserts IS 'Parent level of the tooling hierarchy. One physical insert with N edges. insert_code is the human-readable pseudonym (e.g. H13A-#2).';


--
-- Name: COLUMN cutting_inserts.insert_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cutting_inserts.insert_code IS 'Human-readable code: type-insert# (e.g. H13A-#2). Unique. Never the PK.';


--
-- Name: COLUMN cutting_inserts.insert_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cutting_inserts.insert_number IS 'Sequential number of this insert within its tool_box.';


--
-- Name: COLUMN cutting_inserts.is_depleted; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cutting_inserts.is_depleted IS 'TRUE when all edges of this insert have been consumed.';


--
-- Name: COLUMN cutting_inserts.location; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cutting_inserts.location IS 'Physical storage location of this insert.';


--
-- Name: COLUMN cutting_inserts.owner; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cutting_inserts.owner IS 'Owner / responsible person for this insert.';


--
-- Name: directus_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_access (
    id uuid NOT NULL,
    role uuid,
    "user" uuid,
    policy uuid NOT NULL,
    sort integer
);


--
-- Name: directus_activity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_activity (
    id integer NOT NULL,
    action character varying(45) NOT NULL,
    "user" uuid,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip character varying(50),
    user_agent text,
    collection character varying(64) NOT NULL,
    item character varying(255) NOT NULL,
    origin character varying(255)
);


--
-- Name: directus_activity_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_activity_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_activity_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_activity_id_seq OWNED BY public.directus_activity.id;


--
-- Name: directus_collections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_collections (
    collection character varying(64) NOT NULL,
    icon character varying(64),
    note text,
    display_template character varying(255),
    hidden boolean DEFAULT false NOT NULL,
    singleton boolean DEFAULT false NOT NULL,
    translations json,
    archive_field character varying(64),
    archive_app_filter boolean DEFAULT true NOT NULL,
    archive_value character varying(255),
    unarchive_value character varying(255),
    sort_field character varying(64),
    accountability character varying(255) DEFAULT 'all'::character varying,
    color character varying(255),
    item_duplication_fields json,
    sort integer,
    "group" character varying(64),
    collapse character varying(255) DEFAULT 'open'::character varying NOT NULL,
    preview_url character varying(255),
    versioning boolean DEFAULT false NOT NULL
);


--
-- Name: directus_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_comments (
    id uuid NOT NULL,
    collection character varying(64) NOT NULL,
    item character varying(255) NOT NULL,
    comment text NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid,
    user_updated uuid
);


--
-- Name: directus_dashboards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_dashboards (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    icon character varying(64) DEFAULT 'dashboard'::character varying NOT NULL,
    note text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid,
    color character varying(255)
);


--
-- Name: directus_deployment_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_deployment_projects (
    id uuid NOT NULL,
    deployment uuid NOT NULL,
    external_id character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid,
    url character varying(255),
    framework character varying(255),
    deployable boolean DEFAULT true NOT NULL
);


--
-- Name: directus_deployment_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_deployment_runs (
    id uuid NOT NULL,
    project uuid NOT NULL,
    external_id character varying(255) NOT NULL,
    target character varying(255) NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid,
    status character varying(255),
    url character varying(255),
    started_at timestamp with time zone,
    completed_at timestamp with time zone
);


--
-- Name: directus_deployments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_deployments (
    id uuid NOT NULL,
    provider character varying(255) NOT NULL,
    credentials text,
    options text,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid,
    webhook_ids json,
    webhook_secret character varying(255),
    last_synced_at timestamp with time zone
);


--
-- Name: directus_extensions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_extensions (
    enabled boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    folder character varying(255) NOT NULL,
    source character varying(255) NOT NULL,
    bundle uuid
);


--
-- Name: directus_fields; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_fields (
    id integer NOT NULL,
    collection character varying(64) NOT NULL,
    field character varying(64) NOT NULL,
    special character varying(64),
    interface character varying(64),
    options json,
    display character varying(64),
    display_options json,
    readonly boolean DEFAULT false NOT NULL,
    hidden boolean DEFAULT false NOT NULL,
    sort integer,
    width character varying(30) DEFAULT 'full'::character varying,
    translations json,
    note text,
    conditions json,
    required boolean DEFAULT false,
    "group" character varying(64),
    validation json,
    validation_message text,
    searchable boolean DEFAULT true NOT NULL
);


--
-- Name: directus_fields_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_fields_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_fields_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_fields_id_seq OWNED BY public.directus_fields.id;


--
-- Name: directus_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_files (
    id uuid NOT NULL,
    storage character varying(255) NOT NULL,
    filename_disk character varying(255),
    filename_download character varying(255) NOT NULL,
    title character varying(255),
    type character varying(255),
    folder uuid,
    uploaded_by uuid,
    created_on timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    modified_by uuid,
    modified_on timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    charset character varying(50),
    filesize bigint,
    width integer,
    height integer,
    duration integer,
    embed character varying(200),
    description text,
    location text,
    tags text,
    metadata json,
    focal_point_x integer,
    focal_point_y integer,
    tus_id character varying(64),
    tus_data json,
    uploaded_on timestamp with time zone
);


--
-- Name: directus_flows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_flows (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    icon character varying(64),
    color character varying(255),
    description text,
    status character varying(255) DEFAULT 'active'::character varying NOT NULL,
    trigger character varying(255),
    accountability character varying(255) DEFAULT 'all'::character varying,
    options json,
    operation uuid,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid
);


--
-- Name: directus_folders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_folders (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    parent uuid
);


--
-- Name: directus_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_migrations (
    version character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: directus_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_notifications (
    id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    status character varying(255) DEFAULT 'inbox'::character varying,
    recipient uuid NOT NULL,
    sender uuid,
    subject character varying(255) NOT NULL,
    message text,
    collection character varying(64),
    item character varying(255)
);


--
-- Name: directus_notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_notifications_id_seq OWNED BY public.directus_notifications.id;


--
-- Name: directus_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_operations (
    id uuid NOT NULL,
    name character varying(255),
    key character varying(255) NOT NULL,
    type character varying(255) NOT NULL,
    position_x integer NOT NULL,
    position_y integer NOT NULL,
    options json,
    resolve uuid,
    reject uuid,
    flow uuid NOT NULL,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid
);


--
-- Name: directus_panels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_panels (
    id uuid NOT NULL,
    dashboard uuid NOT NULL,
    name character varying(255),
    icon character varying(64) DEFAULT NULL::character varying,
    color character varying(10),
    show_header boolean DEFAULT false NOT NULL,
    note text,
    type character varying(255) NOT NULL,
    position_x integer NOT NULL,
    position_y integer NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    options json,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid
);


--
-- Name: directus_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_permissions (
    id integer NOT NULL,
    collection character varying(64) NOT NULL,
    action character varying(10) NOT NULL,
    permissions json,
    validation json,
    presets json,
    fields text,
    policy uuid NOT NULL
);


--
-- Name: directus_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_permissions_id_seq OWNED BY public.directus_permissions.id;


--
-- Name: directus_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_policies (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    icon character varying(64) DEFAULT 'badge'::character varying NOT NULL,
    description text,
    ip_access text,
    enforce_tfa boolean DEFAULT false NOT NULL,
    admin_access boolean DEFAULT false NOT NULL,
    app_access boolean DEFAULT false NOT NULL
);


--
-- Name: directus_presets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_presets (
    id integer NOT NULL,
    bookmark character varying(255),
    "user" uuid,
    role uuid,
    collection character varying(64),
    search character varying(100),
    layout character varying(100) DEFAULT 'tabular'::character varying,
    layout_query json,
    layout_options json,
    refresh_interval integer,
    filter json,
    icon character varying(64) DEFAULT 'bookmark'::character varying,
    color character varying(255)
);


--
-- Name: directus_presets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_presets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_presets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_presets_id_seq OWNED BY public.directus_presets.id;


--
-- Name: directus_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_relations (
    id integer NOT NULL,
    many_collection character varying(64) NOT NULL,
    many_field character varying(64) NOT NULL,
    one_collection character varying(64),
    one_field character varying(64),
    one_collection_field character varying(64),
    one_allowed_collections text,
    junction_field character varying(64),
    sort_field character varying(64),
    one_deselect_action character varying(255) DEFAULT 'nullify'::character varying NOT NULL
);


--
-- Name: directus_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_relations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_relations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_relations_id_seq OWNED BY public.directus_relations.id;


--
-- Name: directus_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_revisions (
    id integer NOT NULL,
    activity integer NOT NULL,
    collection character varying(64) NOT NULL,
    item character varying(255) NOT NULL,
    data json,
    delta json,
    parent integer,
    version uuid
);


--
-- Name: directus_revisions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_revisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_revisions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_revisions_id_seq OWNED BY public.directus_revisions.id;


--
-- Name: directus_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_roles (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    icon character varying(64) DEFAULT 'supervised_user_circle'::character varying NOT NULL,
    description text,
    parent uuid
);


--
-- Name: directus_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_sessions (
    token character varying(64) NOT NULL,
    "user" uuid,
    expires timestamp with time zone NOT NULL,
    ip character varying(255),
    user_agent text,
    share uuid,
    origin character varying(255),
    next_token character varying(64)
);


--
-- Name: directus_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_settings (
    id integer NOT NULL,
    project_name character varying(100) DEFAULT 'Directus'::character varying NOT NULL,
    project_url character varying(255),
    project_color character varying(255) DEFAULT '#6644FF'::character varying NOT NULL,
    project_logo uuid,
    public_foreground uuid,
    public_background uuid,
    public_note text,
    auth_login_attempts integer DEFAULT 25,
    auth_password_policy character varying(100),
    storage_asset_transform character varying(7) DEFAULT 'all'::character varying,
    storage_asset_presets json,
    custom_css text,
    storage_default_folder uuid,
    basemaps json,
    mapbox_key character varying(255),
    module_bar json,
    project_descriptor character varying(100),
    default_language character varying(255) DEFAULT 'en-US'::character varying NOT NULL,
    custom_aspect_ratios json,
    public_favicon uuid,
    default_appearance character varying(255) DEFAULT 'auto'::character varying NOT NULL,
    default_theme_light character varying(255),
    theme_light_overrides json,
    default_theme_dark character varying(255),
    theme_dark_overrides json,
    report_error_url character varying(255),
    report_bug_url character varying(255),
    report_feature_url character varying(255),
    public_registration boolean DEFAULT false NOT NULL,
    public_registration_verify_email boolean DEFAULT true NOT NULL,
    public_registration_role uuid,
    public_registration_email_filter json,
    visual_editor_urls json,
    project_id uuid,
    mcp_enabled boolean DEFAULT false NOT NULL,
    mcp_allow_deletes boolean DEFAULT false NOT NULL,
    mcp_prompts_collection character varying(255) DEFAULT NULL::character varying,
    mcp_system_prompt_enabled boolean DEFAULT true NOT NULL,
    mcp_system_prompt text,
    project_owner character varying(255),
    project_usage character varying(255),
    org_name character varying(255),
    product_updates boolean,
    project_status character varying(255),
    ai_openai_api_key text,
    ai_anthropic_api_key text,
    ai_system_prompt text,
    ai_google_api_key text,
    ai_openai_compatible_api_key text,
    ai_openai_compatible_base_url text,
    ai_openai_compatible_name text,
    ai_openai_compatible_models json,
    ai_openai_compatible_headers json,
    ai_openai_allowed_models json,
    ai_anthropic_allowed_models json,
    ai_google_allowed_models json,
    collaborative_editing_enabled boolean DEFAULT false NOT NULL
);


--
-- Name: directus_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.directus_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: directus_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.directus_settings_id_seq OWNED BY public.directus_settings.id;


--
-- Name: directus_shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_shares (
    id uuid NOT NULL,
    name character varying(255),
    collection character varying(64) NOT NULL,
    item character varying(255) NOT NULL,
    role uuid,
    password character varying(255),
    user_created uuid,
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    date_start timestamp with time zone,
    date_end timestamp with time zone,
    times_used integer DEFAULT 0,
    max_uses integer
);


--
-- Name: directus_translations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_translations (
    id uuid NOT NULL,
    language character varying(255) NOT NULL,
    key character varying(255) NOT NULL,
    value text NOT NULL
);


--
-- Name: directus_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_users (
    id uuid NOT NULL,
    first_name character varying(50),
    last_name character varying(50),
    email character varying(128),
    password character varying(255),
    location character varying(255),
    title character varying(50),
    description text,
    tags json,
    avatar uuid,
    language character varying(255) DEFAULT NULL::character varying,
    tfa_secret character varying(255),
    status character varying(16) DEFAULT 'active'::character varying NOT NULL,
    role uuid,
    token character varying(255),
    last_access timestamp with time zone,
    last_page character varying(255),
    provider character varying(128) DEFAULT 'default'::character varying NOT NULL,
    external_identifier character varying(255),
    auth_data json,
    email_notifications boolean DEFAULT true,
    appearance character varying(255),
    theme_dark character varying(255),
    theme_light character varying(255),
    theme_light_overrides json,
    theme_dark_overrides json,
    text_direction character varying(255) DEFAULT 'auto'::character varying NOT NULL
);


--
-- Name: directus_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directus_versions (
    id uuid NOT NULL,
    key character varying(64) NOT NULL,
    name character varying(255),
    collection character varying(64) NOT NULL,
    item character varying(255) NOT NULL,
    hash character varying(255),
    date_created timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    date_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_created uuid,
    user_updated uuid,
    delta json
);


--
-- Name: equipment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment (
    equipment_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    equipment_code character varying(64) NOT NULL,
    equipment_name text NOT NULL,
    equipment_type text NOT NULL,
    location text,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    manufacturer text
);


--
-- Name: TABLE equipment; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.equipment IS 'Physical machines and rigs used in manufacturing and testing.';


--
-- Name: COLUMN equipment.equipment_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.equipment.equipment_code IS 'Short identifier, e.g. NLX-2500. Unique.';


--
-- Name: COLUMN equipment.equipment_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.equipment.equipment_type IS 'Category, e.g. CNC_Lathe, FAST_Press, SEM, Hardness_Tester.';


--
-- Name: COLUMN equipment.manufacturer; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.equipment.manufacturer IS 'Machine/equipment manufacturer name.';


--
-- Name: insert_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insert_edges (
    edge_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    edge_code character varying(64) NOT NULL,
    insert_id uuid NOT NULL,
    edge_identifier character varying(16) NOT NULL,
    is_used boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL
);


--
-- Name: TABLE insert_edges; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.insert_edges IS 'Child level of the tooling hierarchy. Each physical cutting point on an insert. edge_code is the human-readable pseudonym (e.g. H13A-#2-fC).';


--
-- Name: COLUMN insert_edges.edge_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_edges.edge_code IS 'Human-readable code: type-insert#-edge (e.g. H13A-#2-fC). Unique.';


--
-- Name: COLUMN insert_edges.edge_identifier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_edges.edge_identifier IS 'Single edge label within the insert, e.g. A, B, fC, fA. Not globally unique.';


--
-- Name: COLUMN insert_edges.is_used; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_edges.is_used IS 'TRUE once this edge has been consumed by a machining pass.';


--
-- Name: insert_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insert_types (
    insert_type_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    type_code character varying(64) NOT NULL,
    manufacturer text,
    iso_designation text,
    substrate text,
    coating text,
    geometry_notes text,
    datasheet_url text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    op_type text,
    mounting_style_code text,
    inserts_per_box integer,
    edge_count integer,
    nose_radius_mm numeric(8,3),
    cutting_edge_length_mm numeric(8,3),
    included_angle_deg numeric(8,3),
    fixing_hole_diameter_mm numeric(8,3),
    material_class text
);


--
-- Name: TABLE insert_types; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.insert_types IS 'Cutting-insert catalogue: grades, coatings, geometries (e.g. Sandvik CNMG).';


--
-- Name: COLUMN insert_types.type_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.type_code IS 'Manufacturer part or grade code. Unique.';


--
-- Name: COLUMN insert_types.substrate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.substrate IS 'Insert material: carbide, PCBN, PCD, ceramic, etc.';


--
-- Name: COLUMN insert_types.op_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.op_type IS 'Primary operation type, e.g. Roughing, Finishing, Semi-Finishing.';


--
-- Name: COLUMN insert_types.mounting_style_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.mounting_style_code IS 'Insert fixing/clamping style code (IFS), e.g. P, M, S.';


--
-- Name: COLUMN insert_types.inserts_per_box; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.inserts_per_box IS 'Standard box quantity from manufacturer.';


--
-- Name: COLUMN insert_types.edge_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.edge_count IS 'Number of usable cutting edges per insert.';


--
-- Name: COLUMN insert_types.nose_radius_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.nose_radius_mm IS 'Corner/nose radius RE in millimetres.';


--
-- Name: COLUMN insert_types.cutting_edge_length_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.cutting_edge_length_mm IS 'Cutting edge length L in millimetres.';


--
-- Name: COLUMN insert_types.included_angle_deg; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.included_angle_deg IS 'Included/relief angle ESPR in degrees.';


--
-- Name: COLUMN insert_types.fixing_hole_diameter_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.fixing_hole_diameter_mm IS 'Fixing hole diameter in millimetres, if applicable.';


--
-- Name: COLUMN insert_types.material_class; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.insert_types.material_class IS 'ISO 513 TMC1 material classification code, e.g. P, M, K, S.';


--
-- Name: manufacturing_methods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.manufacturing_methods (
    method_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    method_code character varying(8) NOT NULL,
    method_name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL
);


--
-- Name: TABLE manufacturing_methods; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.manufacturing_methods IS 'Catalogue of physical-transformation process types, e.g. FAST/SPS, Turning.';


--
-- Name: COLUMN manufacturing_methods.method_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_methods.method_code IS 'Short code used in sample_code generation, e.g. MF=FAST, MO=Forged, MR=Rolled.';


--
-- Name: manufacturing_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.manufacturing_operations (
    operation_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    sample_id uuid NOT NULL,
    method_id uuid NOT NULL,
    project_id uuid,
    equipment_id uuid,
    tool_id uuid,
    insert_edge_id uuid,
    operator_name text,
    operation_sequence integer,
    pass_code character varying(128),
    operation_date timestamp with time zone,
    recorded_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    capture_software text,
    capture_frequency_khz numeric(10,4),
    file_storage_pointer text,
    force_file_id text,
    nc_program_text text,
    nc_program_file_uri text,
    outcome_notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL
);


--
-- Name: TABLE manufacturing_operations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.manufacturing_operations IS 'Unified operation log for all manufacturing steps on a sample. Replaces separate FAST Runs and Machining Operations sheets. Method-specific fields are stored in recorded_metadata JSONB.';


--
-- Name: COLUMN manufacturing_operations.sample_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.sample_id IS 'The sample this operation was performed on. FK to physical_samples.';


--
-- Name: COLUMN manufacturing_operations.method_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.method_id IS 'The manufacturing method used, e.g. FAST, Turning. FK to manufacturing_methods.';


--
-- Name: COLUMN manufacturing_operations.operation_sequence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.operation_sequence IS 'Ordering of this operation within the sample lifecycle (1 = first).';


--
-- Name: COLUMN manufacturing_operations.pass_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.pass_code IS 'Human-readable pass identifier, e.g. 9-AA-MR-2023-03-23-F9. Generated by generate_pass_code(). Not the PK.';


--
-- Name: COLUMN manufacturing_operations.recorded_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.recorded_metadata IS 'JSONB bag of method-specific parameters. Keys are defined in method_parameters. E.g. {"peak_temperature_celsius": 1100, "atmosphere": "Argon"} for FAST.';


--
-- Name: COLUMN manufacturing_operations.capture_software; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.capture_software IS 'Data-capture app and version, e.g. MATLAB ABFP 0.18. Needed to parse force files.';


--
-- Name: COLUMN manufacturing_operations.capture_frequency_khz; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.capture_frequency_khz IS 'Sampling frequency in kilohertz, e.g. 25.6. Needed to interpret force files.';


--
-- Name: COLUMN manufacturing_operations.file_storage_pointer; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.file_storage_pointer IS 'MinIO URI of the raw data file for this operation, if one was captured.';


--
-- Name: COLUMN manufacturing_operations.force_file_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.force_file_id IS 'Human-readable force-file ID (e.g. 9-AA-MR-2023-03-23-F9-20MPM_0.05feed_0.1DoC). Generated by generate_force_file_id(). Maps to the MinIO object key.';


--
-- Name: COLUMN manufacturing_operations.nc_program_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.nc_program_text IS 'Inline NC/G-code program text for machining passes.';


--
-- Name: COLUMN manufacturing_operations.nc_program_file_uri; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.manufacturing_operations.nc_program_file_uri IS 'MinIO URI for the G-code file if stored as an artifact.';


--
-- Name: material_alloying_elements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.material_alloying_elements (
    material_id uuid NOT NULL,
    symbol character varying(4) NOT NULL
);


--
-- Name: TABLE material_alloying_elements; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.material_alloying_elements IS 'M2M: elemental composition of each alloy (mirrors AppSheet Alloy Codes.Alloying Elements EnumList).';


--
-- Name: material_iso_classifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.material_iso_classifications (
    iso_code character varying(4) NOT NULL,
    description text NOT NULL,
    colour_hex character varying(7)
);


--
-- Name: TABLE material_iso_classifications; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.material_iso_classifications IS 'ISO 513 material-group codes (P, M, K, N, S, H) for cutting-tool selection.';


--
-- Name: COLUMN material_iso_classifications.iso_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.material_iso_classifications.iso_code IS 'Single-letter ISO group code, e.g. P, M, K, N, S, H.';


--
-- Name: COLUMN material_iso_classifications.colour_hex; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.material_iso_classifications.colour_hex IS 'ISO-assigned colour for the group, e.g. #0066CC for P (blue).';


--
-- Name: materials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.materials (
    material_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    alloy_code character varying(32) NOT NULL,
    common_name text NOT NULL,
    iso_code character varying(4),
    density_g_per_cm3 numeric(8,4),
    export_controlled boolean DEFAULT false NOT NULL,
    datasheet_url text,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE materials; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.materials IS 'Alloy/material catalogue. alloy_code (e.g. AA = Ti-6Al-4V) is the human-readable key used in sample codes.';


--
-- Name: COLUMN materials.alloy_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.materials.alloy_code IS 'Short code used in sample_code generation, e.g. AA for Ti-6Al-4V.';


--
-- Name: COLUMN materials.common_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.materials.common_name IS 'Human-readable material name, e.g. Ti-6Al-4V Grade 5.';


--
-- Name: COLUMN materials.density_g_per_cm3; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.materials.density_g_per_cm3 IS 'Theoretical density in grams per cubic centimetre.';


--
-- Name: COLUMN materials.export_controlled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.materials.export_controlled IS 'TRUE if subject to ITAR/ECJU export controls. Drives RBAC visibility.';


--
-- Name: method_parameters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.method_parameters (
    parameter_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    method_id uuid NOT NULL,
    parameter_name text NOT NULL,
    display_name text NOT NULL,
    data_type text NOT NULL,
    unit_of_measure text,
    is_required boolean DEFAULT false NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT method_parameters_data_type_check CHECK ((data_type = ANY (ARRAY['numeric'::text, 'integer'::text, 'text'::text, 'boolean'::text, 'file_uri'::text, 'timestamp'::text])))
);


--
-- Name: TABLE method_parameters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.method_parameters IS 'Template: which JSONB keys are expected in manufacturing_operations.recorded_metadata for each manufacturing_method. Validates the dynamic-template pattern.';


--
-- Name: COLUMN method_parameters.parameter_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.method_parameters.parameter_name IS 'JSONB key used in recorded_metadata, e.g. peak_temperature_celsius.';


--
-- Name: COLUMN method_parameters.data_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.method_parameters.data_type IS 'Expected data type: numeric, integer, text, boolean, file_uri, or timestamp.';


--
-- Name: COLUMN method_parameters.unit_of_measure; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.method_parameters.unit_of_measure IS 'Physical unit, e.g. degC, mm_per_min, bar, rpm. NULL if dimensionless.';


--
-- Name: physical_samples; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.physical_samples (
    sample_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    sample_code character varying(64) NOT NULL,
    material_id uuid,
    project_id uuid,
    form text,
    mass_grams numeric(12,4),
    diameter_mm numeric(10,4),
    length_mm numeric(10,4),
    thickness_mm numeric(10,4),
    current_status text DEFAULT 'active'::text NOT NULL,
    manufactured_date date,
    export_controlled boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    nickname text,
    location text,
    surface_finish text,
    legacy_notes text,
    width_mm numeric(10,4),
    owner text,
    co_owners text,
    manufacturing_route text,
    mounted boolean,
    mounting_method text,
    item_type text,
    CONSTRAINT physical_samples_item_type_check CHECK ((item_type = ANY (ARRAY['sample'::text, 'equipment'::text, 'miscellaneous'::text]))),
    CONSTRAINT physical_samples_status_check CHECK ((current_status = ANY (ARRAY['active'::text, 'consumed'::text, 'destroyed'::text, 'archived'::text])))
);


--
-- Name: TABLE physical_samples; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.physical_samples IS 'The central entity: every physical sample created in the lab. sample_id is the durable hidden PK; sample_code is the human-readable label.';


--
-- Name: COLUMN physical_samples.sample_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.sample_id IS 'UUID primary key. All foreign keys in other tables point here. Never changes.';


--
-- Name: COLUMN physical_samples.sample_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.sample_code IS 'Human-readable pseudonym, e.g. 10-AA-MF-2023-06-03. Generated by generate_sample_code(). Unique-constrained. NOT the primary key.';


--
-- Name: COLUMN physical_samples.form; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.form IS 'Physical form, e.g. disc, billet, powder-compact, coupon.';


--
-- Name: COLUMN physical_samples.mass_grams; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.mass_grams IS 'Current mass of the sample in grams.';


--
-- Name: COLUMN physical_samples.diameter_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.diameter_mm IS 'Outer diameter in millimetres, if applicable.';


--
-- Name: COLUMN physical_samples.length_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.length_mm IS 'Length in millimetres, if applicable.';


--
-- Name: COLUMN physical_samples.thickness_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.thickness_mm IS 'Thickness in millimetres, if applicable.';


--
-- Name: COLUMN physical_samples.current_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.current_status IS 'Lifecycle state: active | consumed | destroyed | archived.';


--
-- Name: COLUMN physical_samples.export_controlled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.export_controlled IS 'TRUE if subject to ITAR/ECJU controls. May be inherited from material or project.';


--
-- Name: COLUMN physical_samples.nickname; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.nickname IS 'Informal human label for the sample (e.g. "FAST Control", "UD Rolled Control").';


--
-- Name: COLUMN physical_samples.location; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.location IS 'Physical storage location of the sample.';


--
-- Name: COLUMN physical_samples.surface_finish; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.surface_finish IS 'Surface finish state, e.g. Mirror, Machined, As-sintered.';


--
-- Name: COLUMN physical_samples.legacy_notes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.legacy_notes IS 'Free-text notes carried over verbatim from the legacy AppSheet Inventory sheet.';


--
-- Name: COLUMN physical_samples.width_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.width_mm IS 'Width in millimetres (x dimension), if applicable.';


--
-- Name: COLUMN physical_samples.owner; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.owner IS 'Primary owner / responsible person for this sample.';


--
-- Name: COLUMN physical_samples.co_owners; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.co_owners IS 'Comma-separated list of co-owners.';


--
-- Name: COLUMN physical_samples.manufacturing_route; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.manufacturing_route IS 'Free-text manufacturing route label from legacy AppSheet (e.g. FAST, Rolled, Cast).';


--
-- Name: COLUMN physical_samples.mounted; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.mounted IS 'TRUE if the sample has been mounted in resin or a holder.';


--
-- Name: COLUMN physical_samples.mounting_method; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.mounting_method IS 'Mounting method used, e.g. Hot Press, Cold Mount.';


--
-- Name: COLUMN physical_samples.item_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.physical_samples.item_type IS 'AppSheet Item Type: sample | equipment | miscellaneous. Distinct from form/geometry.';


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    project_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    project_code character varying(32) NOT NULL,
    project_name text NOT NULL,
    description text,
    document_number text,
    principal_investigator_name text,
    start_date date,
    end_date date,
    export_controlled boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL
);


--
-- Name: TABLE projects; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.projects IS 'Research campaigns / projects grouping related operations and test sessions. E.g. AI4340 – FAST Rolled Plate Detection.';


--
-- Name: COLUMN projects.project_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.projects.project_code IS 'Short unique identifier, e.g. AI4340. Used in document numbering.';


--
-- Name: COLUMN projects.document_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.projects.document_number IS 'AMRC GESS controlled-document number, e.g. AI4340-AMRC-ES-230323-01.';


--
-- Name: COLUMN projects.export_controlled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.projects.export_controlled IS 'TRUE if the project is subject to ITAR/ECJU controls. Propagates to samples.';


--
-- Name: raw_stock_lots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.raw_stock_lots (
    lot_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    lot_code character varying(64) NOT NULL,
    stock_type text NOT NULL,
    material_id uuid,
    supplier_name text,
    supplier_part_number text,
    mesh_size_micrometres numeric(10,3),
    purity_percent numeric(7,4),
    inbound_mass_grams numeric(12,4) NOT NULL,
    remaining_mass_grams numeric(12,4) NOT NULL,
    received_date date,
    certificate_url text,
    export_controlled boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT raw_stock_lots_inbound_mass_check CHECK ((inbound_mass_grams > (0)::numeric)),
    CONSTRAINT raw_stock_lots_remaining_mass_check CHECK ((remaining_mass_grams >= (0)::numeric)),
    CONSTRAINT raw_stock_lots_stock_type_check CHECK ((stock_type = ANY (ARRAY['swarf'::text, 'powder'::text, 'billet'::text, 'chemical'::text, 'other'::text])))
);


--
-- Name: TABLE raw_stock_lots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.raw_stock_lots IS 'Inbound material ledger. Every manufactured sample must trace back to one or more lots here to maintain material provenance (the weakest link in the legacy data).';


--
-- Name: COLUMN raw_stock_lots.lot_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.lot_code IS 'Human-readable lot identifier, unique across all stock.';


--
-- Name: COLUMN raw_stock_lots.stock_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.stock_type IS 'Form of the raw stock: swarf, powder, billet, chemical, or other.';


--
-- Name: COLUMN raw_stock_lots.mesh_size_micrometres; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.mesh_size_micrometres IS 'Powder mesh/particle size in micrometres. NULL for non-powder stock.';


--
-- Name: COLUMN raw_stock_lots.purity_percent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.purity_percent IS 'Material purity as a percentage (0–100). NULL for alloys/billets.';


--
-- Name: COLUMN raw_stock_lots.inbound_mass_grams; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.inbound_mass_grams IS 'Total mass received in grams. Must be > 0.';


--
-- Name: COLUMN raw_stock_lots.remaining_mass_grams; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.remaining_mass_grams IS 'Current remaining mass in grams. Decremented as material is consumed.';


--
-- Name: COLUMN raw_stock_lots.certificate_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raw_stock_lots.certificate_url IS 'URI to material certificate or datasheet in MinIO or external source.';


--
-- Name: sample_genealogy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_genealogy (
    child_sample_id uuid NOT NULL,
    parent_sample_id uuid NOT NULL,
    relationship_type text DEFAULT 'derived_from'::text NOT NULL,
    fraction numeric(5,4),
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    CONSTRAINT sample_genealogy_no_self_loop CHECK ((child_sample_id <> parent_sample_id)),
    CONSTRAINT sample_genealogy_relationship_check CHECK ((relationship_type = ANY (ARRAY['derived_from'::text, 'cut_from'::text, 'sintered_from'::text, 'powder_from'::text])))
);


--
-- Name: TABLE sample_genealogy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sample_genealogy IS 'Self-referential lineage: which samples were produced from which others. Captures the Parent/Contains structure in the legacy Inventory sheet.';


--
-- Name: COLUMN sample_genealogy.relationship_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sample_genealogy.relationship_type IS 'Nature of the derivation: derived_from, cut_from, sintered_from, powder_from.';


--
-- Name: COLUMN sample_genealogy.fraction; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sample_genealogy.fraction IS 'Fraction of parent mass that became this child (0–1). NULL if unknown.';


--
-- Name: sample_stock_provenance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_stock_provenance (
    sample_id uuid NOT NULL,
    lot_id uuid NOT NULL,
    mass_used_grams numeric(12,4),
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL
);


--
-- Name: TABLE sample_stock_provenance; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sample_stock_provenance IS 'Many-to-many: which raw_stock_lots contributed to which physical_samples. Enables full material-provenance tracing back to inbound material receipts.';


--
-- Name: COLUMN sample_stock_provenance.mass_used_grams; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sample_stock_provenance.mass_used_grams IS 'Mass of raw stock consumed to produce this sample, in grams.';


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: semantic_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.semantic_embeddings (
    embedding_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    source_table text NOT NULL,
    source_id uuid NOT NULL,
    source_column text NOT NULL,
    content_text text NOT NULL,
    content_hash text NOT NULL,
    embedding public.vector(768) NOT NULL,
    model_name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE semantic_embeddings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.semantic_embeddings IS 'pgvector store for unstructured note text (spec §6 hybrid search). One row per (source_table, source_id, source_column, model_name); derived data — rebuildable from the source rows, so not audited.';


--
-- Name: COLUMN semantic_embeddings.source_table; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.source_table IS 'Name of the table the embedded text came from (e.g. physical_samples).';


--
-- Name: COLUMN semantic_embeddings.source_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.source_id IS 'Primary key (UUID) of the source row the embedded text belongs to.';


--
-- Name: COLUMN semantic_embeddings.source_column; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.source_column IS 'Name of the text column embedded (e.g. notes, outcome_notes).';


--
-- Name: COLUMN semantic_embeddings.content_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.content_text IS 'The exact text that was embedded; kept for re-ranking and display.';


--
-- Name: COLUMN semantic_embeddings.content_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.content_hash IS 'SHA-256 of content_text; lets the backfill skip unchanged rows.';


--
-- Name: COLUMN semantic_embeddings.embedding; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.embedding IS 'pgvector embedding (dimension 768, nomic-embed-text). Cosine distance.';


--
-- Name: COLUMN semantic_embeddings.model_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.semantic_embeddings.model_name IS 'Embedding model that produced this vector; part of the uniqueness key.';


--
-- Name: test_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.test_sessions (
    session_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    sample_id uuid NOT NULL,
    equipment_id uuid,
    insert_edge_id uuid,
    project_id uuid,
    operator_name text,
    session_date timestamp with time zone,
    test_type text,
    capture_software text,
    capture_frequency_khz numeric(10,4),
    file_storage_pointer text,
    file_size_gb numeric(10,4),
    summary_stats jsonb,
    plot_uris jsonb,
    status text DEFAULT 'registered'::text NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT test_sessions_status_check CHECK ((status = ANY (ARRAY['registered'::text, 'pending_processing'::text, 'processing'::text, 'processed'::text, 'analysing'::text, 'analysed'::text, 'failed'::text])))
);


--
-- Name: TABLE test_sessions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.test_sessions IS 'Experimental test-session ledger. One row per test run / data-capture event. file_storage_pointer links to the raw file in MinIO (10–100 GB).';


--
-- Name: COLUMN test_sessions.sample_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.sample_id IS 'The sample under test. FK to physical_samples.';


--
-- Name: COLUMN test_sessions.insert_edge_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.insert_edge_id IS 'The specific cutting-edge used in this test. FK to insert_edges.';


--
-- Name: COLUMN test_sessions.test_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.test_type IS 'Category of test, e.g. force_measurement, microstructure, hardness, SEM.';


--
-- Name: COLUMN test_sessions.capture_software; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.capture_software IS 'Data-capture app and version, e.g. MATLAB ABFP 0.18.';


--
-- Name: COLUMN test_sessions.capture_frequency_khz; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.capture_frequency_khz IS 'Sampling frequency in kilohertz (e.g. 25.6). Required to interpret raw files.';


--
-- Name: COLUMN test_sessions.file_storage_pointer; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.file_storage_pointer IS 'MinIO S3 URI for the raw data file, e.g. s3://d1-data/AI4340/9-AA-MR-...';


--
-- Name: COLUMN test_sessions.file_size_gb; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.file_size_gb IS 'Raw file size in gigabytes as reported by the capture client.';


--
-- Name: COLUMN test_sessions.summary_stats; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.summary_stats IS 'JSON statistics written back by the async heavy-data worker after parsing.';


--
-- Name: COLUMN test_sessions.plot_uris; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.plot_uris IS 'JSON array of MinIO URIs for SVG/PNG plots rendered by the worker.';


--
-- Name: COLUMN test_sessions.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.test_sessions.status IS 'Pipeline lifecycle status. Canonical set (see db migration 0013 and each plugin app/lib/statuses.py): registered | pending_processing | processing | processed | analysing | analysed | failed.';


--
-- Name: tool_boxes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_boxes (
    tool_box_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    tool_box_code character varying(64) NOT NULL,
    description text,
    location text,
    insert_type_id uuid,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    package_quantity integer,
    owner text
);


--
-- Name: TABLE tool_boxes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tool_boxes IS 'Grandparent level of the 3-tier tooling hierarchy. A box holds a batch of identical cutting inserts.';


--
-- Name: COLUMN tool_boxes.tool_box_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_boxes.tool_box_code IS 'Unique label on the physical box, e.g. BOX-H13A-001.';


--
-- Name: COLUMN tool_boxes.insert_type_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_boxes.insert_type_id IS 'Default insert type for this box. Individual inserts may override.';


--
-- Name: COLUMN tool_boxes.package_quantity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_boxes.package_quantity IS 'Number of inserts in the original manufacturer package.';


--
-- Name: COLUMN tool_boxes.owner; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_boxes.owner IS 'Owner / responsible person for this box.';


--
-- Name: tools; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tools (
    tool_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    tool_code character varying(64) NOT NULL,
    tool_name text NOT NULL,
    tool_type text,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    manufacturer text,
    datasheet_url text,
    op_type text,
    cutter_diameter_mm numeric(8,3),
    shank_width_mm numeric(8,3),
    shank_length_mm numeric(8,3),
    overall_length_mm numeric(8,3),
    shank_type text,
    cutting_direction text,
    insert_clamping_system text
);


--
-- Name: TABLE tools; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tools IS 'Tool holders used in machining operations.';


--
-- Name: COLUMN tools.tool_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.tool_type IS 'Category, e.g. Turning, Milling.';


--
-- Name: COLUMN tools.manufacturer; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.manufacturer IS 'Tool holder manufacturer name.';


--
-- Name: COLUMN tools.datasheet_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.datasheet_url IS 'Link to manufacturer datasheet or product page.';


--
-- Name: COLUMN tools.op_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.op_type IS 'Operation type, e.g. External, Internal, Face.';


--
-- Name: COLUMN tools.cutter_diameter_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.cutter_diameter_mm IS 'Cutter/body diameter in millimetres.';


--
-- Name: COLUMN tools.shank_width_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.shank_width_mm IS 'Shank width B in millimetres.';


--
-- Name: COLUMN tools.shank_length_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.shank_length_mm IS 'Shank length in millimetres.';


--
-- Name: COLUMN tools.overall_length_mm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.overall_length_mm IS 'Overall tool length in millimetres.';


--
-- Name: COLUMN tools.shank_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.shank_type IS 'Shank interface type, e.g. Capto, HSK, ISO.';


--
-- Name: COLUMN tools.cutting_direction; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.cutting_direction IS 'Cutting direction: Right-Hand, Left-Hand, Neutral.';


--
-- Name: COLUMN tools.insert_clamping_system; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.insert_clamping_system IS 'Insert clamping system code, e.g. P-clamp, S-clamp.';


--
-- Name: v_complete_sample_history; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_complete_sample_history AS
 SELECT ps.sample_id,
    ps.sample_code,
    ps.form,
    ps.mass_grams,
    ps.diameter_mm,
    ps.length_mm,
    ps.thickness_mm,
    ps.current_status,
    ps.manufactured_date,
    ps.export_controlled,
    ps.notes,
    ps.created_at,
    ps.updated_at,
    m.alloy_code,
    m.common_name AS material_name,
    m.iso_code AS material_iso_code,
    m.density_g_per_cm3,
    p.project_code,
    p.project_name,
    p.document_number AS project_document_number
   FROM ((public.physical_samples ps
     LEFT JOIN public.materials m ON ((ps.material_id = m.material_id)))
     LEFT JOIN public.projects p ON ((ps.project_id = p.project_id)));


--
-- Name: VIEW v_complete_sample_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_complete_sample_history IS 'Flat sample profile with material and project context. Primary LLM target for sample-centric queries. Join manufacturing_operations or test_sessions for events.';


--
-- Name: v_embeddings_source_notes; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_embeddings_source_notes AS
 SELECT 'physical_samples'::text AS source_table,
    ps.sample_id AS source_id,
    'notes'::text AS source_column,
    ps.notes AS content_text
   FROM public.physical_samples ps
  WHERE ((ps.notes IS NOT NULL) AND (length(TRIM(BOTH FROM ps.notes)) > 0))
UNION ALL
 SELECT 'manufacturing_operations'::text AS source_table,
    mo.operation_id AS source_id,
    'outcome_notes'::text AS source_column,
    mo.outcome_notes AS content_text
   FROM public.manufacturing_operations mo
  WHERE ((mo.outcome_notes IS NOT NULL) AND (length(TRIM(BOTH FROM mo.outcome_notes)) > 0))
UNION ALL
 SELECT 'test_sessions'::text AS source_table,
    ts.session_id AS source_id,
    'notes'::text AS source_column,
    ts.notes AS content_text
   FROM public.test_sessions ts
  WHERE ((ts.notes IS NOT NULL) AND (length(TRIM(BOTH FROM ts.notes)) > 0))
UNION ALL
 SELECT 'raw_stock_lots'::text AS source_table,
    rsl.lot_id AS source_id,
    'notes'::text AS source_column,
    rsl.notes AS content_text
   FROM public.raw_stock_lots rsl
  WHERE ((rsl.notes IS NOT NULL) AND (length(TRIM(BOTH FROM rsl.notes)) > 0));


--
-- Name: VIEW v_embeddings_source_notes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_embeddings_source_notes IS 'All embeddable free-text notes across the schema, one row each, as the canonical backfill source for semantic_embeddings (spec §6).';


--
-- Name: v_llm_query_targets; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_llm_query_targets AS
 SELECT c.relname AS view_name,
    obj_description(c.oid, 'pg_class'::name) AS description
   FROM (pg_class c
     JOIN pg_namespace n ON ((c.relnamespace = n.oid)))
  WHERE ((n.nspname = 'public'::name) AND (c.relkind = 'v'::"char") AND (c.relname ~~ 'v\_%'::text) AND (c.relname <> ALL (ARRAY['v_llm_query_targets'::name, 'v_embeddings_source_notes'::name])))
  ORDER BY c.relname;


--
-- Name: VIEW v_llm_query_targets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_llm_query_targets IS 'Menu of flattened v_* views the text-to-SQL LLM is allowed to query, with their business-logic descriptions. Mirrors the plugin SQL-guard allow-list.';


--
-- Name: v_manufacturing_operations_full; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_manufacturing_operations_full AS
 SELECT mo.operation_id,
    mo.pass_code,
    mo.operation_date,
    mo.operation_sequence,
    mo.operator_name,
    mo.recorded_metadata,
    mo.capture_software,
    mo.capture_frequency_khz,
    mo.file_storage_pointer,
    mo.force_file_id,
    mo.outcome_notes,
    mo.created_at,
    ps.sample_id,
    ps.sample_code,
    mm.method_id,
    mm.method_name,
    mm.method_code,
    p.project_code,
    p.project_name,
    e.equipment_code,
    e.equipment_name,
    t.tool_code,
    ie.edge_code AS insert_edge_code,
    ci.insert_code,
    tb.tool_box_code
   FROM ((((((((public.manufacturing_operations mo
     JOIN public.physical_samples ps ON ((mo.sample_id = ps.sample_id)))
     JOIN public.manufacturing_methods mm ON ((mo.method_id = mm.method_id)))
     LEFT JOIN public.projects p ON ((mo.project_id = p.project_id)))
     LEFT JOIN public.equipment e ON ((mo.equipment_id = e.equipment_id)))
     LEFT JOIN public.tools t ON ((mo.tool_id = t.tool_id)))
     LEFT JOIN public.insert_edges ie ON ((mo.insert_edge_id = ie.edge_id)))
     LEFT JOIN public.cutting_inserts ci ON ((ie.insert_id = ci.insert_id)))
     LEFT JOIN public.tool_boxes tb ON ((ci.tool_box_id = tb.tool_box_id)));


--
-- Name: VIEW v_manufacturing_operations_full; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_manufacturing_operations_full IS 'Operations with fully denormalized method, sample, tooling, and project context. Use recorded_metadata JSONB for method-specific parameters.';


--
-- Name: v_sample_genealogy_flat; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_sample_genealogy_flat AS
 SELECT sg.relationship_type,
    sg.fraction,
    child_s.sample_id AS child_sample_id,
    child_s.sample_code AS child_sample_code,
    child_s.form AS child_form,
    child_s.current_status AS child_status,
    parent_s.sample_id AS parent_sample_id,
    parent_s.sample_code AS parent_sample_code,
    parent_s.form AS parent_form
   FROM ((public.sample_genealogy sg
     JOIN public.physical_samples child_s ON ((sg.child_sample_id = child_s.sample_id)))
     JOIN public.physical_samples parent_s ON ((sg.parent_sample_id = parent_s.sample_id)));


--
-- Name: VIEW v_sample_genealogy_flat; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_sample_genealogy_flat IS 'Flat parent-child lineage pairs. For forward traceability: WHERE parent_sample_code = ''...''. For reverse: WHERE child_sample_code = ''...''.';


--
-- Name: v_schema_dictionary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_schema_dictionary AS
 SELECT c.relname AS object_name,
    a.attnum AS column_position,
    a.attname AS column_name,
    a.attnotnull AS is_not_null,
        CASE c.relkind
            WHEN 'r'::"char" THEN 'table'::text
            WHEN 'v'::"char" THEN 'view'::text
            WHEN 'm'::"char" THEN 'materialized_view'::text
            ELSE (c.relkind)::text
        END AS object_type,
    format_type(a.atttypid, a.atttypmod) AS data_type,
    obj_description(c.oid, 'pg_class'::name) AS object_comment,
    col_description(c.oid, (a.attnum)::integer) AS column_comment
   FROM ((pg_class c
     JOIN pg_namespace n ON ((c.relnamespace = n.oid)))
     JOIN pg_attribute a ON ((c.oid = a.attrelid)))
  WHERE ((n.nspname = 'public'::name) AND (c.relkind = ANY (ARRAY['r'::"char", 'v'::"char"])) AND (a.attnum > 0) AND (NOT a.attisdropped))
  ORDER BY c.relname, a.attnum;


--
-- Name: VIEW v_schema_dictionary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_schema_dictionary IS 'Flat semantic dictionary: every public table/view column with its native COMMENT, type, and nullability. Primary LLM context source (spec §6).';


--
-- Name: v_stock_provenance; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_stock_provenance AS
 SELECT ps.sample_id,
    ps.sample_code,
    rsl.lot_id,
    rsl.lot_code,
    rsl.stock_type,
    rsl.supplier_name,
    rsl.inbound_mass_grams,
    rsl.remaining_mass_grams,
    ssp.mass_used_grams,
    mat.alloy_code,
    mat.common_name AS material_name
   FROM (((public.sample_stock_provenance ssp
     JOIN public.physical_samples ps ON ((ssp.sample_id = ps.sample_id)))
     JOIN public.raw_stock_lots rsl ON ((ssp.lot_id = rsl.lot_id)))
     LEFT JOIN public.materials mat ON ((rsl.material_id = mat.material_id)));


--
-- Name: VIEW v_stock_provenance; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_stock_provenance IS 'Material provenance: which raw_stock_lots fed which physical_samples. Enables full cradle-to-gate traceability from inbound receipt to sample.';


--
-- Name: v_test_sessions_full; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_test_sessions_full AS
 SELECT ts.session_id,
    ts.session_date,
    ts.test_type,
    ts.operator_name,
    ts.capture_software,
    ts.capture_frequency_khz,
    ts.file_storage_pointer,
    ts.file_size_gb,
    ts.status,
    ts.summary_stats,
    ts.plot_uris,
    ts.notes,
    ts.created_at,
    ps.sample_id,
    ps.sample_code,
    p.project_code,
    p.project_name,
    e.equipment_code,
    e.equipment_name,
    ie.edge_code AS insert_edge_code,
    ci.insert_code,
    tb.tool_box_code
   FROM ((((((public.test_sessions ts
     JOIN public.physical_samples ps ON ((ts.sample_id = ps.sample_id)))
     LEFT JOIN public.projects p ON ((ts.project_id = p.project_id)))
     LEFT JOIN public.equipment e ON ((ts.equipment_id = e.equipment_id)))
     LEFT JOIN public.insert_edges ie ON ((ts.insert_edge_id = ie.edge_id)))
     LEFT JOIN public.cutting_inserts ci ON ((ie.insert_id = ci.insert_id)))
     LEFT JOIN public.tool_boxes tb ON ((ci.tool_box_id = tb.tool_box_id)));


--
-- Name: VIEW v_test_sessions_full; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_test_sessions_full IS 'Test sessions with fully denormalized sample, equipment, and tooling context. plot_uris and summary_stats are populated by the async heavy-data worker.';


--
-- Name: v_tooling_hierarchy; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_tooling_hierarchy AS
 SELECT tb.tool_box_id,
    tb.tool_box_code,
    tb.description AS tool_box_description,
    tb.location AS tool_box_location,
    ci.insert_id,
    ci.insert_code,
    ci.insert_number,
    ci.is_depleted AS insert_depleted,
    ie.edge_id,
    ie.edge_code,
    ie.edge_identifier,
    ie.is_used AS edge_used,
    it.type_code AS insert_type_code,
    it.manufacturer AS insert_manufacturer,
    it.substrate AS insert_substrate
   FROM (((public.tool_boxes tb
     LEFT JOIN public.cutting_inserts ci ON ((tb.tool_box_id = ci.tool_box_id)))
     LEFT JOIN public.insert_edges ie ON ((ci.insert_id = ie.insert_id)))
     LEFT JOIN public.insert_types it ON ((ci.insert_type_id = it.insert_type_id)));


--
-- Name: VIEW v_tooling_hierarchy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_tooling_hierarchy IS 'Full denormalized view of the 3-tier tooling hierarchy: tool_boxes → cutting_inserts → insert_edges.';


--
-- Name: audit_logs log_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN log_id SET DEFAULT nextval('public.audit_logs_log_id_seq'::regclass);


--
-- Name: directus_activity id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_activity ALTER COLUMN id SET DEFAULT nextval('public.directus_activity_id_seq'::regclass);


--
-- Name: directus_fields id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_fields ALTER COLUMN id SET DEFAULT nextval('public.directus_fields_id_seq'::regclass);


--
-- Name: directus_notifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_notifications ALTER COLUMN id SET DEFAULT nextval('public.directus_notifications_id_seq'::regclass);


--
-- Name: directus_permissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_permissions ALTER COLUMN id SET DEFAULT nextval('public.directus_permissions_id_seq'::regclass);


--
-- Name: directus_presets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_presets ALTER COLUMN id SET DEFAULT nextval('public.directus_presets_id_seq'::regclass);


--
-- Name: directus_relations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_relations ALTER COLUMN id SET DEFAULT nextval('public.directus_relations_id_seq'::regclass);


--
-- Name: directus_revisions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_revisions ALTER COLUMN id SET DEFAULT nextval('public.directus_revisions_id_seq'::regclass);


--
-- Name: directus_settings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings ALTER COLUMN id SET DEFAULT nextval('public.directus_settings_id_seq'::regclass);


--
-- Name: alloying_elements alloying_elements_atomic_number_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alloying_elements
    ADD CONSTRAINT alloying_elements_atomic_number_unique UNIQUE (atomic_number);


--
-- Name: alloying_elements alloying_elements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alloying_elements
    ADD CONSTRAINT alloying_elements_pkey PRIMARY KEY (symbol);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (log_id);


--
-- Name: cutting_inserts cutting_inserts_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cutting_inserts
    ADD CONSTRAINT cutting_inserts_code_unique UNIQUE (insert_code);


--
-- Name: cutting_inserts cutting_inserts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cutting_inserts
    ADD CONSTRAINT cutting_inserts_pkey PRIMARY KEY (insert_id);


--
-- Name: directus_access directus_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_access
    ADD CONSTRAINT directus_access_pkey PRIMARY KEY (id);


--
-- Name: directus_activity directus_activity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_activity
    ADD CONSTRAINT directus_activity_pkey PRIMARY KEY (id);


--
-- Name: directus_collections directus_collections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_collections
    ADD CONSTRAINT directus_collections_pkey PRIMARY KEY (collection);


--
-- Name: directus_comments directus_comments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_comments
    ADD CONSTRAINT directus_comments_pkey PRIMARY KEY (id);


--
-- Name: directus_dashboards directus_dashboards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_dashboards
    ADD CONSTRAINT directus_dashboards_pkey PRIMARY KEY (id);


--
-- Name: directus_deployment_projects directus_deployment_projects_deployment_external_id_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_projects
    ADD CONSTRAINT directus_deployment_projects_deployment_external_id_unique UNIQUE (deployment, external_id);


--
-- Name: directus_deployment_projects directus_deployment_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_projects
    ADD CONSTRAINT directus_deployment_projects_pkey PRIMARY KEY (id);


--
-- Name: directus_deployment_runs directus_deployment_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_runs
    ADD CONSTRAINT directus_deployment_runs_pkey PRIMARY KEY (id);


--
-- Name: directus_deployments directus_deployments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployments
    ADD CONSTRAINT directus_deployments_pkey PRIMARY KEY (id);


--
-- Name: directus_deployments directus_deployments_provider_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployments
    ADD CONSTRAINT directus_deployments_provider_unique UNIQUE (provider);


--
-- Name: directus_extensions directus_extensions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_extensions
    ADD CONSTRAINT directus_extensions_pkey PRIMARY KEY (id);


--
-- Name: directus_fields directus_fields_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_fields
    ADD CONSTRAINT directus_fields_pkey PRIMARY KEY (id);


--
-- Name: directus_files directus_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_files
    ADD CONSTRAINT directus_files_pkey PRIMARY KEY (id);


--
-- Name: directus_flows directus_flows_operation_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_flows
    ADD CONSTRAINT directus_flows_operation_unique UNIQUE (operation);


--
-- Name: directus_flows directus_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_flows
    ADD CONSTRAINT directus_flows_pkey PRIMARY KEY (id);


--
-- Name: directus_folders directus_folders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_folders
    ADD CONSTRAINT directus_folders_pkey PRIMARY KEY (id);


--
-- Name: directus_migrations directus_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_migrations
    ADD CONSTRAINT directus_migrations_pkey PRIMARY KEY (version);


--
-- Name: directus_notifications directus_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_notifications
    ADD CONSTRAINT directus_notifications_pkey PRIMARY KEY (id);


--
-- Name: directus_operations directus_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_pkey PRIMARY KEY (id);


--
-- Name: directus_operations directus_operations_reject_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_reject_unique UNIQUE (reject);


--
-- Name: directus_operations directus_operations_resolve_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_resolve_unique UNIQUE (resolve);


--
-- Name: directus_panels directus_panels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_panels
    ADD CONSTRAINT directus_panels_pkey PRIMARY KEY (id);


--
-- Name: directus_permissions directus_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_permissions
    ADD CONSTRAINT directus_permissions_pkey PRIMARY KEY (id);


--
-- Name: directus_policies directus_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_policies
    ADD CONSTRAINT directus_policies_pkey PRIMARY KEY (id);


--
-- Name: directus_presets directus_presets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_presets
    ADD CONSTRAINT directus_presets_pkey PRIMARY KEY (id);


--
-- Name: directus_relations directus_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_relations
    ADD CONSTRAINT directus_relations_pkey PRIMARY KEY (id);


--
-- Name: directus_revisions directus_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_revisions
    ADD CONSTRAINT directus_revisions_pkey PRIMARY KEY (id);


--
-- Name: directus_roles directus_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_roles
    ADD CONSTRAINT directus_roles_pkey PRIMARY KEY (id);


--
-- Name: directus_sessions directus_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_sessions
    ADD CONSTRAINT directus_sessions_pkey PRIMARY KEY (token);


--
-- Name: directus_settings directus_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_pkey PRIMARY KEY (id);


--
-- Name: directus_shares directus_shares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_shares
    ADD CONSTRAINT directus_shares_pkey PRIMARY KEY (id);


--
-- Name: directus_translations directus_translations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_translations
    ADD CONSTRAINT directus_translations_pkey PRIMARY KEY (id);


--
-- Name: directus_users directus_users_email_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_users
    ADD CONSTRAINT directus_users_email_unique UNIQUE (email);


--
-- Name: directus_users directus_users_external_identifier_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_users
    ADD CONSTRAINT directus_users_external_identifier_unique UNIQUE (external_identifier);


--
-- Name: directus_users directus_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_users
    ADD CONSTRAINT directus_users_pkey PRIMARY KEY (id);


--
-- Name: directus_users directus_users_token_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_users
    ADD CONSTRAINT directus_users_token_unique UNIQUE (token);


--
-- Name: directus_versions directus_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_versions
    ADD CONSTRAINT directus_versions_pkey PRIMARY KEY (id);


--
-- Name: equipment equipment_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment
    ADD CONSTRAINT equipment_code_unique UNIQUE (equipment_code);


--
-- Name: equipment equipment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment
    ADD CONSTRAINT equipment_pkey PRIMARY KEY (equipment_id);


--
-- Name: insert_edges insert_edges_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insert_edges
    ADD CONSTRAINT insert_edges_code_unique UNIQUE (edge_code);


--
-- Name: insert_edges insert_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insert_edges
    ADD CONSTRAINT insert_edges_pkey PRIMARY KEY (edge_id);


--
-- Name: insert_types insert_types_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insert_types
    ADD CONSTRAINT insert_types_code_unique UNIQUE (type_code);


--
-- Name: insert_types insert_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insert_types
    ADD CONSTRAINT insert_types_pkey PRIMARY KEY (insert_type_id);


--
-- Name: manufacturing_methods manufacturing_methods_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_methods
    ADD CONSTRAINT manufacturing_methods_code_unique UNIQUE (method_code);


--
-- Name: manufacturing_methods manufacturing_methods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_methods
    ADD CONSTRAINT manufacturing_methods_pkey PRIMARY KEY (method_id);


--
-- Name: manufacturing_operations manufacturing_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_pkey PRIMARY KEY (operation_id);


--
-- Name: material_alloying_elements material_alloying_elements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.material_alloying_elements
    ADD CONSTRAINT material_alloying_elements_pkey PRIMARY KEY (material_id, symbol);


--
-- Name: material_iso_classifications material_iso_classifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.material_iso_classifications
    ADD CONSTRAINT material_iso_classifications_pkey PRIMARY KEY (iso_code);


--
-- Name: materials materials_alloy_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT materials_alloy_code_unique UNIQUE (alloy_code);


--
-- Name: materials materials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT materials_pkey PRIMARY KEY (material_id);


--
-- Name: method_parameters method_parameters_method_param_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.method_parameters
    ADD CONSTRAINT method_parameters_method_param_unique UNIQUE (method_id, parameter_name);


--
-- Name: method_parameters method_parameters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.method_parameters
    ADD CONSTRAINT method_parameters_pkey PRIMARY KEY (parameter_id);


--
-- Name: physical_samples physical_samples_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_samples
    ADD CONSTRAINT physical_samples_code_unique UNIQUE (sample_code);


--
-- Name: physical_samples physical_samples_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_samples
    ADD CONSTRAINT physical_samples_pkey PRIMARY KEY (sample_id);


--
-- Name: projects projects_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_code_unique UNIQUE (project_code);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (project_id);


--
-- Name: raw_stock_lots raw_stock_lots_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raw_stock_lots
    ADD CONSTRAINT raw_stock_lots_code_unique UNIQUE (lot_code);


--
-- Name: raw_stock_lots raw_stock_lots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raw_stock_lots
    ADD CONSTRAINT raw_stock_lots_pkey PRIMARY KEY (lot_id);


--
-- Name: sample_genealogy sample_genealogy_pair_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_genealogy
    ADD CONSTRAINT sample_genealogy_pair_unique UNIQUE (child_sample_id, parent_sample_id);


--
-- Name: sample_genealogy sample_genealogy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_genealogy
    ADD CONSTRAINT sample_genealogy_pkey PRIMARY KEY (id);


--
-- Name: sample_stock_provenance sample_stock_provenance_pair_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_pair_unique UNIQUE (sample_id, lot_id);


--
-- Name: sample_stock_provenance sample_stock_provenance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: semantic_embeddings semantic_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.semantic_embeddings
    ADD CONSTRAINT semantic_embeddings_pkey PRIMARY KEY (embedding_id);


--
-- Name: semantic_embeddings semantic_embeddings_source_uq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.semantic_embeddings
    ADD CONSTRAINT semantic_embeddings_source_uq UNIQUE (source_table, source_id, source_column, model_name);


--
-- Name: test_sessions test_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_sessions
    ADD CONSTRAINT test_sessions_pkey PRIMARY KEY (session_id);


--
-- Name: tool_boxes tool_boxes_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_boxes
    ADD CONSTRAINT tool_boxes_code_unique UNIQUE (tool_box_code);


--
-- Name: tool_boxes tool_boxes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_boxes
    ADD CONSTRAINT tool_boxes_pkey PRIMARY KEY (tool_box_id);


--
-- Name: tools tools_code_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tools
    ADD CONSTRAINT tools_code_unique UNIQUE (tool_code);


--
-- Name: tools tools_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tools
    ADD CONSTRAINT tools_pkey PRIMARY KEY (tool_id);


--
-- Name: directus_activity_timestamp_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX directus_activity_timestamp_index ON public.directus_activity USING btree ("timestamp");


--
-- Name: directus_revisions_activity_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX directus_revisions_activity_index ON public.directus_revisions USING btree (activity);


--
-- Name: directus_revisions_parent_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX directus_revisions_parent_index ON public.directus_revisions USING btree (parent);


--
-- Name: manufacturing_operations_metadata_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX manufacturing_operations_metadata_gin_idx ON public.manufacturing_operations USING gin (recorded_metadata);


--
-- Name: manufacturing_operations_sample_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX manufacturing_operations_sample_seq_idx ON public.manufacturing_operations USING btree (sample_id, operation_sequence);


--
-- Name: semantic_embeddings_hnsw_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX semantic_embeddings_hnsw_idx ON public.semantic_embeddings USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: semantic_embeddings_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX semantic_embeddings_source_idx ON public.semantic_embeddings USING btree (source_table, source_id);


--
-- Name: audit_logs audit_logs_no_delete; Type: RULE; Schema: public; Owner: -
--

CREATE RULE audit_logs_no_delete AS
    ON DELETE TO public.audit_logs DO INSTEAD NOTHING;


--
-- Name: audit_logs audit_logs_no_update; Type: RULE; Schema: public; Owner: -
--

CREATE RULE audit_logs_no_update AS
    ON UPDATE TO public.audit_logs DO INSTEAD NOTHING;


--
-- Name: cutting_inserts audit_cutting_inserts; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_cutting_inserts AFTER INSERT OR DELETE OR UPDATE ON public.cutting_inserts FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: insert_edges audit_insert_edges; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_insert_edges AFTER INSERT OR DELETE OR UPDATE ON public.insert_edges FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: manufacturing_operations audit_manufacturing_operations; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_manufacturing_operations AFTER INSERT OR DELETE OR UPDATE ON public.manufacturing_operations FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: physical_samples audit_physical_samples; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_physical_samples AFTER INSERT OR DELETE OR UPDATE ON public.physical_samples FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: projects audit_projects; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_projects AFTER INSERT OR DELETE OR UPDATE ON public.projects FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: raw_stock_lots audit_raw_stock_lots; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_raw_stock_lots AFTER INSERT OR DELETE OR UPDATE ON public.raw_stock_lots FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: test_sessions audit_test_sessions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_test_sessions AFTER INSERT OR DELETE OR UPDATE ON public.test_sessions FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: tool_boxes audit_tool_boxes; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_tool_boxes AFTER INSERT OR DELETE OR UPDATE ON public.tool_boxes FOR EACH ROW EXECUTE FUNCTION public.audit_trigger_function();


--
-- Name: cutting_inserts occ_cutting_inserts; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_cutting_inserts BEFORE UPDATE ON public.cutting_inserts FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: equipment occ_equipment; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_equipment BEFORE UPDATE ON public.equipment FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: insert_edges occ_insert_edges; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_insert_edges BEFORE UPDATE ON public.insert_edges FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: insert_types occ_insert_types; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_insert_types BEFORE UPDATE ON public.insert_types FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: manufacturing_methods occ_manufacturing_methods; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_manufacturing_methods BEFORE UPDATE ON public.manufacturing_methods FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: manufacturing_operations occ_manufacturing_operations; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_manufacturing_operations BEFORE UPDATE ON public.manufacturing_operations FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: physical_samples occ_physical_samples; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_physical_samples BEFORE UPDATE ON public.physical_samples FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: projects occ_projects; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_projects BEFORE UPDATE ON public.projects FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: raw_stock_lots occ_raw_stock_lots; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_raw_stock_lots BEFORE UPDATE ON public.raw_stock_lots FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: test_sessions occ_test_sessions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_test_sessions BEFORE UPDATE ON public.test_sessions FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: tool_boxes occ_tool_boxes; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_tool_boxes BEFORE UPDATE ON public.tool_boxes FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: tools occ_tools; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER occ_tools BEFORE UPDATE ON public.tools FOR EACH ROW EXECUTE FUNCTION public.occ_update_trigger_function();


--
-- Name: cutting_inserts cutting_inserts_insert_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cutting_inserts
    ADD CONSTRAINT cutting_inserts_insert_type_id_fkey FOREIGN KEY (insert_type_id) REFERENCES public.insert_types(insert_type_id);


--
-- Name: cutting_inserts cutting_inserts_tool_box_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cutting_inserts
    ADD CONSTRAINT cutting_inserts_tool_box_id_fkey FOREIGN KEY (tool_box_id) REFERENCES public.tool_boxes(tool_box_id);


--
-- Name: directus_access directus_access_policy_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_access
    ADD CONSTRAINT directus_access_policy_foreign FOREIGN KEY (policy) REFERENCES public.directus_policies(id) ON DELETE CASCADE;


--
-- Name: directus_access directus_access_role_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_access
    ADD CONSTRAINT directus_access_role_foreign FOREIGN KEY (role) REFERENCES public.directus_roles(id) ON DELETE CASCADE;


--
-- Name: directus_access directus_access_user_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_access
    ADD CONSTRAINT directus_access_user_foreign FOREIGN KEY ("user") REFERENCES public.directus_users(id) ON DELETE CASCADE;


--
-- Name: directus_collections directus_collections_group_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_collections
    ADD CONSTRAINT directus_collections_group_foreign FOREIGN KEY ("group") REFERENCES public.directus_collections(collection);


--
-- Name: directus_comments directus_comments_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_comments
    ADD CONSTRAINT directus_comments_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_comments directus_comments_user_updated_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_comments
    ADD CONSTRAINT directus_comments_user_updated_foreign FOREIGN KEY (user_updated) REFERENCES public.directus_users(id);


--
-- Name: directus_dashboards directus_dashboards_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_dashboards
    ADD CONSTRAINT directus_dashboards_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_deployment_projects directus_deployment_projects_deployment_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_projects
    ADD CONSTRAINT directus_deployment_projects_deployment_foreign FOREIGN KEY (deployment) REFERENCES public.directus_deployments(id) ON DELETE CASCADE;


--
-- Name: directus_deployment_projects directus_deployment_projects_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_projects
    ADD CONSTRAINT directus_deployment_projects_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_deployment_runs directus_deployment_runs_project_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_runs
    ADD CONSTRAINT directus_deployment_runs_project_foreign FOREIGN KEY (project) REFERENCES public.directus_deployment_projects(id) ON DELETE CASCADE;


--
-- Name: directus_deployment_runs directus_deployment_runs_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployment_runs
    ADD CONSTRAINT directus_deployment_runs_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_deployments directus_deployments_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_deployments
    ADD CONSTRAINT directus_deployments_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_files directus_files_folder_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_files
    ADD CONSTRAINT directus_files_folder_foreign FOREIGN KEY (folder) REFERENCES public.directus_folders(id) ON DELETE SET NULL;


--
-- Name: directus_files directus_files_modified_by_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_files
    ADD CONSTRAINT directus_files_modified_by_foreign FOREIGN KEY (modified_by) REFERENCES public.directus_users(id);


--
-- Name: directus_files directus_files_uploaded_by_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_files
    ADD CONSTRAINT directus_files_uploaded_by_foreign FOREIGN KEY (uploaded_by) REFERENCES public.directus_users(id);


--
-- Name: directus_flows directus_flows_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_flows
    ADD CONSTRAINT directus_flows_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_folders directus_folders_parent_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_folders
    ADD CONSTRAINT directus_folders_parent_foreign FOREIGN KEY (parent) REFERENCES public.directus_folders(id);


--
-- Name: directus_notifications directus_notifications_recipient_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_notifications
    ADD CONSTRAINT directus_notifications_recipient_foreign FOREIGN KEY (recipient) REFERENCES public.directus_users(id) ON DELETE CASCADE;


--
-- Name: directus_notifications directus_notifications_sender_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_notifications
    ADD CONSTRAINT directus_notifications_sender_foreign FOREIGN KEY (sender) REFERENCES public.directus_users(id);


--
-- Name: directus_operations directus_operations_flow_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_flow_foreign FOREIGN KEY (flow) REFERENCES public.directus_flows(id) ON DELETE CASCADE;


--
-- Name: directus_operations directus_operations_reject_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_reject_foreign FOREIGN KEY (reject) REFERENCES public.directus_operations(id);


--
-- Name: directus_operations directus_operations_resolve_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_resolve_foreign FOREIGN KEY (resolve) REFERENCES public.directus_operations(id);


--
-- Name: directus_operations directus_operations_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_operations
    ADD CONSTRAINT directus_operations_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_panels directus_panels_dashboard_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_panels
    ADD CONSTRAINT directus_panels_dashboard_foreign FOREIGN KEY (dashboard) REFERENCES public.directus_dashboards(id) ON DELETE CASCADE;


--
-- Name: directus_panels directus_panels_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_panels
    ADD CONSTRAINT directus_panels_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_permissions directus_permissions_policy_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_permissions
    ADD CONSTRAINT directus_permissions_policy_foreign FOREIGN KEY (policy) REFERENCES public.directus_policies(id) ON DELETE CASCADE;


--
-- Name: directus_presets directus_presets_role_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_presets
    ADD CONSTRAINT directus_presets_role_foreign FOREIGN KEY (role) REFERENCES public.directus_roles(id) ON DELETE CASCADE;


--
-- Name: directus_presets directus_presets_user_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_presets
    ADD CONSTRAINT directus_presets_user_foreign FOREIGN KEY ("user") REFERENCES public.directus_users(id) ON DELETE CASCADE;


--
-- Name: directus_revisions directus_revisions_activity_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_revisions
    ADD CONSTRAINT directus_revisions_activity_foreign FOREIGN KEY (activity) REFERENCES public.directus_activity(id) ON DELETE CASCADE;


--
-- Name: directus_revisions directus_revisions_parent_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_revisions
    ADD CONSTRAINT directus_revisions_parent_foreign FOREIGN KEY (parent) REFERENCES public.directus_revisions(id);


--
-- Name: directus_revisions directus_revisions_version_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_revisions
    ADD CONSTRAINT directus_revisions_version_foreign FOREIGN KEY (version) REFERENCES public.directus_versions(id) ON DELETE CASCADE;


--
-- Name: directus_roles directus_roles_parent_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_roles
    ADD CONSTRAINT directus_roles_parent_foreign FOREIGN KEY (parent) REFERENCES public.directus_roles(id);


--
-- Name: directus_sessions directus_sessions_share_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_sessions
    ADD CONSTRAINT directus_sessions_share_foreign FOREIGN KEY (share) REFERENCES public.directus_shares(id) ON DELETE CASCADE;


--
-- Name: directus_sessions directus_sessions_user_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_sessions
    ADD CONSTRAINT directus_sessions_user_foreign FOREIGN KEY ("user") REFERENCES public.directus_users(id) ON DELETE CASCADE;


--
-- Name: directus_settings directus_settings_project_logo_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_project_logo_foreign FOREIGN KEY (project_logo) REFERENCES public.directus_files(id);


--
-- Name: directus_settings directus_settings_public_background_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_public_background_foreign FOREIGN KEY (public_background) REFERENCES public.directus_files(id);


--
-- Name: directus_settings directus_settings_public_favicon_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_public_favicon_foreign FOREIGN KEY (public_favicon) REFERENCES public.directus_files(id);


--
-- Name: directus_settings directus_settings_public_foreground_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_public_foreground_foreign FOREIGN KEY (public_foreground) REFERENCES public.directus_files(id);


--
-- Name: directus_settings directus_settings_public_registration_role_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_public_registration_role_foreign FOREIGN KEY (public_registration_role) REFERENCES public.directus_roles(id) ON DELETE SET NULL;


--
-- Name: directus_settings directus_settings_storage_default_folder_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_settings
    ADD CONSTRAINT directus_settings_storage_default_folder_foreign FOREIGN KEY (storage_default_folder) REFERENCES public.directus_folders(id) ON DELETE SET NULL;


--
-- Name: directus_shares directus_shares_collection_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_shares
    ADD CONSTRAINT directus_shares_collection_foreign FOREIGN KEY (collection) REFERENCES public.directus_collections(collection) ON DELETE CASCADE;


--
-- Name: directus_shares directus_shares_role_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_shares
    ADD CONSTRAINT directus_shares_role_foreign FOREIGN KEY (role) REFERENCES public.directus_roles(id) ON DELETE CASCADE;


--
-- Name: directus_shares directus_shares_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_shares
    ADD CONSTRAINT directus_shares_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_users directus_users_role_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_users
    ADD CONSTRAINT directus_users_role_foreign FOREIGN KEY (role) REFERENCES public.directus_roles(id) ON DELETE SET NULL;


--
-- Name: directus_versions directus_versions_collection_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_versions
    ADD CONSTRAINT directus_versions_collection_foreign FOREIGN KEY (collection) REFERENCES public.directus_collections(collection) ON DELETE CASCADE;


--
-- Name: directus_versions directus_versions_user_created_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_versions
    ADD CONSTRAINT directus_versions_user_created_foreign FOREIGN KEY (user_created) REFERENCES public.directus_users(id) ON DELETE SET NULL;


--
-- Name: directus_versions directus_versions_user_updated_foreign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directus_versions
    ADD CONSTRAINT directus_versions_user_updated_foreign FOREIGN KEY (user_updated) REFERENCES public.directus_users(id);


--
-- Name: insert_edges insert_edges_insert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insert_edges
    ADD CONSTRAINT insert_edges_insert_id_fkey FOREIGN KEY (insert_id) REFERENCES public.cutting_inserts(insert_id);


--
-- Name: manufacturing_operations manufacturing_operations_equipment_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_equipment_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(equipment_id);


--
-- Name: manufacturing_operations manufacturing_operations_insert_edge_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_insert_edge_fkey FOREIGN KEY (insert_edge_id) REFERENCES public.insert_edges(edge_id);


--
-- Name: manufacturing_operations manufacturing_operations_method_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_method_fkey FOREIGN KEY (method_id) REFERENCES public.manufacturing_methods(method_id);


--
-- Name: manufacturing_operations manufacturing_operations_project_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_project_fkey FOREIGN KEY (project_id) REFERENCES public.projects(project_id);


--
-- Name: manufacturing_operations manufacturing_operations_sample_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_sample_fkey FOREIGN KEY (sample_id) REFERENCES public.physical_samples(sample_id);


--
-- Name: manufacturing_operations manufacturing_operations_tool_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturing_operations
    ADD CONSTRAINT manufacturing_operations_tool_fkey FOREIGN KEY (tool_id) REFERENCES public.tools(tool_id);


--
-- Name: material_alloying_elements material_alloying_elements_material_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.material_alloying_elements
    ADD CONSTRAINT material_alloying_elements_material_id_fkey FOREIGN KEY (material_id) REFERENCES public.materials(material_id) ON DELETE CASCADE;


--
-- Name: material_alloying_elements material_alloying_elements_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.material_alloying_elements
    ADD CONSTRAINT material_alloying_elements_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.alloying_elements(symbol) ON DELETE RESTRICT;


--
-- Name: materials materials_iso_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT materials_iso_code_fkey FOREIGN KEY (iso_code) REFERENCES public.material_iso_classifications(iso_code);


--
-- Name: method_parameters method_parameters_method_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.method_parameters
    ADD CONSTRAINT method_parameters_method_id_fkey FOREIGN KEY (method_id) REFERENCES public.manufacturing_methods(method_id);


--
-- Name: physical_samples physical_samples_material_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_samples
    ADD CONSTRAINT physical_samples_material_id_fkey FOREIGN KEY (material_id) REFERENCES public.materials(material_id);


--
-- Name: physical_samples physical_samples_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_samples
    ADD CONSTRAINT physical_samples_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(project_id);


--
-- Name: raw_stock_lots raw_stock_lots_material_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raw_stock_lots
    ADD CONSTRAINT raw_stock_lots_material_id_fkey FOREIGN KEY (material_id) REFERENCES public.materials(material_id);


--
-- Name: sample_genealogy sample_genealogy_child_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_genealogy
    ADD CONSTRAINT sample_genealogy_child_fkey FOREIGN KEY (child_sample_id) REFERENCES public.physical_samples(sample_id);


--
-- Name: sample_genealogy sample_genealogy_parent_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_genealogy
    ADD CONSTRAINT sample_genealogy_parent_fkey FOREIGN KEY (parent_sample_id) REFERENCES public.physical_samples(sample_id);


--
-- Name: sample_stock_provenance sample_stock_provenance_lot_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_lot_fkey FOREIGN KEY (lot_id) REFERENCES public.raw_stock_lots(lot_id);


--
-- Name: sample_stock_provenance sample_stock_provenance_sample_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_sample_fkey FOREIGN KEY (sample_id) REFERENCES public.physical_samples(sample_id);


--
-- Name: test_sessions test_sessions_equipment_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_sessions
    ADD CONSTRAINT test_sessions_equipment_fkey FOREIGN KEY (equipment_id) REFERENCES public.equipment(equipment_id);


--
-- Name: test_sessions test_sessions_insert_edge_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_sessions
    ADD CONSTRAINT test_sessions_insert_edge_fkey FOREIGN KEY (insert_edge_id) REFERENCES public.insert_edges(edge_id);


--
-- Name: test_sessions test_sessions_project_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_sessions
    ADD CONSTRAINT test_sessions_project_fkey FOREIGN KEY (project_id) REFERENCES public.projects(project_id);


--
-- Name: test_sessions test_sessions_sample_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.test_sessions
    ADD CONSTRAINT test_sessions_sample_fkey FOREIGN KEY (sample_id) REFERENCES public.physical_samples(sample_id);


--
-- Name: tool_boxes tool_boxes_insert_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_boxes
    ADD CONSTRAINT tool_boxes_insert_type_id_fkey FOREIGN KEY (insert_type_id) REFERENCES public.insert_types(insert_type_id);


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20260618000001'),
    ('20260618000002'),
    ('20260618000003'),
    ('20260618000004'),
    ('20260618000005'),
    ('20260618000006'),
    ('20260618000007'),
    ('20260618000008'),
    ('20260618000009'),
    ('20260618000010'),
    ('20260618000011'),
    ('20260618000012'),
    ('20260619000013'),
    ('20260619000014'),
    ('20260619000015'),
    ('20260619000016'),
    ('20260620000017'),
    ('20260620000018'),
    ('20260620000019'),
    ('20260620000020'),
    ('20260620000021');
