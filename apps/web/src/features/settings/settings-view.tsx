"use client";

import { CalendarCheck, ExternalLink, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import dashboardStyles from "@/src/features/dashboard/dashboard.module.css";
import { api } from "@/src/services/api";
import type { AppSettings, Lecturer } from "@/src/types/api";

import styles from "./settings-view.module.css";

export function SettingsView({
  settings,
  lecturers,
  busy,
  onSave,
}: {
  settings: AppSettings;
  lecturers: Lecturer[];
  busy: string | null;
  onSave: (payload: AppSettings) => void;
}) {
  const [form, setForm] = useState(settings);

  useEffect(() => setForm(settings), [settings]);

  function update<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <div className={dashboardStyles.viewStack}>
      <section className={dashboardStyles.sectionHeading}>
        <div>
          <span className={dashboardStyles.eyebrow}>Thiết lập dùng chung</span>
          <h2>Cài đặt học kỳ và Calendar</h2>
          <p>Các giá trị này được lưu cục bộ và dùng cho tiêu đề giao diện, JSON và tệp lịch ICS.</p>
        </div>
        <button className={dashboardStyles.primaryButton} disabled={!!busy} onClick={() => onSave(form)}>
          <Save size={17} />{busy === "settings" ? "Đang lưu…" : "Lưu cài đặt"}
        </button>
      </section>

      <div className={styles.settingsGrid}>
        <section className={styles.settingsCard}>
          <div className={styles.cardTitle}><CalendarCheck size={20} /><div><strong>Thông tin học kỳ</strong><span>Hiển thị và gắn vào dữ liệu xuất</span></div></div>
          <div className={styles.formGrid}>
            <label><span>Năm học</span><input value={form.academic_year} onChange={(event) => update("academic_year", event.target.value)} placeholder="2026-2027" /></label>
            <label><span>Học kỳ</span><select value={form.semester} onChange={(event) => update("semester", Number(event.target.value))}><option value={1}>Học kỳ 1</option><option value={2}>Học kỳ 2</option><option value={3}>Học kỳ hè</option></select></label>
            <label><span>Ngày bắt đầu</span><input type="date" value={form.semester_start ?? ""} onChange={(event) => update("semester_start", event.target.value || null)} /></label>
            <label><span>Ngày kết thúc</span><input type="date" value={form.semester_end ?? ""} onChange={(event) => update("semester_end", event.target.value || null)} /></label>
            <label><span>Trường/đơn vị</span><input value={form.institution} onChange={(event) => update("institution", event.target.value)} /></label>
            <label><span>Bộ môn</span><input value={form.department} onChange={(event) => update("department", event.target.value)} /></label>
          </div>
          <p className={styles.hint}>Ngày diễn ra từng buổi học vẫn lấy chính xác từ file phân công đã tải lên; khoảng học kỳ dùng để đối chiếu và mô tả.</p>
        </section>

        <section className={styles.settingsCard}>
          <div className={styles.cardTitle}><ShieldCheck size={20} /><div><strong>Cấu hình Calendar</strong><span>Tương thích Google, Outlook và Apple Calendar</span></div></div>
          <div className={styles.formStack}>
            <label><span>Tên lịch khi nhập</span><input value={form.calendar_name} onChange={(event) => update("calendar_name", event.target.value)} /></label>
            <label><span>Múi giờ</span><select value={form.timezone_name} onChange={(event) => update("timezone_name", event.target.value)}><option value="Asia/Ho_Chi_Minh">Asia/Ho_Chi_Minh (GMT+7)</option></select></label>
            <label><span>Giảng viên mặc định</span><select value={form.primary_lecturer ?? ""} onChange={(event) => update("primary_lecturer", event.target.value || null)}><option value="">Tự chọn người đầu tiên</option>{lecturers.map((item) => <option value={item.name} key={item.id}>{item.name}</option>)}</select></label>
          </div>
          <div className={styles.calendarStatus}>
            <span><ShieldCheck size={16} />Có UID ổn định, giờ GMT+7 và tên lịch theo học kỳ</span>
            <span><ShieldCheck size={16} />Xuất riêng lịch của từng giảng viên</span>
          </div>
          <a className={styles.googleLink} href={api.googleCalendarImportUrl} target="_blank" rel="noreferrer">Mở trang nhập lịch Google Calendar<ExternalLink size={15} /></a>
        </section>
      </div>
    </div>
  );
}
