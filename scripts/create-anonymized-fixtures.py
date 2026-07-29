"""Create a deterministic anonymous fixture that preserves the ingestion shape."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = {
    "lecturers": [
        {"code": "GV001", "name": "Giảng viên An", "max_credits": 18},
        {"code": "GV002", "name": "Giảng viên Bình", "max_credits": 18},
    ],
    "classes": [
        {
            "course_code": "TEST101",
            "course_name": "Môn học mẫu",
            "class_code": "TEST-A1",
            "credits": 3,
            "locked_assignment": False,
            "sessions": [
                {
                    "weekday": 2,
                    "start_period": 1,
                    "end_period": 3,
                    "room": "P.TEST-01",
                    "raw_weeks": "12345678",
                    "active_weeks": [1, 2, 3, 4, 5, 6, 7, 8],
                }
            ],
        }
    ],
}


if __name__ == "__main__":
    target = ROOT / "data" / "fixtures" / "anonymized-schedule.json"
    target.write_text(
        json.dumps(FIXTURE, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(target)
