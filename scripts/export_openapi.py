"""Write the OpenAPI spec to sdk/openapi.json (the SDK generates its types from it).

    uv run python scripts/export_openapi.py
"""

import json
from pathlib import Path

from zerch.main import create_app

out = Path(__file__).resolve().parent.parent / "sdk" / "openapi.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(create_app().openapi(), indent=1, ensure_ascii=False) + "\n")
print(f"wrote {out}")
