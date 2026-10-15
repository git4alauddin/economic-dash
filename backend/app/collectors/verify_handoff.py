"""Real-source, in-memory M3/M4 contract check; no SQL, API route or report file."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import SchedulerSettings
from .catalog import SourceRegistry
from .handoff import CollectionEnvelope
from .runner import CollectionRunner
from .snapshot_cache import SnapshotCache


async def verify(*, all_sources: bool = False) -> dict:
    envelopes = []
    def validate_plan(plan):
        item = CollectionEnvelope.from_plan(plan)
        decoded = CollectionEnvelope.model_validate_json(item.model_dump_json())
        if decoded != item or decoded.digest != item.digest:
            raise ValueError("Lossless handoff round trip failed.")
        envelopes.append(decoded)
    with TemporaryDirectory() as directory:
        cache = SnapshotCache(before_commit=validate_plan)
        runner = CollectionRunner(SchedulerSettings(_env_file=None, state_directory=Path(directory)), cache=cache)
        sources = SourceRegistry.load().source_ids if all_sources else ("world_bank_gdp",)
        result = await runner.run(sources, trigger="handoff_verification", history=all_sources)
        if result.status != "prepared":
            raise RuntimeError(f"Source verification failed: {result.reason_code}")
        restored = SnapshotCache.from_plan(envelopes[-1].to_plan())
        before = restored.view(datetime.now(timezone.utc))
        world = next(s for s in before.freshness if s.series_id == "gdp_growth_world")
        if world.observation is None or world.observation.as_of_precision != "year":
            raise ValueError("World GDP source/date metadata is missing.")
        points = {s.series_id: s.observation for s in before.freshness if s.observation is not None}
        now = datetime.now(timezone.utc)
        if not cache.record_failure(sources, run_id="handoff-failure-check", started=now, finished=now,
                                    reason="timeout", trigger="handoff_verification"):
            raise ValueError("Failure event handoff failed.")
        after = SnapshotCache.from_plan(envelopes[-1].to_plan()).view(now)
        if any(s.observation != points[s.series_id] or s.status != "stale" for s in after.freshness if s.series_id in points):
            raise ValueError("Failure handoff lost last-good data or stale metadata.")
        return dict(result="PASS", scope="collector_handoff_only", source_count=len(sources),
                    observations=sum(len(s.observations) for s in before.history.series),
                    supported_series=len(points), requirements=len(envelopes[-1].requirements),
                    blocked_requirements=sum(r.status == "blocked" for r in envelopes[-1].requirements),
                    lossless_round_trip=True, failure_retention=True, database_verified=False, api_verified=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-sources", action="store_true", help="Verify all selected sources and reviewed history; default: World GDP first slice.")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(all_sources=args.all_sources)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
