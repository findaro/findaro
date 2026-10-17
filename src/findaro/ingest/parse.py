"""Parse ingest payloads (JSON array, JSONL, CSV) into documents."""

from __future__ import annotations

import csv
import io
from typing import Any

import orjson


class PayloadError(ValueError):
    pass


def detect_format(filename: str | None, content_type: str | None, explicit: str | None = None) -> str:
    if explicit:
        f = explicit.lower()
        if f not in ("csv", "jsonl", "json"):
            raise PayloadError("format must be csv, jsonl or json")
        return f
    name = (filename or "").lower()
    for ext, fmt in ((".csv", "csv"), (".jsonl", "jsonl"), (".ndjson", "jsonl"), (".json", "json")):
        if name.endswith(ext):
            return fmt
    ct = (content_type or "").lower()
    if "csv" in ct:
        return "csv"
    if "ndjson" in ct or "jsonl" in ct:
        return "jsonl"
    if "json" in ct:
        return "json"
    raise PayloadError("cannot tell file format; use a .csv/.jsonl/.json filename or ?format=")


def parse(data: bytes, fmt: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (documents, errors). Row-level problems become errors, not exceptions."""
    docs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if fmt == "json":
        try:
            obj = orjson.loads(data)
        except orjson.JSONDecodeError as e:
            raise PayloadError(f"invalid JSON: {e}") from e
        if isinstance(obj, dict) and isinstance(obj.get("documents"), list):
            obj = obj["documents"]
        if not isinstance(obj, list):
            raise PayloadError("expected a JSON array of documents")
        for i, d in enumerate(obj):
            (docs if isinstance(d, dict) else errors).append(d if isinstance(d, dict) else
                                                             {"row": i, "error": "not an object"})
        return docs, errors
    if fmt == "jsonl":
        for i, line in enumerate(data.splitlines()):
            if not line.strip():
                continue
            try:
                d = orjson.loads(line)
            except orjson.JSONDecodeError as e:
                errors.append({"row": i + 1, "error": f"invalid JSON: {e}"[:200]})
                continue
            if isinstance(d, dict):
                docs.append(d)
            else:
                errors.append({"row": i + 1, "error": "not an object"})
        return docs, errors
    if fmt == "csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise PayloadError("CSV must be UTF-8") from e
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise PayloadError("CSV has no header row")
        for row in reader:
            docs.append({k.strip(): v for k, v in row.items() if k is not None and v not in (None, "")})
        return docs, errors
    raise PayloadError(f"unknown format {fmt}")
