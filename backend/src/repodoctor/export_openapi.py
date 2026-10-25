"""Write the OpenAPI schema without network access or API keys.

Usage (from backend/): uv run python -m repodoctor.export_openapi ../contracts/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from repodoctor.config import PROJECT_ROOT, Settings
from repodoctor.main import create_app

DEFAULT_OUTPUT = PROJECT_ROOT / "contracts" / "openapi.json"


def render_openapi() -> str:
    # Schema does not depend on env; defaults keep the output reproducible.
    settings = Settings(_env_file=None, use_dev_stubs=False, openai_api_key=None)
    schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def export_openapi(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_openapi(), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    target = Path(args[0]) if args else DEFAULT_OUTPUT
    export_openapi(target)
    print(f"OpenAPI written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
