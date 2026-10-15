"""Manual CLI: python -m app.collectors.refresh [--source ID] [--history]."""

import argparse
import asyncio

from app.config import get_settings, get_scheduler_settings, get_database_settings
from app.database import Database
from app.repository import SQLiteCollectionRepository
from .catalog import SourceRegistry
from .runner import CollectionRunner, configure_logging


def main() -> int:
    choices = SourceRegistry.load().source_ids
    parser = argparse.ArgumentParser(description="Acquire selected sources and atomically commit validated observations to private SQLite.")
    parser.add_argument("--source", action="append", choices=choices, help="Selected source ID; repeat for several, omit for all.")
    parser.add_argument("--history", action="store_true", help="Include the reviewed historical releases (bounded backfill).")
    arguments = parser.parse_args()
    sources = tuple(arguments.source or choices)
    if len(set(sources)) != len(sources):
        parser.error("Each source may appear only once.")
    configure_logging()
    app_env = get_settings().app_env
    settings = get_scheduler_settings(app_env)
    database = Database(get_database_settings(app_env))
    database.bootstrap()
    result = asyncio.run(CollectionRunner(settings, repository=SQLiteCollectionRepository(database)).run(sources, trigger="manual", history=arguments.history))
    print(result.as_json())
    return 0 if result.status in {"prepared", "unchanged"} else (2 if result.status == "skipped_busy" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
