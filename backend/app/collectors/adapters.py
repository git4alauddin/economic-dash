"""Acquisition adapters; source-specific parsers are implemented in M3.4."""

from dataclasses import dataclass
from typing import Protocol

from .http_client import CollectorHttpClient, FetchResult


@dataclass(frozen=True)
class SourcePayloads:
    source_id: str
    payload: FetchResult
    metadata: FetchResult | None = None


class SourceAdapter(Protocol):
    source_id: str

    async def acquire(self) -> SourcePayloads: ...


@dataclass
class CatalogSourceAdapter:
    source_id: str
    client: CollectorHttpClient

    async def acquire(self) -> SourcePayloads:
        payload = await self.client.fetch(self.source_id)
        metadata_id = f"{self.source_id}.metadata"
        metadata = await self.client.fetch(metadata_id) if metadata_id in self.client.registry.resources else None
        return SourcePayloads(self.source_id, payload, metadata)


def create_adapters(client: CollectorHttpClient) -> dict[str, SourceAdapter]:
    """One adapter per selected source, shared across its dependent series."""
    return {source_id: CatalogSourceAdapter(source_id, client) for source_id in client.registry.source_ids}
