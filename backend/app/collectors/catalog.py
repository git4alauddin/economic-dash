"""Turn the reviewed source catalog into a closed acquisition allowlist."""

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from .errors import AcquisitionError, ErrorCode

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "source-catalog.json"


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.fragment or parsed.port not in {None, 443}
        or any(char.isspace() or ord(char) < 32 for char in url)
    ):
        raise ValueError("Acquisition requires an approved, credential-free HTTPS URL.")
    return url


@dataclass(frozen=True)
class SourceResource:
    source_id: str
    url: str
    format: str


@dataclass(frozen=True)
class SourceRegistry:
    resources: Mapping[str, SourceResource]
    blocked_ids: frozenset[str]
    source_ids: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = CATALOG_PATH) -> "SourceRegistry":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] != 1:
            raise ValueError("Unsupported source catalog version.")
        selected = {
            item["source_id"] for item in data["requirements"].values()
            if item["status"] in {"selected", "derived"}
        }
        resources = {}
        for source_id in sorted(selected):
            source = data["sources"][source_id]
            reuse = data["reuse"][source["reuse_id"]]
            if reuse["collection_allowed"] is not True or source["access"] != "verified_local":
                raise ValueError(f"Selected source {source_id} still has an access/reuse gate.")
            if source["format"] not in {"json", "html", "pdf"}:
                raise ValueError(f"Unsupported source format: {source_id}")
            resources[source_id] = SourceResource(source_id, validate_url(source["url"]), source["format"])
            if source.get("metadata_url"):
                key = f"{source_id}.metadata"
                resources[key] = SourceResource(key, validate_url(source["metadata_url"]), source["format"])
        blocked = frozenset(set(data["sources"]) - selected)
        return cls(MappingProxyType(resources), blocked, tuple(sorted(selected)))

    def resolve(self, source_id: str) -> SourceResource:
        if source_id in self.blocked_ids:
            raise AcquisitionError(source_id, ErrorCode.SOURCE_BLOCKED)
        if source_id not in self.resources:
            raise AcquisitionError(source_id, ErrorCode.UNKNOWN_SOURCE)
        return self.resources[source_id]
