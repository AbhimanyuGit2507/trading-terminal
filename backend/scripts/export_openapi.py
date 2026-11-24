"""Export FastAPI OpenAPI schema to /shared/openapi.json."""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.schemas.domain import WsSubscribeMessage, WsTickFrameSchema


def main() -> None:
    out_path = ROOT_DIR / "shared" / "openapi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for model in (WsSubscribeMessage, WsTickFrameSchema):
        if model.__name__ not in components:
            components[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
    out_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Exported OpenAPI schema to {out_path}")


if __name__ == "__main__":
    main()
