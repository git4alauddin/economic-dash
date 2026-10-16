"""M3 merge repository: parameterized SQL, archival observations, bounded reload."""

from datetime import datetime, timezone
import json
from app.sqlite_runtime import sqlite3

from app.database import Database
from app.collectors.catalog import CATALOG_PATH
from app.collectors.handoff import CollectionEnvelope, CommitAcknowledgement, StoredCheckpoint
from app.collectors.history import _resolve
from app.collectors.observations import NormalizedObservation
from app.collectors.snapshot_cache import _bounded

REPOSITORY_VERSION = "sqlite-m4-v1"


class RepositoryConflict(ValueError):
    """A stale writer or contradictory immutable identity; no writes committed."""


def utc(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z") if value else None


def semantic(point: NormalizedObservation) -> dict:
    # A second fetch cannot change the publisher's immutable vintage. Keep its
    # first retrieval time in the archive; later checks live in run/checkpoint state.
    return point.model_dump(mode="json", exclude={"retrieved_at"})


def observation_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> NormalizedObservation:
    sources = tuple(dict(source_id=s["source_id"], name=s["name"], url=s["url"], is_nse=bool(s["is_nse"]))
                    for s in connection.execute("SELECT source_id,name,url,is_nse FROM observation_sources WHERE observation_id=? ORDER BY ordinal", (row["observation_id"],)))
    fields = ("series_id", "definition_id", "unit", "as_of", "as_of_precision", "as_of_kind", "published_at",
              "publication_precision", "publication_timezone", "retrieved_at", "quality_status", "reason_code",
              "revision_kind", "vintage_id", "parser_version", "source_unit", "normalization_id", "dataset_updated_at")
    data = {field: row[field] for field in fields}
    series = connection.execute("SELECT indicator_id FROM series WHERE series_id=? AND definition_id=?", (row["series_id"], row["definition_id"])).fetchone()
    data.update(indicator_id=series[0], value=row["value_decimal"], sources=sources,
                observation_period=dict(id=row["period_id"], label=row["period_label"], basis=row["basis"],
                                        frequency=row["frequency"], start=row["period_start"], end=row["period_end"]))
    return NormalizedObservation.model_validate_json(json.dumps(data))


class SQLiteCollectionRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _points(item):
        # Resources may contain accepted history older than the RAM window.
        # Archive those too; checkpoint bounds must never become SQL deletion.
        points = {}
        for point in item.observations + tuple(p for r in item.resources for p in r.batch.observations):
            points.setdefault((point.series_id, point.definition_id, point.observation_period.id, point.vintage_id, point.parser_version), point)
        return tuple(points.values())

    def _load(self, connection: sqlite3.Connection) -> StoredCheckpoint | None:
        row = connection.execute("""SELECT r.* FROM repository_checkpoint p
            JOIN collector_runs r ON r.run_id=p.run_id WHERE p.singleton=1""").fetchone()
        if row is None:
            if connection.execute("SELECT 1 FROM collector_runs LIMIT 1").fetchone():
                raise RepositoryConflict("Committed runs exist without a checkpoint.")
            return None
        envelope = CollectionEnvelope.model_validate_json(row["envelope_json"])
        acknowledgement = CommitAcknowledgement(run_id=row["run_id"], envelope_digest=row["envelope_digest"], repository_version=row["repository_version"])
        checkpoint = StoredCheckpoint(envelope=envelope, acknowledgement=acknowledgement)
        if (row["repository_version"], row["catalog_fingerprint"], row["contract_version"], row["started_at"], row["finished_at"], row["trigger"], row["observation_count"]) != (
            REPOSITORY_VERSION, envelope.catalog_fingerprint, envelope.contract_version, utc(envelope.started_at), utc(envelope.finished_at), envelope.trigger, len(envelope.observations)):
            raise RepositoryConflict("Stored run metadata differs from its checkpoint.")
        for point in self._points(envelope):
            stored = self._find_observation(connection, point)
            if stored is None or semantic(observation_from_row(connection, stored)) != semantic(point):
                raise RepositoryConflict("Checkpoint observation differs from its SQL archive.")
        for state in envelope.source_states:
            stored = connection.execute("SELECT * FROM source_states WHERE source_id=?", (state.source_id,)).fetchone()
            expected = self._state_values(state)
            if stored is None or tuple(stored) != expected:
                raise RepositoryConflict("Checkpoint source state differs from SQL state.")
        return checkpoint

    def load(self) -> StoredCheckpoint | None:
        with self.database.connection(read_only=True) as connection:
            connection.execute("BEGIN")  # One consistent read snapshot, closed/rolled back on exit.
            return self._load(connection)

    @staticmethod
    def _find_observation(connection, point):
        return connection.execute("""SELECT * FROM observations WHERE series_id=? AND definition_id=?
            AND period_id=? AND vintage_id=? AND parser_version=?""",
            (point.series_id, point.definition_id, point.observation_period.id, point.vintage_id, point.parser_version)).fetchone()

    @staticmethod
    def _continuity(previous: CollectionEnvelope | None, item: CollectionEnvelope) -> None:
        old_states = {s.source_id: s for s in previous.source_states} if previous else {}
        old_resources = {r.resource_id: r for r in previous.resources} if previous else {}
        if any(s.source_id not in item.source_ids and old_states.get(s.source_id) != s for s in item.source_states):
            raise RepositoryConflict("Unscoped source state requires an existing matching checkpoint.")
        if any(r.batch.source_id not in item.source_ids and old_resources.get(r.resource_id) != r for r in item.resources):
            raise RepositoryConflict("Unscoped resources require an existing matching checkpoint.")
        if previous is None:
            return
        if item.finished_at < previous.finished_at:
            raise RepositoryConflict("Checkpoint time cannot regress.")
        states = {s.source_id: s for s in item.source_states}
        for old in previous.source_states:
            current = states.get(old.source_id)
            if current is None or (old.source_id not in item.source_ids and current != old):
                raise RepositoryConflict("A stale writer omitted or changed another source's state.")
            for field in ("last_checked_at", "last_success_at", "last_changed_at", "last_failure_at"):
                before, after = getattr(old, field), getattr(current, field)
                if before is not None and (after is None or after < before):
                    raise RepositoryConflict("Source event timestamps cannot regress.")
        resources = {r.resource_id: r for r in item.resources}
        for old in previous.resources:
            current = resources.get(old.resource_id)
            if old.batch.source_id not in item.source_ids and current != old:
                raise RepositoryConflict("A stale writer changed another source's resource.")
            if current is not None and current.checked_at < old.checked_at:
                raise RepositoryConflict("Resource checks cannot regress.")
            if current is None and sum(r.batch.source_id == old.batch.source_id for r in item.resources) < 32:
                raise RepositoryConflict("Accepted resources may only be evicted at the cache bound.")
        merged = _bounded(previous.observations + item.observations)
        tokens = lambda points: {json.dumps(semantic(p), sort_keys=True) for p in points}
        if tokens(merged) != tokens(item.observations):
            raise RepositoryConflict("Checkpoint omitted retained observations before the cache bound.")

    @staticmethod
    def _catalog(connection):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        inventory = json.loads((CATALOG_PATH.parent / "indicator-requirements.json").read_text(encoding="utf-8"))
        publishers = inventory["publishers"]
        for source_id, source in sorted(catalog["sources"].items()):
            publisher = publishers[source["publisher_id"]]
            limitations = json.dumps([source["limits"], catalog["reuse"][source["reuse_id"]]["constraint"]])
            resources = [(source_id, source["url"])]
            if "metadata_url" in source:
                resources.append((source_id + ".metadata", source["metadata_url"]))
            for identifier, url in resources:
                expected = (identifier, publisher["name"], publisher["name"], url, int(publisher["is_nse"]), limitations)
                connection.execute("INSERT INTO sources(source_id,name,provider,url,is_nse,limitations_json) VALUES (?,?,?,?,?,?) ON CONFLICT(source_id) DO NOTHING",
                                   expected)
                if tuple(connection.execute("SELECT source_id,name,provider,url,is_nse,limitations_json FROM sources WHERE source_id=?", (identifier,)).fetchone()) != expected:
                    raise RepositoryConflict("SQL source catalog differs from the frozen source definition.")
        bindings = {s["id"]: panel["indicator_id"] for panel in inventory["panels"] for s in panel["series"]}
        bindings.update({s["instrument_id"]: "market_ticker" for s in inventory["ticker"]["instruments"]})
        bindings.update({s["id"]: s["indicator_id"] for s in inventory["unbound_requirements"]})
        for indicator in sorted(set(bindings.values())):
            connection.execute("INSERT INTO indicators(indicator_id,name) VALUES (?,?) ON CONFLICT(indicator_id) DO NOTHING", (indicator, indicator.replace("_", " ").title()))
        for requirement, definition in sorted(catalog["requirements"].items()):
            if definition["definition_id"] is not None:
                expected = (requirement, definition["definition_id"], bindings[requirement], definition["source_id"], definition["definition"], definition["unit"], definition["frequency"], definition["basis"],
                            {"selected": "direct", "derived": "derived", "blocked": "blocked"}[definition["status"]])
                connection.execute("""INSERT INTO series(series_id,definition_id,indicator_id,source_id,definition,unit,frequency,basis,storage_kind)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id,definition_id) DO NOTHING""", expected)
                if tuple(connection.execute("SELECT series_id,definition_id,indicator_id,source_id,definition,unit,frequency,basis,storage_kind FROM series WHERE series_id=? AND definition_id=?", (requirement, definition["definition_id"])).fetchone()) != expected:
                    raise RepositoryConflict("SQL series differs from the frozen definition.")
            expected = (requirement, definition["source_id"], definition["definition_id"], definition["status"], definition["unit"], definition["frequency"], definition["basis"], definition.get("reason_code"), definition.get("transform_id"), json.dumps(definition.get("inputs", [])))
            connection.execute("""INSERT INTO requirement_bindings(requirement_id,source_id,definition_id,status,unit,frequency,basis,reason_code,transform_id,inputs_json)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(requirement_id) DO NOTHING""", expected)
            if tuple(connection.execute("SELECT requirement_id,source_id,definition_id,status,unit,frequency,basis,reason_code,transform_id,inputs_json FROM requirement_bindings WHERE requirement_id=?", (requirement,)).fetchone()) != expected:
                raise RepositoryConflict("SQL requirement binding differs from the frozen definition.")

    def _observation(self, connection, point, item):
        old = self._find_observation(connection, point)
        if old is not None:
            if semantic(observation_from_row(connection, old)) != semantic(point):
                raise RepositoryConflict("Observation vintage conflicts with its immutable SQL record.")
            return
        if point.sources[0].source_id not in item.source_ids or not any(
            semantic(point) == semantic(candidate) for resource in item.resources if resource.batch.source_id in item.source_ids
            for candidate in resource.batch.observations):
            raise RepositoryConflict("New observations require an accepted resource in the run scope.")
        existing = [observation_from_row(connection, row) for row in connection.execute(
            "SELECT * FROM observations WHERE series_id=? AND definition_id=? AND period_id=?",
            (point.series_id, point.definition_id, point.observation_period.id))]
        if (point.value is None and any(p.value is not None for p in existing)) or _resolve(existing + [point])[2]:
            raise RepositoryConflict("A conflicting, missing or regressed revision cannot replace valid history.")
        period = point.observation_period
        cursor = connection.execute("""INSERT INTO observations(
            series_id,definition_id,source_id,unit,frequency,basis,period_id,period_label,period_start,period_end,value_decimal,
            quality_status,reason_code,as_of,as_of_precision,as_of_kind,published_at,publication_precision,publication_timezone,
            retrieved_at,revision_kind,vintage_id,parser_version,source_unit,normalization_id,dataset_updated_at,first_run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (point.series_id, point.definition_id, point.sources[0].source_id, point.unit, period.frequency, period.basis,
             period.id, period.label, period.start.isoformat(), period.end.isoformat(), format(point.value, "f") if point.value is not None else None,
             point.quality_status, point.reason_code, point.as_of, point.as_of_precision, point.as_of_kind, utc(point.published_at),
             point.publication_precision, point.publication_timezone, utc(point.retrieved_at), point.revision_kind, point.vintage_id,
             point.parser_version, point.source_unit, point.normalization_id,
             point.dataset_updated_at.isoformat() if point.dataset_updated_at else None, item.run_id))
        for ordinal, reference in enumerate(point.sources):
            connection.execute("INSERT INTO observation_sources(observation_id,ordinal,source_id,name,url,is_nse) VALUES (?,?,?,?,?,?)",
                               (cursor.lastrowid, ordinal, reference.source_id, reference.name, reference.url, int(reference.is_nse)))

    @staticmethod
    def _state_values(state):
        return (state.source_id, state.run_id, state.outcome, utc(state.last_attempt_at), utc(state.last_checked_at),
                utc(state.last_success_at), utc(state.last_changed_at), utc(state.last_failure_at), state.failure_reason)

    def _write_states(self, connection, item):
        for state in item.source_states:
            if state.source_id in item.source_ids:
                connection.execute("""INSERT INTO source_states(source_id,run_id,outcome,last_attempt_at,last_checked_at,last_success_at,last_changed_at,last_failure_at,failure_reason)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                    run_id=excluded.run_id,outcome=excluded.outcome,last_attempt_at=excluded.last_attempt_at,last_checked_at=excluded.last_checked_at,
                    last_success_at=excluded.last_success_at,last_changed_at=excluded.last_changed_at,last_failure_at=excluded.last_failure_at,failure_reason=excluded.failure_reason""", self._state_values(state))

    def commit(self, envelope: CollectionEnvelope) -> CommitAcknowledgement:
        if not isinstance(envelope, CollectionEnvelope):
            raise TypeError("A validated collection envelope is required.")
        # Revalidate constructed/copied models too; strict JSON rejects floats and raw bodies.
        item = CollectionEnvelope.model_validate_json(envelope.model_dump_json())
        acknowledgement = CommitAcknowledgement(run_id=item.run_id, envelope_digest=item.digest, repository_version=REPOSITORY_VERSION)
        with self.database.transaction() as connection:
            old = connection.execute("SELECT envelope_digest,repository_version FROM collector_runs WHERE run_id=?", (item.run_id,)).fetchone()
            if old is not None:
                if (old[0], old[1]) != (item.digest, REPOSITORY_VERSION):
                    raise RepositoryConflict("Run ID was already committed with different content.")
                return acknowledgement  # Never move the checkpoint backward on a retry.
            previous = self._load(connection)
            self._continuity(previous.envelope if previous else None, item)
            self._catalog(connection)
            states = [s for s in item.source_states if s.source_id in item.source_ids]
            reasons = {s.failure_reason for s in states}
            status = ("cancelled" if "collection_cancelled" in reasons else "timeout" if "collection_deadline_exceeded" in reasons else
                      "failed" if all(s.outcome == "failed" for s in states) else
                      "partial" if any(f.source_id in item.source_ids for f in item.failures) else
                      "unchanged" if all(s.outcome == "unchanged" for s in states) else "prepared")
            connection.execute("""INSERT INTO collector_runs(run_id,envelope_digest,catalog_fingerprint,contract_version,repository_version,trigger,started_at,finished_at,status,observation_count,envelope_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (item.run_id, item.digest, item.catalog_fingerprint, item.contract_version, REPOSITORY_VERSION, item.trigger, utc(item.started_at), utc(item.finished_at), status, len(item.observations), item.model_dump_json()))
            for state in states:
                connection.execute("INSERT INTO collector_run_sources(run_id,source_id,outcome,failure_reason) VALUES (?,?,?,?)", (item.run_id, state.source_id, state.outcome, state.failure_reason))
            for point in self._points(item):
                self._observation(connection, point, item)
            self._write_states(connection, item)
            connection.execute("INSERT INTO repository_checkpoint(singleton,run_id) VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET run_id=excluded.run_id", (item.run_id,))
            self._load(connection)  # Verify the complete SQL/checkpoint projection before COMMIT.
        return acknowledgement  # Context exited: durable COMMIT succeeded before ACK.
