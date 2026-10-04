"""Validate the public case DB. Exit code 1 if any ERROR.

  python scripts/validate_public_db.py                         # public_db/
  python scripts/validate_public_db.py docs/schema/example --allow-synthetic
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lexarena.config import Settings  # noqa: E402
from lexarena.public_db_validate import validate_dir  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("dir", nargs="?", type=Path, default=None)
    p.add_argument("--allow-synthetic", action="store_true")
    args = p.parse_args()
    target = args.dir or Settings().public_db_dir
    problems = validate_dir(target, allow_synthetic=args.allow_synthetic)
    for prob in problems:
        print(prob)
    errors = sum(prob.level == "ERROR" for prob in problems)
    print(f"{target}: {errors} error(s), {len(problems) - errors} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
