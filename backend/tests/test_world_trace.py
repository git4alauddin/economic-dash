"""Independent source-token tracing rejects parser/SQL identity drift."""

from dataclasses import replace
from pathlib import Path
from app.sqlite_runtime import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app.config import DatabaseSettings
from app.database import Database
from app.repository import SQLiteCollectionRepository
from app.verify_world_trace import world_gdp_trace
from test_normalization import wb
from test_repository import prepare
from test_snapshot_cache import check


class WorldTraceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Database(DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db"))
        self.database.bootstrap()
        self.bundle = wb()
        SQLiteCollectionRepository(self.database).commit(prepare(checks=(check(self.bundle),)))

    def trace(self, receipt=None):
        return world_gdp_trace(self.database, receipt or self.bundle.payload, self.bundle.metadata)

    def test_publisher_decimal_year_and_urls_match_sql_without_rounding_source_value(self):
        result = self.trace()
        self.assertEqual(result["value"], "2.123456789012345678")
        self.assertEqual(result["display"], "2.12%")
        self.assertEqual((result["year"], result["period"]["basis"], result["period"]["id"]), ("2025", "calendar", "CY2025"))
        self.assertEqual([source["url"] for source in result["sources"]], [self.bundle.payload.response_url, self.bundle.metadata.response_url])

    def test_independent_publisher_identity_and_numeric_changes_cannot_pass(self):
        for original, changed in ((b"WLD", b"IND"), (b"NY.GDP.MKTP.KD.ZG", b"WRONG.INDICATOR"),
                                  (b"2.123456789012345678", b"999.5")):
            with self.subTest(change=original), self.assertRaises(ValueError):
                self.trace(replace(self.bundle.payload, body=self.bundle.payload.body.replace(original, changed)))

    def test_sql_value_date_unit_and_source_drift_cannot_pass(self):
        for column, changed in (("value_decimal", "999"), ("period_label", "FY 2025")):
            with self.database.connection(read_only=True) as connection:
                original = connection.execute("SELECT * FROM observations WHERE series_id='gdp_growth_world'").fetchone()[column]
            # Column identifiers are fixed test constants, never user input.
            with self.database.transaction() as connection:
                connection.execute(f"UPDATE observations SET {column}=?", (changed,))
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.trace()
            with self.database.transaction() as connection:
                connection.execute(f"UPDATE observations SET {column}=?", (original,))
        # The storage constraint itself prevents a mismatched annual as-of year.
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute("UPDATE observations SET as_of='2024'")
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute("UPDATE observations SET unit='percent'")
        with self.database.transaction() as connection:
            connection.execute("UPDATE observation_sources SET url='https://example.com/wrong-publisher'")
        with self.assertRaises(ValueError):
            self.trace()


if __name__ == "__main__":
    unittest.main()
