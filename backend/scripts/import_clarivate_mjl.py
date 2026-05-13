from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage a user-downloaded Clarivate MJL file for crawler import.")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Input file does not exist: {source}")
    target_dir = Path(settings.clarivate_manual_import_dir)
    if not target_dir.is_absolute():
        target_dir = Path(__file__).resolve().parents[1] / target_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    print(f"staged={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
