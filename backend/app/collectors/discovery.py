"""Discover bounded candidate PIB releases; only full normalization accepts data."""

from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from .catalog import SourceRegistry
from .html_document import Document, Node
from .http_client import FetchResult
from .observations import ParseError

INDEX_ID = "pib_release_index"


class IndexDocument(Document):
    def handle_starttag(self, tag, attrs):
        # PIB's decorative footer image repeats a style attribute. Ignore image
        # attributes entirely; release links and structural nodes remain strict.
        super().handle_starttag(tag, [] if tag == "img" else attrs)


@dataclass(frozen=True)
class ReleaseCandidate:
    source_id: str
    url: str
    title: str


def _family(ministry: str, title: str) -> str | None:
    text = title.casefold()
    if ministry == "Ministry of Statistics & Programme Implementation":
        if "consumer price index" in text and "2024" in text:
            return "mospi_cpi_pib"
        if "annual gross domestic product" in text:
            return "mospi_gdp_pib"
    if ministry == "Ministry of Commerce & Industry" and "exports" in text and "merchandise" in text and "during" in text:
        return "commerce_trade_pib"
    if ministry == "Ministry of Finance" and "review of accounts" in text and "government" in text:
        return "finance_accounts_pib"
    return None


def discover_releases(result: FetchResult, registry: SourceRegistry, sources: tuple[str, ...], *, limit: int = 2) -> tuple[ReleaseCandidate, ...]:
    resource = registry.resolve(INDEX_ID)
    if result.source_id != INDEX_ID or result.resource_url != resource.url or urlsplit(result.response_url).hostname != "www.pib.gov.in" or urlsplit(result.response_url).scheme != "https" or result.outcome != "modified" or result.body is None or (result.content_type or "").partition(";")[0] != "text/html":
        raise ParseError(INDEX_ID, "release_index_identity_mismatch")
    if type(limit) is not int or not 1 <= limit <= 4:
        raise ValueError("Discovery limit must be between one and four per source.")
    try:
        document = IndexDocument(result.body)
        if not any(node.text() == "All Releases" for node in document.root.find("h2")):
            raise ValueError("PIB release index heading changed.")
        known = {source: {parse_qs(urlsplit(registry.resolve(key).url).query).get("PRID", [None])[0] for key in registry.observation_resources(source)} for source in sources}
        candidates = {}
        ministry = None
        def visit(node: Node):
            nonlocal ministry
            if not node.visible():
                return
            if node.tag == "h3":
                ministry = node.text()
            if node.tag == "a":
                title = node.text()
                source = _family(ministry, title)
                if source in sources:
                    parsed = urlsplit(urljoin(resource.url, node.attrs.get("href") or ""))
                    query = parse_qs(parsed.query)
                    if parsed.scheme != "https" or parsed.hostname != "www.pib.gov.in" or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.path not in {"/PressReleseDetail.aspx", "/PressReleasePage.aspx", "/PressReleaseDetail.aspx"} or parsed.fragment or set(query) != {"PRID"} or len(query["PRID"]) != 1 or not re.fullmatch(r"\d{6,8}", query["PRID"][0], re.ASCII):
                        raise ValueError("Unexpected candidate URL.")
                    release = query["PRID"][0]
                    if release not in known[source]:
                        candidates[source, release] = ReleaseCandidate(source, f"https://www.pib.gov.in/PressReleasePage.aspx?PRID={release}", title)
            for child in node.children:
                if isinstance(child, Node):
                    visit(child)
        visit(document.root)
        picked = []
        for source in sources:
            options = [(int(release), item) for (sid, release), item in candidates.items() if sid == source]
            # IDs only bound discovery order; publisher timestamps and periods
            # resolve actual revisions after every candidate is parsed.
            picked.extend(item for _, item in sorted(options, reverse=True)[:limit])
        return tuple(picked)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise ParseError(INDEX_ID, "invalid_release_index") from error
