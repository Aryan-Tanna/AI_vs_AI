"""Write JSON Schema files for the three public case records to docs/schema/.

These are what annotators fill and what the Case Builder agent must output (as its structured output format).
Run after any change to lexarena/schemas/public_case.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexarena.schemas.public_case import PublicGroundTruth, PublicManifest, PublicUnspoiled  # noqa: E402

OUT = ROOT / "docs" / "schema"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, model in (("unspoiled", PublicUnspoiled), ("ground_truth", PublicGroundTruth), ("manifest", PublicManifest)):
        path = OUT / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
