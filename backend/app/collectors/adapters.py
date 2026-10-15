"""Acquisition and normalization adapters; persistence accepts batches separately."""

from dataclasses import dataclass
from typing import Protocol

from .http_client import CollectorHttpClient, FetchResult
from .normalization import SourceNormalizer
from .observations import NormalizedBatch


@dataclass(frozen=True)
class SourcePayloads:
    source_id: str
    payload: FetchResult
    metadata: FetchResult | None = None


class SourceAdapter(Protocol):
    source_id: str

    async def acquire(self, *, resource_id: str | None = None, conditional: bool = True) -> SourcePayloads: ...

    def normalize(self, payloads: SourcePayloads) -> NormalizedBatch: ...


@dataclass
class CatalogSourceAdapter:
    source_id: str
    client: CollectorHttpClient
    normalizer: SourceNormalizer

    async def acquire(self, *, resource_id: str | None = None, conditional: bool = True) -> SourcePayloads:
        resource_id = resource_id or self.source_id
        if resource_id not in self.client.registry.observation_resources(self.source_id):
            raise ValueError("Resource does not belong to this adapter.")
        payload = await self.client.fetch(resource_id, conditional=conditional)
        metadata_id = f"{self.source_id}.metadata"
        metadata = await self.client.fetch(metadata_id, conditional=conditional) if metadata_id in self.client.registry.resources else None
        return SourcePayloads(self.source_id, payload, metadata)

    def normalize(self, payloads: SourcePayloads) -> NormalizedBatch:
        if payloads.source_id != self.source_id:
            raise ValueError("Adapter/source mismatch.")
        return self.normalizer.parse(payloads)


def create_adapters(client: CollectorHttpClient) -> dict[str, SourceAdapter]:
    """One adapter per selected source, shared across its dependent series."""
    normalizer = SourceNormalizer()
    return {source_id: CatalogSourceAdapter(source_id, client, normalizer) for source_id in client.registry.source_ids}
