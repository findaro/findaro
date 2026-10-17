"""Query log: one JSON line per search or chat turn (what was asked, how it was understood, what came back).

Off unless FINDARO_QUERY_LOG names a file. End-user queries are personal data: turn it on for development and
demos, and decide on retention before enabling it anywhere real. A failed write never fails the request.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("findaro.querylog")
_lock = threading.Lock()


def top_hits(items: list[tuple[str, dict[str, Any]]], title_field: str | None, n: int = 10) -> list[dict[str, Any]]:
    """[{id, title}] for the first n results (title only when the schema has a title field)."""
    out = []
    for did, doc in items[:n]:
        row: dict[str, Any] = {"id": did}
        if title_field and doc.get(title_field) is not None:
            row["title"] = str(doc[title_field])[:120]
        out.append(row)
    return out


def record(path: str | None, entry: dict[str, Any]) -> None:
    if not path:
        return
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}, ensure_ascii=False, default=str)
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with _lock, p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        log.warning("query log write failed: %s", e)
