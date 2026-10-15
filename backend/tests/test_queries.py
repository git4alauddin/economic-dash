"""SQL-backed histories/cards; synthetic observations never seed production data."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.collectors.observations import NormalizedBatch, annual_period, monthly_period
from app.config import DatabaseSettings
from app.database import Database
from app.queries import DashboardQueries, QueryIntegrityError, QueryLimitExceeded, UnknownIndicator, UnknownSeries
from app.repository import SQLiteCollectionRepository
from test_history import record
from test_normalization import NOW, changed, cpi, expenditure, gdp, trade, wb
from test_repository import prepare
from test_snapshot_cache import check


def world_resource(years=(2024, 2025), values=("1.00", "2.123456789012345678")):
    resource = check(wb())
    template = resource.batch.observations[0]
    points = tuple(record(template, observation_period=annual_period(year), value=Decimal(value) if value is not None else None,
                          quality_status="missing" if value is None else "valid", reason_code="source_value_missing" if value is None else None)
                   for year, value in zip(years, values))
    return replace(resource, batch=NormalizedBatch(source_id="world_bank_gdp", observations=points, coverage="bounded_page"))


def reading(panel, sid):
    return next(s for s in panel.series if s.history.series_id == sid)


class QueryTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Database(DatabaseSettings(_env_file=None, app_env="test", directory=Path(directory.name) / "db"))
        self.database.bootstrap()
        self.repository = SQLiteCollectionRepository(self.database)
        self.queries = DashboardQueries(self.database)

    def populate(self):
        self.item = prepare(checks=(world_resource(),) + tuple(check(factory()) for factory in (gdp, trade, cpi, expenditure)))
        self.repository.commit(self.item)

    def test_empty_database_has_six_panels_twelve_mapped_cards_and_blocked_ticker(self):
        dashboard = self.queries.dashboard(now=NOW)
        self.assertIsNone(dashboard.checkpoint_run_id)
        self.assertEqual(len(dashboard.panels), 6)
        cards = [card for p in dashboard.panels for card in p.summaries]
        self.assertEqual(len(cards), 12)
        self.assertTrue(all(card.observation is None and card.reason_code for card in cards))
        self.assertEqual({card.requirement_id for card in cards}, {
            "gdp_growth_india", "gdp_growth_world", "debt_to_gdp_india", "debt_india_us_comparison",
            "exports", "imports", "gst_total", "gst_monthly_average", "cpi_yoy", "rbi_target", "expenditure_total", "expenditure_capital"})
        self.assertEqual(len(dashboard.ticker), 3)
        self.assertTrue(all(quote.reason_code for quote in dashboard.ticker))

    def test_gdp_fiscal_calendar_history_and_exact_comparisons_remain_separate(self):
        self.populate()
        panel = self.queries.indicator("gdp_growth", now=NOW)
        india, world = reading(panel, "gdp_growth_india"), reading(panel, "gdp_growth_world")
        self.assertEqual(india.latest_valid.observation_period.basis, "fiscal")
        self.assertEqual(world.latest_valid.observation_period.basis, "calendar")
        self.assertEqual(india.history.window[-1].period.id, "FY2025-26")
        self.assertEqual(world.history.window[-1].period.id, "CY2025")
        self.assertEqual(india.history.window[0].reason_code, "comparable_base_history_unverified")
        self.assertEqual(india.comparison.value.display_decimal(2), "1.90")
        self.assertEqual(world.comparison.value.display_decimal(18), "1.123456789012345678")
        self.assertEqual(world.comparison.unit, "percentage_points")
        self.assertEqual(panel.summaries[1].observation.sources, world.latest_valid.sources)
        self.assertIsNone(panel.summaries[1].observation.published_at)

    def test_reference_outside_chart_and_negative_trade_balance_keep_exact_inputs(self):
        self.populate()
        exports = self.queries.series("exports", window=1, now=NOW)
        self.assertEqual([slot.period.id for slot in exports.history.window], ["2026-09"])
        self.assertEqual(exports.comparison.reference_period_id, "2025-09")
        self.assertEqual(Fraction(exports.comparison.value.numerator, exports.comparison.value.denominator), Fraction(100, 9))
        balance = self.queries.series("trade_balance", window=1, now=NOW)
        self.assertEqual(balance.latest_valid.value, Decimal("-4.70"))
        self.assertEqual(tuple(p.series_id for p in balance.latest_valid.inputs), ("exports", "imports"))
        self.assertEqual(balance.comparison.reason_code, "comparison_not_defined")

    def test_period_selection_uses_old_sql_values_without_forward_fill(self):
        self.populate()
        panel = self.queries.indicator("gdp_growth", end_periods={"gdp_growth_india": "FY2024-25", "gdp_growth_world": "CY2024"}, now=NOW)
        self.assertEqual(reading(panel, "gdp_growth_india").latest_valid.value, Decimal("6.20"))
        self.assertEqual(reading(panel, "gdp_growth_world").latest_valid.value, Decimal("1.00"))
        empty = self.queries.series("gdp_growth_world", end_period_id="CY2010", window=2, now=NOW)
        self.assertIsNone(empty.latest_valid)
        self.assertEqual([s.period.id for s in empty.history.window], ["CY2009", "CY2010"])
        self.assertTrue(all(s.observation is None for s in empty.history.window))

    def test_null_new_period_keeps_actual_prior_date_and_zero_is_valid(self):
        self.repository.commit(prepare(checks=(world_resource(values=("0", None)),)))
        panel = self.queries.indicator("gdp_growth", now=NOW)
        world = reading(panel, "gdp_growth_world")
        self.assertIsNone(world.history.latest.value)
        self.assertEqual(world.history.window[-1].reason_code, "source_value_missing")
        self.assertEqual(world.latest_valid.value, Decimal(0))
        self.assertEqual(world.latest_valid.as_of, "2024")
        self.assertEqual(panel.summaries[1].observation.as_of, "2024")
        self.assertEqual(panel.summaries[1].reason_code, "latest_period_observation_missing")

    def test_missing_consecutive_reference_is_unavailable_not_skipped_year(self):
        self.repository.commit(prepare(checks=(world_resource(years=(2023, 2025)),)))
        world = self.queries.series("gdp_growth_world", now=NOW)
        self.assertIsNone(world.comparison.value)
        self.assertEqual(world.comparison.reference_period_id, "CY2024")
        self.assertEqual(world.comparison.reason_code, "reference_observation_missing")

    def test_zero_denominator_preserves_reference_and_does_not_emit_percent_change(self):
        resource = check(trade())
        points = tuple(record(point, value=Decimal(0)) if point.as_of == "2025-09" else point
                       for point in resource.batch.observations)
        resource = replace(resource, batch=resource.batch.model_copy(update={"observations": points}))
        self.repository.commit(prepare(checks=(resource,)))
        exports = self.queries.series("exports", window=1, now=NOW)
        self.assertEqual(exports.latest_valid.value, Decimal("12.50"))
        self.assertEqual(exports.comparison.reference.value, Decimal(0))
        self.assertIsNone(exports.comparison.value)
        self.assertEqual(exports.comparison.reason_code, "zero_reference_denominator")

    def test_mismatched_release_vintages_do_not_create_a_comparison(self):
        resource = world_resource()
        prior, current = resource.batch.observations
        resource = replace(resource, batch=resource.batch.model_copy(update={"observations": (record(prior, vintage_id="different-dataset-edition"), current)}))
        self.repository.commit(prepare(checks=(resource,)))
        world = self.queries.series("gdp_growth_world", window=1, now=NOW)
        self.assertIsNone(world.comparison.value)
        self.assertEqual(world.comparison.reason_code, "comparison_inputs_not_comparable")

    def test_revised_cpi_wins_by_publication_and_keeps_superseded_rows(self):
        self.repository.commit(prepare(cpi))
        revision = lambda: changed(changed(changed(cpi(), "12 OCT", "13 OCT"), "September, 2026 (Provisional)", "September, 2026 (Final)"), "0.00", "0.10")
        self.repository.commit(prepare(revision, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="cpi-final"))
        cpi_read = self.queries.series("cpi_yoy", window=2, now=NOW + timedelta(hours=1))
        self.assertEqual(cpi_read.latest_valid.revision_kind, "final")
        self.assertEqual(cpi_read.latest_valid.value, Decimal("0.10"))
        self.assertTrue(any(p.revision_kind == "provisional" and p.value == 0 for p in cpi_read.history.superseded))
        self.assertEqual(cpi_read.comparison.value.display_decimal(2), "0.30")

    def test_ytd_same_cutoff_comparison_does_not_sum_monthly_snapshots(self):
        resource = check(expenditure())
        current = resource.batch.observations
        amounts = {"expenditure_total": "100000", "expenditure_capital": "20000", "expenditure_revenue": "80000"}
        prior = tuple(record(p, observation_period=monthly_period(2025, 8, cumulative=True), value=Decimal(amounts[p.series_id]),
                             published_at=NOW - timedelta(days=380), vintage_id="prior-year") for p in current)
        resource = replace(resource, batch=resource.batch.model_copy(update={"observations": current + prior}))
        self.repository.commit(prepare(checks=(resource,)))
        panel = self.queries.indicator("government_expenditure", now=NOW)
        total = reading(panel, "expenditure_total")
        self.assertEqual(total.latest_valid.value, Decimal("123456"))
        self.assertEqual(total.comparison.reference_period_id, "FY2025-26:2025-08")
        self.assertEqual(total.comparison.value.display_decimal(3), "23.456")
        self.assertEqual(total.history.window[0].reason_code, "published_components_do_not_reconcile")
        self.assertEqual([slot.period.id for slot in total.history.window], [f"FY2026-27:2026-{month:02}" for month in range(4, 9)])

    def test_blocked_cards_preserve_specific_reasons_and_unknown_units(self):
        self.populate()
        dashboard = self.queries.dashboard(now=NOW)
        cards = {c.requirement_id: c for p in dashboard.panels for c in p.summaries}
        for requirement in ("gst_total", "gst_monthly_average", "rbi_target", "debt_to_gdp_india", "debt_india_us_comparison"):
            self.assertIsNone(cards[requirement].observation)
            self.assertEqual(cards[requirement].reason_code, self.queries.catalog["requirements"][requirement]["reason_code"])
            self.assertEqual(cards[requirement].comparison.reason_code, cards[requirement].reason_code)
        self.assertIsNone(cards["debt_india_us_comparison"].unit)
        self.assertIsNone(cards["debt_india_us_comparison"].definition_id)

    def test_old_sql_archive_is_queryable_after_collector_ram_eviction(self):
        resource = world_resource(years=tuple(range(1970, 2019)), values=("2.5",) * 49)
        item = prepare(checks=(resource,))
        self.assertEqual(len(item.observations), 48)
        self.repository.commit(item)
        with patch.object(self.repository, "load", side_effect=AssertionError("Read SQL, not collector cache")):
            oldest = self.queries.series("gdp_growth_world", end_period_id="CY1970", window=1, now=NOW)
        self.assertEqual(oldest.latest_valid.as_of, "1970")
        self.assertEqual(oldest.latest_valid.value, Decimal("2.5"))

    def test_queries_perform_no_network_or_writes(self):
        self.populate()
        with self.database.connection() as connection:
            before = [tuple(row) for row in connection.execute("SELECT run_id,envelope_digest FROM collector_runs ORDER BY run_id")]
        with patch("socket.socket", side_effect=AssertionError("No HTTP during data reads")):
            self.queries.dashboard(now=NOW)
            self.queries.indicator("trade", now=NOW)
            self.queries.series("cpi_yoy", now=NOW)
        with self.database.connection() as connection:
            after = [tuple(row) for row in connection.execute("SELECT run_id,envelope_digest FROM collector_runs ORDER BY run_id")]
        self.assertEqual(before, after)

    def test_validation_unknown_ids_injection_period_basis_and_limits(self):
        with patch.object(self.database, "connection", side_effect=AssertionError("Unknown ID must fail before SQL")):
            for identifier in ("missing", "trade'; DROP TABLE observations; --"):
                with self.assertRaises(UnknownIndicator):
                    self.queries.indicator(identifier)
                with self.assertRaises(UnknownSeries):
                    self.queries.series(identifier)
        for window in (0, 25, True, 1.5, "5"):
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.queries.dashboard(window=window)
        for sid, period in (("gdp_growth_india", "CY2025"), ("gdp_growth_world", "FY2024-25"), ("cpi_yoy", "2026-13"),
                            ("expenditure_total", "FY2025-26:2026-08"), ("gdp_growth_world", "CY2027"),
                            ("gdp_growth_world", "CY2025' OR 1=1 --"), ("rbi_target", "2026-09")):
            with self.subTest(sid=sid, period=period), self.assertRaises(ValueError):
                self.queries.series(sid, end_period_id=period, now=NOW)
        with self.assertRaises(ValueError):
            self.queries.indicator("trade", end_periods={"gdp_growth_india": "FY2024-25"}, now=NOW)
        with self.assertRaises(ValueError):
            self.queries.indicator("trade", end_periods={"exports": None}, now=NOW)
        with self.assertRaises(ValueError):
            self.queries.dashboard(now=NOW.replace(tzinfo=None))

    def test_large_revision_read_fails_explicitly_instead_of_truncating(self):
        self.populate()
        with patch("app.queries.MAX_QUERY_ROWS", 1), self.assertRaises(QueryLimitExceeded):
            self.queries.series("gdp_growth_world", now=NOW)

    def test_dashboard_uses_one_snapshot_when_another_process_commits_mid_read(self):
        self.repository.commit(prepare(wb))
        next_item = prepare(trade, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="concurrent")
        original = self.queries._indicator
        def concurrent(connection, indicator, window, selections, now):
            result = original(connection, indicator, window, selections, now)
            if indicator == "gdp_growth":
                self.repository.commit(next_item)
            return result
        with patch.object(self.queries, "_indicator", side_effect=concurrent):
            old = self.queries.dashboard(now=NOW + timedelta(hours=1))
        old_trade = next(p for p in old.panels if p.indicator_id == "trade")
        self.assertEqual(old.checkpoint_run_id, "first")
        self.assertIsNone(reading(old_trade, "exports").latest_valid)
        new = self.queries.dashboard(now=NOW + timedelta(hours=1))
        new_trade = next(p for p in new.panels if p.indicator_id == "trade")
        self.assertEqual(new.checkpoint_run_id, "concurrent")
        self.assertIsNotNone(reading(new_trade, "exports").latest_valid)

    def test_catalog_mismatch_fails_without_returning_relabelled_values(self):
        self.populate()
        with self.database.transaction() as connection:
            connection.execute("UPDATE collector_runs SET catalog_fingerprint=?", ("sha256:" + "0" * 64,))
        with self.assertRaises(QueryIntegrityError):
            self.queries.dashboard(now=NOW)


if __name__ == "__main__":
    unittest.main()
