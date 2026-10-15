"""Small bounded HTML reader for reviewed PIB release structures."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IGNORED_TAGS = {"script", "style", "noscript", "textarea", "template"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)

    def visible(self) -> bool:
        return self.tag not in IGNORED_TAGS and "hidden" not in self.attrs and self.attrs.get("aria-hidden") != "true" and not re.search(r"display\s*:\s*none", self.attrs.get("style") or "", re.I)

    def text(self) -> str:
        if not self.visible():
            return ""
        return " ".join(" ".join(child.text() if isinstance(child, Node) else child for child in self.children).split())

    def find(self, tag: str | None = None, **attrs: str) -> list["Node"]:
        if not self.visible():
            return []
        found = [self] if (tag is None or self.tag == tag) and all(self.attrs.get(key) == value for key, value in attrs.items()) else []
        for child in self.children:
            if isinstance(child, Node):
                found.extend(child.find(tag, **attrs))
        return found


class Document(HTMLParser):
    def __init__(self, body: bytes):
        super().__init__(convert_charrefs=True)
        if len(body) > 2_000_000:
            raise ValueError("HTML parser size limit exceeded.")
        self.root = Node("document")
        self.stack = [self.root]
        self.nodes = 0
        self.feed(body.decode("utf-8-sig", errors="strict"))
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > 30_000 or len(self.stack) > 100:
            raise ValueError("HTML structure exceeds parser limits.")
        if len(dict(attrs)) != len(attrs):
            raise ValueError("Duplicate HTML attributes.")
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, value: str) -> None:
        self.stack[-1].children.append(value)


def table_grid(table: Node) -> list[list[str]]:
    """Expand row/column spans before interpreting group headers or values."""
    grid: dict[tuple[int, int], str] = {}
    rows = table.find("tr")
    if len(rows) > 500:
        raise ValueError("Too many table rows.")
    for row_index, row in enumerate(rows):
        column = 0
        cells = [child for child in row.children if isinstance(child, Node) and child.tag in {"td", "th"} and child.visible()]
        for cell in cells:
            while (row_index, column) in grid:
                column += 1
            row_span, col_span = int(cell.attrs.get("rowspan") or "1"), int(cell.attrs.get("colspan") or "1")
            if not 1 <= row_span <= 30 or not 1 <= col_span <= 30 or column + col_span > 40 or row_index + row_span > len(rows):
                raise ValueError("Invalid table span.")
            for target_row in range(row_index, row_index + row_span):
                for target_col in range(column, column + col_span):
                    key = (target_row, target_col)
                    if key in grid:
                        raise ValueError("Overlapping table cells.")
                    grid[key] = cell.text()
            column += col_span
    width = max((column + 1 for _, column in grid), default=0)
    return [[grid.get((row, column), "") for column in range(width)] for row in range(len(rows))]
