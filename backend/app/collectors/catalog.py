"""Turn the reviewed source catalog into a closed acquisition allowlist."""

from dataclasses import dataclass
import json
import re
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
            releases = source.get("history_releases", [])
            if len(releases) > 24 or (releases and (source["format"] != "html" or source.get("delivery_publisher_id") != "pib")):
                raise ValueError("History acquisition requires a bounded, reviewed PIB release list.")
            for release in releases:
                period = release["period"]
                url = validate_url(release["url"])
                key = f"{source_id}.history.{period}"
                if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", period, re.ASCII) or key in resources or urlsplit(url).hostname != urlsplit(source["url"]).hostname:
                    raise ValueError("Invalid/duplicate history period or unapproved host.")
                resources[key] = SourceResource(key, url, source["format"])
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

    def observation_resources(self, source_id: str) -> tuple[str, ...]:
        self.resolve(source_id)
        if source_id not in self.source_ids:
            raise ValueError("An observation source is required.")
        return (source_id,) + tuple(sorted(key for key in self.resources if key.startswith(f"{source_id}.history.")))
