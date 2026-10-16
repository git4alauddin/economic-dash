"""Generate browser wire types from public Pydantic serialization schemas.

python -m app.generate_public_contract [--check]
No app startup, database, credentials, reports or external schema dependencies.
Runtime JSON validation remains the adapter's responsibility.
"""

import argparse
import json
from pathlib import Path
import re

from app.api_models import (CatalogIndicator, DashboardData, Envelope, ErrorEnvelope,
                            HistoryData, ResponsePanel, ResponseTicker)
from app.auth.routes import LoginInput, LoginResponse, PublicIdentity

TARGET = Path(__file__).resolve().parents[2] / "frontend/src/data/dashboard-response.ts"
ROOTS = {
    "DashboardResponseV1": Envelope[DashboardData],
    "CatalogResponseV1": Envelope[tuple[CatalogIndicator, ...]],
    "PanelResponseV1": Envelope[ResponsePanel],
    "HistoryResponseV1": Envelope[HistoryData],
    "TickerResponseV1": Envelope[ResponseTicker],
    "LoginRequest": LoginInput,
    "LoginResponse": LoginResponse,
    "PublicIdentity": PublicIdentity,
    "ApiErrorResponse": ErrorEnvelope,
}


def typescript(schema):
    if "$ref" in schema:
        reference = schema["$ref"].removeprefix("#/$defs/")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", reference):
            raise ValueError("Unsupported public schema reference.")
        return reference
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(item) for item in schema["enum"])
    for alternatives in ("anyOf", "oneOf"):
        if alternatives in schema:
            return " | ".join(typescript(item) for item in schema[alternatives])
    kind = schema.get("type")
    if kind == "object":
        if "properties" in schema:
            required = set(schema.get("required", ()))
            fields = [f"  readonly {json.dumps(key)}{'' if key in required else '?'}: {typescript(value)};"
                      for key, value in schema["properties"].items()]
            return "{\n" + "\n".join(fields) + "\n}"
        value = schema.get("additionalProperties", False)
        return "Readonly<Record<string, " + ("never" if value is False else "unknown" if value is True else typescript(value)) + ">>"
    if kind == "array":
        if "prefixItems" in schema:
            return "readonly [" + ", ".join(typescript(item) for item in schema["prefixItems"]) + "]"
        return "ReadonlyArray<" + typescript(schema["items"]) + ">"
    if kind in {"string", "boolean", "null"}:
        return kind
    if kind in {"integer", "number"}:
        return "number"
    raise ValueError("Unsupported public schema shape; update the generator explicitly.")


def render():
    definitions, roots = {}, {}
    for name, model in ROOTS.items():
        schema = model.model_json_schema(mode="serialization")
        for key, definition in schema.pop("$defs", {}).items():
            if key in definitions and definitions[key] != definition:
                raise ValueError("Conflicting public schema definitions.")
            definitions[key] = definition
        roots[name] = schema
    sections = ["// Generated from backend public serialization schemas. Do not edit by hand.\n"
                "// Regenerate: python -m app.generate_public_contract (from backend/).\n"
                "// Check: add --check. Runtime input still requires validation.\n"]
    for name, schema in sorted((definitions | roots).items()):
        sections.append(f"export type {name} = {typescript(schema)};\n")
    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != content:
            parser.exit(1, "Public wire types differ from the backend schema; regenerate and review.\n")
        print("PASS public wire types match backend serialization schemas")
    else:
        TARGET.write_text(content, encoding="utf-8", newline="\n")
        print("Updated public wire types")


if __name__ == "__main__":
    main()
