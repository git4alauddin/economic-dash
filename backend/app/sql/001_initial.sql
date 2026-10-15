-- M3 direct inputs are archival; derived values are recomputed from their inputs.
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY CHECK(length(trim(source_id)) > 0),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    provider TEXT NOT NULL CHECK(length(trim(provider)) > 0),
    url TEXT NOT NULL CHECK(url LIKE 'https://%'),
    is_nse INTEGER NOT NULL CHECK(is_nse IN (0, 1)),
    limitations_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(limitations_json) AND json_type(limitations_json) = 'array')
) STRICT;

CREATE TABLE indicators (
    indicator_id TEXT PRIMARY KEY CHECK(length(trim(indicator_id)) > 0),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0)
) STRICT;

-- Definition is part of the key: a later base/coverage change cannot relabel history.
CREATE TABLE series (
    series_id TEXT NOT NULL CHECK(length(trim(series_id)) > 0),
    definition_id TEXT NOT NULL CHECK(length(trim(definition_id)) > 0),
    indicator_id TEXT NOT NULL REFERENCES indicators(indicator_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    definition TEXT NOT NULL CHECK(length(trim(definition)) > 0),
    unit TEXT NOT NULL CHECK(unit IN ('percent_yoy', 'percent_of_gdp', 'percent', 'inr_crore', 'usd_billion', 'index_points')),
    frequency TEXT NOT NULL CHECK(frequency IN ('annual', 'monthly', 'monthly_cumulative', 'policy_event', 'market_session_quote')),
    basis TEXT CHECK(basis IN ('calendar', 'fiscal')),
    storage_kind TEXT NOT NULL CHECK(storage_kind IN ('direct', 'derived', 'blocked')),
    dimensions_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(dimensions_json) AND json_type(dimensions_json) = 'object'),
    PRIMARY KEY(series_id, definition_id),
    UNIQUE(series_id, definition_id, source_id, unit, frequency, basis, storage_kind),
    CHECK(storage_kind != 'direct' OR (basis IS NOT NULL AND frequency IN ('annual', 'monthly', 'monthly_cumulative')))
) STRICT;

-- Includes blocked/unbound requirements; unknown definitions stay NULL, without invented series.
CREATE TABLE requirement_bindings (
    requirement_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    definition_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('selected', 'derived', 'blocked')),
    unit TEXT,
    frequency TEXT NOT NULL,
    basis TEXT CHECK(basis IN ('calendar', 'fiscal')),
    reason_code TEXT,
    transform_id TEXT,
    inputs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(inputs_json) AND json_type(inputs_json) = 'array'),
    FOREIGN KEY(requirement_id, definition_id) REFERENCES series(series_id, definition_id),
    CHECK((status = 'blocked' AND reason_code IS NOT NULL) OR
          (status != 'blocked' AND reason_code IS NULL AND definition_id IS NOT NULL AND unit IS NOT NULL AND basis IS NOT NULL)),
    CHECK(status != 'derived' OR (transform_id IS NOT NULL AND json_array_length(inputs_json) > 0))
) STRICT;

CREATE TABLE collector_runs (
    run_id TEXT PRIMARY KEY CHECK(length(run_id) BETWEEN 1 AND 128),
    envelope_digest TEXT NOT NULL CHECK(length(envelope_digest) = 71 AND envelope_digest GLOB 'sha256:*' AND substr(envelope_digest, 8) NOT GLOB '*[^0-9a-f]*'),
    catalog_fingerprint TEXT NOT NULL CHECK(length(catalog_fingerprint) = 71 AND catalog_fingerprint GLOB 'sha256:*' AND substr(catalog_fingerprint, 8) NOT GLOB '*[^0-9a-f]*'),
    contract_version TEXT NOT NULL CHECK(contract_version = 'm3-m4-ingest-v1'),
    repository_version TEXT NOT NULL CHECK(length(repository_version) > 0),
    trigger TEXT NOT NULL CHECK(length(trigger) BETWEEN 1 AND 64),
    started_at TEXT NOT NULL CHECK(length(started_at) = 27 AND started_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(started_at) IS NOT NULL),
    finished_at TEXT NOT NULL CHECK(length(finished_at) = 27 AND finished_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(finished_at) IS NOT NULL AND finished_at >= started_at),
    status TEXT NOT NULL CHECK(status IN ('prepared', 'unchanged', 'partial', 'failed', 'timeout', 'cancelled')),
    observation_count INTEGER NOT NULL CHECK(observation_count >= 0),
    envelope_json TEXT NOT NULL CHECK(json_valid(envelope_json) AND json_type(envelope_json) = 'object')
) STRICT;

CREATE TABLE collector_run_sources (
    run_id TEXT NOT NULL REFERENCES collector_runs(run_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    outcome TEXT NOT NULL CHECK(outcome IN ('updated', 'unchanged', 'empty', 'partial', 'failed')),
    failure_reason TEXT,
    PRIMARY KEY(run_id, source_id)
) STRICT;

CREATE TABLE observations (
    observation_id INTEGER PRIMARY KEY,
    series_id TEXT NOT NULL,
    definition_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    unit TEXT NOT NULL,
    frequency TEXT NOT NULL,
    basis TEXT NOT NULL,
    storage_kind TEXT NOT NULL DEFAULT 'direct' CHECK(storage_kind = 'direct'),
    period_id TEXT NOT NULL,
    period_label TEXT NOT NULL CHECK(length(trim(period_label)) > 0),
    period_start TEXT NOT NULL CHECK(length(period_start) = 10 AND date(period_start, '+0 days') IS period_start),
    period_end TEXT NOT NULL CHECK(length(period_end) = 10 AND date(period_end, '+0 days') IS period_end AND period_end >= period_start),
    -- ANY in a STRICT table forbids implicit numeric-to-TEXT conversion here.
    value_decimal ANY CHECK(value_decimal IS NULL OR (
        typeof(value_decimal) = 'text' AND length(value_decimal) BETWEEN 1 AND 58
        AND instr(value_decimal, char(0)) = 0
        AND value_decimal NOT GLOB '*[^0-9.-]*'
        AND value_decimal NOT IN ('', '-', '.', '-.')
        AND instr(substr(value_decimal, 2), '-') = 0
        AND length(value_decimal) - length(replace(value_decimal, '.', '')) <= 1
        AND substr(value_decimal, -1) != '.' AND substr(ltrim(value_decimal, '-'), 1, 1) != '.'
        AND (substr(ltrim(value_decimal, '-'), 1, 1) != '0' OR length(ltrim(value_decimal, '-')) = 1 OR substr(ltrim(value_decimal, '-'), 2, 1) = '.')
        AND length(replace(replace(value_decimal, '-', ''), '.', '')) <= 38
        AND (instr(value_decimal, '.') = 0 OR length(value_decimal) - instr(value_decimal, '.') <= 18)
    )),
    quality_status TEXT NOT NULL CHECK(quality_status IN ('valid', 'missing')),
    reason_code TEXT,
    as_of TEXT NOT NULL,
    as_of_precision TEXT NOT NULL CHECK(as_of_precision IN ('year', 'month')),
    as_of_kind TEXT NOT NULL DEFAULT 'period_end' CHECK(as_of_kind = 'period_end'),
    published_at TEXT CHECK(published_at IS NULL OR (length(published_at) = 27 AND published_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(published_at) IS NOT NULL)),
    publication_precision TEXT CHECK(publication_precision = 'minute'),
    publication_timezone TEXT,
    retrieved_at TEXT NOT NULL CHECK(length(retrieved_at) = 27 AND retrieved_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(retrieved_at) IS NOT NULL),
    revision_kind TEXT NOT NULL CHECK(revision_kind IN ('published', 'provisional', 'first_revised', 'final', 'provisional_actual')),
    vintage_id TEXT NOT NULL CHECK(length(trim(vintage_id)) > 0),
    parser_version TEXT NOT NULL CHECK(length(trim(parser_version)) > 0),
    source_unit TEXT NOT NULL CHECK(length(trim(source_unit)) > 0),
    normalization_id TEXT NOT NULL CHECK(length(trim(normalization_id)) > 0),
    dataset_updated_at TEXT CHECK(dataset_updated_at IS NULL OR (length(dataset_updated_at) = 10 AND date(dataset_updated_at, '+0 days') IS dataset_updated_at)),
    first_run_id TEXT NOT NULL,
    FOREIGN KEY(series_id, definition_id, source_id, unit, frequency, basis, storage_kind)
        REFERENCES series(series_id, definition_id, source_id, unit, frequency, basis, storage_kind),
    FOREIGN KEY(first_run_id, source_id) REFERENCES collector_run_sources(run_id, source_id),
    UNIQUE(series_id, definition_id, period_id, vintage_id, parser_version),
    UNIQUE(observation_id, source_id),
    CHECK((value_decimal IS NULL AND quality_status = 'missing' AND reason_code IS 'source_value_missing') OR
          (value_decimal IS NOT NULL AND quality_status = 'valid' AND reason_code IS NULL)),
    CHECK(period_end = date(period_end, 'start of month', '+1 month', '-1 day')),
    CHECK((frequency = 'annual' AND basis = 'calendar' AND period_start = substr(period_end, 1, 4) || '-01-01' AND substr(period_end, 6) = '12-31' AND period_id = 'CY' || substr(period_end, 1, 4)) OR
          (frequency = 'annual' AND basis = 'fiscal' AND period_start = date(period_end, '-1 year', 'start of year', '+3 months') AND substr(period_end, 6) = '03-31' AND period_id = 'FY' || substr(period_start, 1, 4) || '-' || substr(period_end, 3, 2)) OR
          (frequency = 'monthly' AND basis = 'calendar' AND period_start = date(period_end, 'start of month') AND period_id = substr(period_end, 1, 7)) OR
          (frequency = 'monthly_cumulative' AND basis = 'fiscal' AND substr(period_start, 6) = '04-01' AND period_end < date(period_start, '+1 year') AND period_id = 'FY' || substr(period_start, 1, 4) || '-' || substr(date(period_start, '+1 year'), 3, 2) || ':' || substr(period_end, 1, 7))),
    CHECK((frequency = 'annual' AND as_of_precision = 'year' AND as_of = substr(period_end, 1, 4)) OR
          (frequency != 'annual' AND as_of_precision = 'month' AND as_of = substr(period_end, 1, 7))),
    CHECK(period_end <= substr(retrieved_at, 1, 10)),
    CHECK((published_at IS NULL AND publication_timezone IS NULL AND publication_precision IS NULL) OR
          (published_at IS NOT NULL AND publication_timezone IS NOT NULL AND publication_precision IS NOT NULL AND published_at <= retrieved_at AND substr(published_at, 1, 10) >= period_end)),
    CHECK(dataset_updated_at IS NULL OR dataset_updated_at <= substr(retrieved_at, 1, 10))
) STRICT;

CREATE TABLE observation_sources (
    observation_id INTEGER NOT NULL REFERENCES observations(observation_id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    url TEXT NOT NULL CHECK(url LIKE 'https://%'),
    is_nse INTEGER NOT NULL CHECK(is_nse IN (0, 1)),
    PRIMARY KEY(observation_id, ordinal),
    UNIQUE(observation_id, source_id)
) STRICT;

-- A bounded, normalized envelope in collector_runs carries body-free resource validators.
CREATE TABLE repository_checkpoint (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    run_id TEXT NOT NULL UNIQUE REFERENCES collector_runs(run_id)
) STRICT;

CREATE TABLE source_states (
    source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
    run_id TEXT,
    outcome TEXT NOT NULL CHECK(outcome IN ('never_observed', 'updated', 'unchanged', 'empty', 'partial', 'failed')),
    last_attempt_at TEXT,
    last_checked_at TEXT,
    last_success_at TEXT,
    last_changed_at TEXT,
    last_failure_at TEXT,
    failure_reason TEXT,
    FOREIGN KEY(run_id, source_id) REFERENCES collector_run_sources(run_id, source_id),
    CHECK(last_attempt_at IS NULL OR (length(last_attempt_at) = 27 AND last_attempt_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(last_attempt_at) IS NOT NULL)),
    CHECK(last_checked_at IS NULL OR (length(last_checked_at) = 27 AND last_checked_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(last_checked_at) IS NOT NULL)),
    CHECK(last_success_at IS NULL OR (length(last_success_at) = 27 AND last_success_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(last_success_at) IS NOT NULL)),
    CHECK(last_changed_at IS NULL OR (length(last_changed_at) = 27 AND last_changed_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(last_changed_at) IS NOT NULL)),
    CHECK(last_failure_at IS NULL OR (length(last_failure_at) = 27 AND last_failure_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(last_failure_at) IS NOT NULL)),
    CHECK(last_attempt_at IS NULL OR (last_checked_at IS NOT NULL AND last_attempt_at <= last_checked_at)),
    CHECK(last_success_at IS NULL OR (last_checked_at IS NOT NULL AND last_success_at <= last_checked_at)),
    CHECK(last_changed_at IS NULL OR (last_checked_at IS NOT NULL AND last_changed_at <= last_checked_at)),
    CHECK(last_failure_at IS NULL OR (last_checked_at IS NOT NULL AND last_failure_at <= last_checked_at)),
    CHECK(outcome != 'never_observed' OR (run_id IS NULL AND last_attempt_at IS NULL AND last_checked_at IS NULL AND last_success_at IS NULL AND last_changed_at IS NULL AND last_failure_at IS NULL AND failure_reason IS NULL)),
    CHECK(outcome = 'never_observed' OR (run_id IS NOT NULL AND last_attempt_at IS NOT NULL AND last_checked_at IS NOT NULL))
) STRICT;

CREATE INDEX observations_history ON observations(series_id, definition_id, period_end DESC, published_at DESC, dataset_updated_at DESC);
CREATE INDEX observations_source_run ON observations(first_run_id, source_id);
CREATE INDEX observation_sources_source ON observation_sources(source_id);
CREATE INDEX series_indicator ON series(indicator_id, series_id);
CREATE INDEX series_source ON series(source_id);
CREATE INDEX requirement_bindings_source ON requirement_bindings(source_id);
CREATE INDEX collector_runs_finished ON collector_runs(finished_at DESC, run_id);
CREATE INDEX collector_run_sources_source ON collector_run_sources(source_id, run_id);
