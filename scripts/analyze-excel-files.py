"""Inspect source workbooks without mutating them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

from app.parsers.schedule import parse_schedule


def main() -> None:
    source = PROJECT_ROOT / "data" / "local" / "source" / "schedule-2026-07-28.xls"
    result = parse_schedule(source)
    report = {
        "source": str(source),
        "rows_accepted": result.rows_accepted,
        "rows_rejected": result.rows_rejected,
        "classes": len(result.classes),
        "sessions": sum(len(item.sessions) for item in result.classes),
        "locked_classes": sum(1 for item in result.classes if item.locked_assignment),
        "merged_pair_suggestions": sum(
            len(group.class_keys) * (len(group.class_keys) - 1) // 2
            for group in result.merged_groups
        ),
        "validation_issues": len(result.issues),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
