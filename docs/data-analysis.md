# Source data analysis

## Primary schedule

`schedule-2026-07-28.xls` is the newest source schedule and is selected as the default. It contains a 14-column table on `Sheet1`, with the two-row header at rows 8–9. The first valid record starts at row 10.

The verified import result is 314 accepted rows, 175 classes, 314 sessions, 36 locked classes, 139 initially unassigned classes, and 64 proposed merged pairs. This is the direct workbook count; it intentionally replaces the earlier rough estimate of 315 rows.

The importer detects the header from `STT`, `Mã học phần`, `Tên môn học`, and `Mã lớp học`; it does not rely on row 8 being fixed. It reads only columns A:N and ignores signatures and formatting-only ranges.

## Important observations

- Week strings are positional calendars; their spaces must be preserved until decoded.
- Multiple rows sharing `course_code + class_code` are sessions of the same class.
- Lecturer strings use the form `[code]Full name`.
- Assignments already present in the schedule are locked.
- A merged-class suggestion requires the same course and an identical complete schedule signature, including room, period, date range, and decoded weeks.
- The preference workbook contains real content in A:J, while formatting extends far beyond the data.

## Other sources

- `schedule-2026-07-26.xls`: earlier schedule snapshot.
- `teacher-preferences.xlsx`: lecturer preferences, aliases, and seminar notes.
- `previous-assignments.xlsx`: prior/derived assignment table.
- `expected-output-template.xlsx`: lecturer-by-weekday timetable layout.

Exact counts are produced by `scripts/analyze-excel-files.py` and by the import API, rather than hard-coded into the application.
