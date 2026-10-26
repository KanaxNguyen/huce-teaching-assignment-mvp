"""Seed a fresh QA backend (:8026) with one semester and the 03-08-2026 real schedule activated."""
import httpx

B = "http://127.0.0.1:8026/api/v1"
F = "/Users/mac/Downloads/phan-cong-giang-day-lich-hoc-to-bo-mon-03-08-2026.xls"
c = httpx.Client(timeout=120)
sid = c.post(B + "/semesters", json=dict(name="QA UI 26-10", department_name="Toán học", head_name="QA", start_date="2026-08-03", end_date="2027-01-31")).json()["id"]
s = c.post(B + f"/sources/upload?semester_id={sid}&source_type=CURRENT_SCHEDULE", files={"file": (F.rsplit("/", 1)[1], open(F, "rb").read())}).json()
p = c.post(B + f"/sources/{s['id']}/preview?semester_id={sid}", json={"source_type": "CURRENT_SCHEDULE"}).json()
a = c.post(B + f"/sources/{s['id']}/activate?semester_id={sid}", json={"source_type": "CURRENT_SCHEDULE", "confirmed": True, "preview_token": p["preview_token"]})
print(sid, a.status_code, len(c.get(B + f"/classes?semester_id={sid}").json()))
