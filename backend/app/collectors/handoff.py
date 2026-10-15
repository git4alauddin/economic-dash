"""M3/M4 v1 merge/checkpoint contract. SQL and public API projection remain M4."""

from datetime import datetime, timedelta
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .catalog import CATALOG_PATH, SourceRegistry, validate_url
from .freshness import FRESHNESS_VERSION, SourceState
from .history import HISTORY_VERSION, SourceFailure
from .http_client import FetchResult
from .normalization import PARSER_VERSION
from .observations import ImmutableModel, NormalizedBatch, NormalizedObservation
from .refresh_policy import POLICY_VERSION
from .snapshot_cache import AcceptedResource, CachePlan, SnapshotCache

CONTRACT_VERSION = "m3-m4-ingest-v1"


def catalog_fingerprint() -> str:
    catalogs = [json.loads(path.read_text(encoding="utf-8")) for path in (CATALOG_PATH, CATALOG_PATH.parent / "indicator-requirements.json")]
    return "sha256:" + sha256(json.dumps(catalogs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RequirementBinding(ImmutableModel):
    requirement_id: str
    source_id: str
    status: Literal["selected", "derived", "blocked"]
    definition_id: str | None
    unit: str | None
    frequency: str
    basis: str | None
    reason_code: str | None
    inputs: tuple[str, ...] = ()
    transform_id: str | None = None


def requirement_bindings() -> tuple[RequirementBinding, ...]:
    requirements = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["requirements"]
    return tuple(RequirementBinding(requirement_id=sid, source_id=d["source_id"], status=d["status"],
                                    definition_id=d["definition_id"], unit=d["unit"], frequency=d["frequency"], basis=d["basis"],
                                    reason_code=d.get("reason_code"), inputs=tuple(d.get("inputs", ())), transform_id=d.get("transform_id"))
                 for sid, d in sorted(requirements.items()))


class ValidatorReceipt(ImmutableModel):
    resource_id: str
    resource_url: str
    response_url: str
    content_type: str | None
    retrieved_at: datetime
    etag: str | None = Field(default=None, max_length=4096)
    last_modified: str | None = Field(default=None, max_length=4096)

    @field_validator("resource_url", "response_url")
    @classmethod
    def approved_url_shape(cls, value):
        return validate_url(value)

    def to_fetch_receipt(self) -> FetchResult:
        return FetchResult(self.resource_id, self.resource_url, self.response_url, "modified", None,
                           self.content_type, self.retrieved_at, 1, 0, self.etag, self.last_modified)


class ResourceCheckpoint(ImmutableModel):
    resource_id: str
    batch: NormalizedBatch
    receipts: tuple[ValidatorReceipt, ...] = Field(min_length=1, max_length=2)
    accepted_at: datetime
    checked_at: datetime

    @classmethod
    def from_entry(cls, entry: AcceptedResource) -> "ResourceCheckpoint":
        if any(receipt.body is not None for receipt in entry.receipts):
            raise ValueError("Raw bodies cannot cross the storage handoff.")
        return cls(resource_id=entry.resource_id, batch=entry.batch, accepted_at=entry.accepted_at, checked_at=entry.checked_at,
                   receipts=tuple(ValidatorReceipt(resource_id=r.source_id, resource_url=r.resource_url, response_url=r.response_url,
                                                   content_type=r.content_type, retrieved_at=r.retrieved_at, etag=r.etag, last_modified=r.last_modified)
                                  for r in entry.receipts))

    def to_entry(self) -> AcceptedResource:
        return AcceptedResource(self.resource_id, self.batch, tuple(r.to_fetch_receipt() for r in self.receipts), self.accepted_at, self.checked_at)


class CollectionEnvelope(ImmutableModel):
    contract_version: Literal["m3-m4-ingest-v1"] = CONTRACT_VERSION
    operation: Literal["merge"] = "merge"  # Omitted records NEVER mean SQL deletion.
    catalog_fingerprint: str
    parser_version: str = PARSER_VERSION
    history_version: str = HISTORY_VERSION
    refresh_version: str = POLICY_VERSION
    freshness_version: str = FRESHNESS_VERSION
    run_id: str = Field(min_length=1, max_length=128)
    trigger: str = Field(min_length=1, max_length=64)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=5)
    started_at: datetime
    finished_at: datetime
    requirements: tuple[RequirementBinding, ...]
    observations: tuple[NormalizedObservation, ...] = Field(max_length=1152)
    resources: tuple[ResourceCheckpoint, ...] = Field(max_length=160)
    source_states: tuple[SourceState, ...] = Field(max_length=5)
    failures: tuple[SourceFailure, ...]

    @field_validator("run_id", "trigger")
    @classmethod
    def printable_identifier(cls, value):
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Run identifiers must be printable ASCII.")
        return value

    @model_validator(mode="after")
    def contract_invariants(self):
        registry = SourceRegistry.load()
        if self.catalog_fingerprint != catalog_fingerprint() or self.requirements != requirement_bindings():
            raise ValueError("Source/definition catalog changed; explicit migration/review is required.")
        if (self.parser_version, self.history_version, self.refresh_version, self.freshness_version) != (PARSER_VERSION, HISTORY_VERSION, POLICY_VERSION, FRESHNESS_VERSION):
            raise ValueError("Pipeline version mismatch.")
        if len(set(self.source_ids)) != len(self.source_ids) or any(source not in registry.source_ids for source in self.source_ids):
            raise ValueError("Run scope must contain unique, enabled sources.")
        instants = [self.started_at, self.finished_at]
        for resource in self.resources:
            instants.extend((resource.accepted_at, resource.checked_at))
            instants.extend(r.retrieved_at for r in resource.receipts)
        for state in self.source_states:
            instants.extend(v for v in (state.last_attempt_at, state.last_checked_at, state.last_success_at, state.last_changed_at, state.last_failure_at) if v is not None)
            if state.source_id not in registry.source_ids or (state.last_attempt_at and state.last_checked_at and state.last_checked_at < state.last_attempt_at):
                raise ValueError("Invalid source state identity/timestamps.")
            if state.last_checked_at and any(v > state.last_checked_at for v in (state.last_success_at, state.last_changed_at, state.last_failure_at) if v is not None):
                raise ValueError("Source event timestamps cannot follow the latest check.")
        if any(instant.utcoffset() != timedelta(0) or instant > self.finished_at for instant in instants) or self.started_at > self.finished_at:
            raise ValueError("Handoff timestamps require ordered aware UTC times.")
        if len({r.resource_id for r in self.resources}) != len(self.resources) or len({s.source_id for s in self.source_states}) != len(self.source_states):
            raise ValueError("Duplicate checkpoint identities.")
        if any(sum(r.batch.source_id == source for r in self.resources) > 32 for source in registry.source_ids):
            raise ValueError("Resource checkpoint exceeds per-source bounds.")
        if any(f.source_id not in registry.source_ids for f in self.failures):
            raise ValueError("Failures cannot enable blocked sources.")
        current = {s.source_id: s for s in self.source_states if s.run_id == self.run_id}
        if set(current) != set(self.source_ids) or any(current[s].last_attempt_at != self.started_at or current[s].last_checked_at != self.finished_at for s in self.source_ids):
            raise ValueError("Run metadata and scoped source states must agree.")
        if any(p.retrieved_at > self.finished_at or p.inputs or p.transform_id for p in self.observations):
            raise ValueError("Ingest stores validated direct inputs; versioned derived values are recomputed.")
        signatures = {}
        for point in self.observations + tuple(p for resource in self.resources for p in resource.batch.observations):
            source = point.sources[0].source_id
            if source not in registry.source_ids:
                raise ValueError("Observation source is not enabled.")
            expected = (source,) + ((f"{source}.metadata",) if f"{source}.metadata" in registry.resources else ())
            if tuple(ref.source_id for ref in point.sources) != expected or any(ref.is_nse or urlsplit(ref.url).hostname != urlsplit(registry.resolve(ref.source_id).url).hostname for ref in point.sources):
                raise ValueError("Observation provenance differs from the selected publisher.")
            key = point.series_id, point.observation_period.id, point.vintage_id, point.parser_version
            signature = (point.definition_id, point.value, point.unit, point.observation_period, point.published_at,
                         point.revision_kind, point.source_unit, point.normalization_id, point.dataset_updated_at)
            if key in signatures and signatures[key] != signature:
                raise ValueError("One source vintage cannot contain contradictory observation records.")
            signatures[key] = signature
        # Reuse acceptance validation before either repository commit or reload.
        SnapshotCache.from_plan(self.to_plan())
        return self

    @classmethod
    def from_plan(cls, plan: CachePlan) -> "CollectionEnvelope":
        return cls(catalog_fingerprint=catalog_fingerprint(), run_id=plan.run_id, trigger=plan.trigger,
                   source_ids=tuple(sorted(plan.source_ids)), started_at=plan.started_at, finished_at=plan.finished_at,
                   requirements=requirement_bindings(), observations=plan.candidates,
                   resources=tuple(ResourceCheckpoint.from_entry(entry) for _, entry in sorted(plan.resources.items())),
                   source_states=tuple(sorted(plan.states, key=lambda state: state.source_id)),
                   failures=tuple(sorted(plan.failures, key=lambda f: (f.source_id, f.resource_id, f.reason_code))))

    def to_plan(self) -> CachePlan:
        return CachePlan(MappingProxyType({r.resource_id: r.to_entry() for r in self.resources}), self.observations,
                         self.source_states, self.failures, self.run_id, self.source_ids, self.started_at, self.finished_at, self.trigger)

    @property
    def digest(self) -> str:
        return "sha256:" + sha256(self.model_dump_json().encode()).hexdigest()


class CommitAcknowledgement(ImmutableModel):
    run_id: str
    envelope_digest: str
    repository_version: str = Field(min_length=1, max_length=128)
    durable: Literal[True] = True

    def verifies(self, envelope: CollectionEnvelope) -> bool:
        return self.durable is True and self.run_id == envelope.run_id and self.envelope_digest == envelope.digest


class StoredCheckpoint(ImmutableModel):
    envelope: CollectionEnvelope
    acknowledgement: CommitAcknowledgement

    @model_validator(mode="after")
    def committed(self):
        if not self.acknowledgement.verifies(self.envelope):
            raise ValueError("Checkpoint is not acknowledged by this repository transaction.")
        return self


class CollectionRepository(Protocol):
    """M4: synchronous SQL transaction, merge-only, idempotent on run_id + digest.

    Same run/digest returns the same acknowledgement; a reused run ID with a
    different digest rejects. Keep archival history when a bounded checkpoint
    omits records. commit() returns ONLY after durable commit. load() returns
    a validated bounded checkpoint; neither operation performs upstream HTTP.
    """

    def commit(self, envelope: CollectionEnvelope) -> CommitAcknowledgement: ...

    def load(self) -> StoredCheckpoint | None: ...


class RepositoryBridge:
    def __init__(self, repository: CollectionRepository):
        self.repository = repository
        self.last_acknowledgement: CommitAcknowledgement | None = None

    def __call__(self, plan: CachePlan) -> None:
        self.last_acknowledgement = None
        envelope = CollectionEnvelope.from_plan(plan)
        acknowledgement = self.repository.commit(envelope)
        if not isinstance(acknowledgement, CommitAcknowledgement) or not acknowledgement.verifies(envelope):
            raise ValueError("Repository returned a mismatched commit acknowledgement.")
        self.last_acknowledgement = acknowledgement

    def open_cache(self) -> SnapshotCache:
        checkpoint = self.repository.load()
        if checkpoint is None:
            cache = SnapshotCache()
        else:
            # Validate even a repository that returns constructed model objects.
            checkpoint = StoredCheckpoint.model_validate_json(checkpoint.model_dump_json())
            cache = SnapshotCache.from_plan(checkpoint.envelope.to_plan())
        cache.before_commit = self
        return cache
