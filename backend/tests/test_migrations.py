"""Real schema constraints and atomic upgrades; no collector repository implemented here."""

from contextlib import closing
from datetime import timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.collectors.handoff import catalog_fingerprint, requirement_bindings
from app.collectors.normalization import SourceNormalizer
from app.config import DatabaseSettings
from app.database import Database
from app.migrations import SCHEMA_VERSION, Migration, migration_plan, migrate, statements
from test_normalization import cpi, expenditure, gdp, trade, wb


def instant(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z") if value else None


def insert(connection, table, values):
    # Table/column names below are test-owned constants; values are always bound.
    return connection.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


def observation_values(point):
    period = point.observation_period
    return dict(series_id=point.series_id, definition_id=point.definition_id, source_id=point.sources[0].source_id,
                unit=point.unit, frequency=period.frequency, basis=period.basis, period_id=period.id,
                period_label=period.label, period_start=period.start.isoformat(), period_end=period.end.isoformat(),
                value_decimal=format(point.value, "f") if point.value is not None else None,
                quality_status=point.quality_status, reason_code=point.reason_code, as_of=point.as_of,
                as_of_precision=point.as_of_precision, published_at=instant(point.published_at),
                publication_precision=point.publication_precision, publication_timezone=point.publication_timezone,
                retrieved_at=instant(point.retrieved_at), revision_kind=point.revision_kind, vintage_id=point.vintage_id,
                parser_version=point.parser_version, source_unit=point.source_unit, normalization_id=point.normalization_id,
                dataset_updated_at=point.dataset_updated_at.isoformat() if point.dataset_updated_at else None,
                first_run_id="test-run")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Database(DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db"))
        self.database.bootstrap()

    def populate_catalog(self, connection):
        normalizer = SourceNormalizer()
        points = tuple(p for factory in (wb, gdp, trade, cpi, expenditure)
                       for p in normalizer.parse(factory()).observations if p.transform_id is None)
        bindings = requirement_bindings()
        source_ids = {b.source_id for b in bindings} | {s.source_id for p in points for s in p.sources}
        for source_id in sorted(source_ids):
            insert(connection, "sources", dict(source_id=source_id, name=source_id, provider="synthetic test metadata",
                                               url="https://example.com/source", is_nse=0))
        for indicator_id in sorted({p.indicator_id for p in points} | {"unbound_test"}):
            insert(connection, "indicators", dict(indicator_id=indicator_id, name=indicator_id))
        by_series = {p.series_id: p for p in points}
        for binding in bindings:
            if binding.definition_id is not None:
                insert(connection, "series", dict(series_id=binding.requirement_id, definition_id=binding.definition_id,
                    indicator_id=by_series[binding.requirement_id].indicator_id if binding.requirement_id in by_series else "unbound_test",
                    source_id=binding.source_id, definition="Synthetic schema test definition", unit=binding.unit,
                    frequency=binding.frequency, basis=binding.basis,
                    storage_kind={"selected": "direct", "derived": "derived", "blocked": "blocked"}[binding.status]))
            insert(connection, "requirement_bindings", dict(requirement_id=binding.requirement_id,
                source_id=binding.source_id, definition_id=binding.definition_id, status=binding.status, unit=binding.unit,
                frequency=binding.frequency, basis=binding.basis, reason_code=binding.reason_code,
                transform_id=binding.transform_id, inputs_json=json.dumps(binding.inputs)))
        timestamp = "2026-10-16T12:00:00.000000Z"
        insert(connection, "collector_runs", dict(run_id="test-run", envelope_digest="sha256:" + "a" * 64,
            catalog_fingerprint=catalog_fingerprint(), contract_version="m3-m4-ingest-v1", repository_version="test-v1",
            trigger="test", started_at=timestamp, finished_at=timestamp, status="prepared",
            observation_count=len(points), envelope_json='{"test_only":true}'))
        for source_id in sorted({p.sources[0].source_id for p in points}):
            insert(connection, "collector_run_sources", dict(run_id="test-run", source_id=source_id, outcome="updated"))
        return points

    def test_fresh_and_version_zero_upgrade_reproduce_schema_without_erasing_data(self):
        with self.database.connection() as connection:
            schema = [tuple(r) for r in connection.execute("SELECT type, name, sql FROM sqlite_schema ORDER BY type, name")]
        other = Database(DatabaseSettings(_env_file=None, directory=self.database.settings.directory / "version-zero"))
        other.settings.directory.mkdir()
        with closing(sqlite3.connect(other.settings.path)) as connection, connection:
            connection.execute("CREATE TABLE retained_probe(value TEXT)")
            connection.execute("INSERT INTO retained_probe VALUES (?)", ("pre-migration",))
        other.bootstrap()
        other.bootstrap()
        with other.connection() as connection:
            upgraded = [tuple(r) for r in connection.execute("SELECT type, name, sql FROM sqlite_schema WHERE name != 'retained_probe' ORDER BY type, name")]
            self.assertEqual(upgraded, schema)
            self.assertEqual(connection.execute("SELECT value FROM retained_probe").fetchone()[0], "pre-migration")
            self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_all_m3_definitions_periods_and_multiple_source_references_fit_schema(self):
        with self.database.transaction() as connection:
            points = self.populate_catalog(connection)
            for point in points:
                identifier = insert(connection, "observations", observation_values(point)).lastrowid
                for ordinal, source in enumerate(point.sources):
                    insert(connection, "observation_sources", dict(observation_id=identifier, ordinal=ordinal,
                        source_id=source.source_id, name=source.name, url=source.url, is_nse=int(source.is_nse)))
            self.assertEqual(connection.execute("SELECT count(*) FROM requirement_bindings").fetchone()[0], 17)
            self.assertEqual(connection.execute("SELECT count(*) FROM requirement_bindings WHERE status='blocked'").fetchone()[0], 8)
            self.assertEqual(connection.execute("SELECT definition_id FROM requirement_bindings WHERE requirement_id='debt_india_us_comparison'").fetchone()[0], None)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT value_decimal FROM observations WHERE series_id='gdp_growth_world'").fetchone()[0], "2.123456789012345678")
            self.assertEqual(connection.execute("SELECT count(*) FROM observation_sources WHERE observation_id=(SELECT observation_id FROM observations WHERE series_id='gdp_growth_world')").fetchone()[0], 2)
        self.database.bootstrap()

    def test_duplicate_vintage_rejects_conflict_but_new_revision_preserves_old_value(self):
        with self.database.transaction() as connection:
            point = self.populate_catalog(connection)[0]
            values = observation_values(point)
            insert(connection, "observations", values)
            for changes in ({}, {"value_decimal": "3"}):
                with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                    insert(connection, "observations", values | changes)
            insert(connection, "observations", values | {"vintage_id": "reviewed-new-vintage", "value_decimal": "3"})
            self.assertEqual(connection.execute("SELECT count(*) FROM observations").fetchone()[0], 2)

    def test_exact_text_zero_null_and_invalid_numeric_tokens(self):
        with self.database.transaction() as connection:
            values = observation_values(self.populate_catalog(connection)[0])
            for index, value in enumerate(("0", "-0.00", "12345678901234567890.123456789012345678", None)):
                changes = dict(value_decimal=value, vintage_id=f"test-{index}", quality_status="missing" if value is None else "valid",
                               reason_code="source_value_missing" if value is None else None)
                insert(connection, "observations", values | changes)
            self.assertEqual([r[0] for r in connection.execute("SELECT value_decimal FROM observations ORDER BY observation_id")],
                             ["0", "-0.00", "12345678901234567890.123456789012345678", None])
            for value in (0, 1.25, True, float("inf"), "NaN", "Infinity", "+1", "01", "1e2", "--1", "1.", ".2", "1.2.3", "1\x00junk", "1,000", "1" * 39, "0." + "1" * 19):
                with self.subTest(value=repr(value)), self.assertRaises(sqlite3.IntegrityError):
                    insert(connection, "observations", values | {"value_decimal": value, "vintage_id": "bad-token"})

    def test_foreign_keys_quality_period_units_and_time_constraints(self):
        with self.database.transaction() as connection:
            values = observation_values(self.populate_catalog(connection)[0])
            for changes in (
                {"source_id": "unknown"}, {"first_run_id": "unknown"}, {"definition_id": "unknown"}, {"unit": "inr_crore"},
                {"value_decimal": None}, {"reason_code": "invented"}, {"quality_status": "missing"},
                {"basis": "fiscal"}, {"period_id": "FY2024-25"}, {"period_end": "2025-02-30"},
                {"period_start": "2024-01-01"}, {"as_of": "2025-12"}, {"as_of_precision": "month"},
                {"retrieved_at": "2024-10-16T12:00:00.000000Z"}, {"retrieved_at": "2026-10-16T12:00:00.000000+01:00"},
                {"published_at": "2026-10-16T12:00:00.000000Z"},
                {"dataset_updated_at": "2026-11-01"}, {"storage_kind": "derived"},
            ):
                with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                    insert(connection, "observations", values | changes)
            identifier = insert(connection, "observations", values).lastrowid
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM sources WHERE source_id=?", (values["source_id"],))
            with self.assertRaises(sqlite3.IntegrityError):
                insert(connection, "observation_sources", dict(observation_id=identifier, ordinal=0, source_id="unknown",
                    name="unknown", url="https://example.com", is_nse=0))
            for series_id in ("trade_balance", "gst_total"):
                record = connection.execute("SELECT * FROM series WHERE series_id=?", (series_id,)).fetchone()
                with self.subTest(series_id=series_id), self.assertRaises(sqlite3.IntegrityError):
                    insert(connection, "observations", values | {key: record[key] for key in ("series_id", "definition_id", "source_id", "unit", "frequency", "basis")})

    def test_partial_source_state_preserves_m3_change_and_check_semantics(self):
        with self.database.transaction() as connection:
            self.populate_catalog(connection)
            # A historical resource can change while the current-source check fails.
            insert(connection, "source_states", dict(source_id="world_bank_gdp", run_id="test-run", outcome="partial",
                last_attempt_at="2026-10-16T12:00:00.000000Z", last_checked_at="2026-10-16T12:00:00.000000Z",
                last_changed_at="2026-10-16T12:00:00.000000Z", last_success_at=None, failure_reason=None))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE source_states SET last_success_at=?", ("2026-10-17T12:00:00.000000Z",))
            insert(connection, "repository_checkpoint", dict(singleton=1, run_id="test-run"))
            with self.assertRaises(sqlite3.IntegrityError):
                insert(connection, "repository_checkpoint", dict(singleton=2, run_id="test-run"))

    def test_failed_upgrade_rolls_back_ddl_data_ledger_and_version(self):
        with self.database.transaction() as connection:
            self.populate_catalog(connection)
        failing = Migration(SCHEMA_VERSION + 1, "broken", "CREATE TABLE upgrade_probe(id INTEGER); INSERT INTO indicators VALUES ('probe','probe'); INSERT INTO missing_table VALUES (1);")
        with patch("app.migrations.SCHEMA_VERSION", SCHEMA_VERSION + 1), patch("app.migrations.migration_plan", return_value=migration_plan() + (failing,)):
            with self.database.connection() as connection, self.assertRaises(sqlite3.OperationalError):
                migrate(connection)
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_schema WHERE name='upgrade_probe'").fetchone())
            self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNone(connection.execute("SELECT 1 FROM indicators WHERE indicator_id='probe'").fetchone())
            self.assertEqual(connection.execute("SELECT count(*) FROM requirement_bindings").fetchone()[0], 17)
        self.database.bootstrap()

    def test_applied_migration_checksum_and_missing_ledger_fail_closed(self):
        original = migration_plan()[0]
        modified = Migration(1, original.name, original.sql + "\n-- edited after application\n")
        with patch("app.migrations.migration_plan", return_value=(modified,) + migration_plan()[1:]):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                self.database.bootstrap()
        with self.database.connection() as connection:
            connection.execute("DROP TABLE schema_migrations")
        with self.assertRaisesRegex(RuntimeError, "ledger is missing"):
            self.database.bootstrap()

    def test_successful_forward_upgrade_commits_once_and_preserves_rows(self):
        with self.database.transaction() as connection:
            self.populate_catalog(connection)
        following = Migration(SCHEMA_VERSION + 1, "forward_probe", "CREATE TABLE forward_probe(id INTEGER PRIMARY KEY) STRICT; INSERT INTO forward_probe VALUES (1);")
        plan = migration_plan() + (following,)
        with patch("app.migrations.SCHEMA_VERSION", SCHEMA_VERSION + 1), patch("app.migrations.migration_plan", return_value=plan):
            with self.database.connection() as connection:
                migrate(connection)
                migrate(connection)
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION + 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM forward_probe").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], SCHEMA_VERSION + 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM requirement_bindings").fetchone()[0], 17)

    def test_failed_first_install_leaves_no_schema_or_migration_ledger(self):
        other = Database(DatabaseSettings(_env_file=None, directory=self.database.settings.directory / "failed-install"))
        broken = Migration(1, "broken_first", "CREATE TABLE partial_schema(id INTEGER); INSERT INTO nonexistent VALUES (1);")
        with patch("app.migrations.SCHEMA_VERSION", 1), patch("app.migrations.migration_plan", return_value=(broken,)):
            with self.assertRaises(sqlite3.OperationalError):
                other.bootstrap()
        with other.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall(), [])
        other.bootstrap()

    def test_migration_parser_handles_comments_strings_triggers_and_line_endings(self):
        script = "CREATE TABLE parser_probe(value TEXT); INSERT INTO parser_probe VALUES ('a;b');\nCREATE TRIGGER parser_trigger AFTER INSERT ON parser_probe BEGIN SELECT 'x;y'; SELECT 1; END;\n-- tail comment\n"
        with self.database.transaction() as connection:
            for statement in statements(script):
                connection.execute(statement)
            self.assertEqual(connection.execute("SELECT value FROM parser_probe").fetchone()[0], "a;b")
        self.assertEqual(Migration(1, "test", "SELECT 1;\n").checksum, Migration(1, "test", "SELECT 1;\r\n").checksum)
        with self.assertRaisesRegex(RuntimeError, "semicolon"):
            list(statements("CREATE TABLE unclosed(id INTEGER)"))

    def test_domain_indices_and_strict_tables_exist(self):
        with self.database.connection() as connection:
            for name in ("observations_history", "observations_source_run", "series_indicator", "collector_runs_finished"):
                self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_schema WHERE type='index' AND name=?", (name,)).fetchone())
            tables = list(connection.execute("PRAGMA table_list"))
            self.assertTrue(all(row[5] == 1 for row in tables if not row[1].startswith("sqlite_")))


if __name__ == "__main__":
    unittest.main()
