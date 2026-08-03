"use client";

import { CalendarPlus, ChevronDown, Clipboard, Download, ExternalLink, FileJson, Sheet, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/src/services/api";
import type { AppSettings, ClassItem } from "@/src/types/api";
import dashboardStyles from "@/src/features/dashboard/dashboard.module.css";

import styles from "./calendar-view.module.css";

const DAYS = [2, 3, 4, 5, 6, 7, 8];
const PERIODS = Array.from({ length: 15 }, (_, index) => index + 1);
const CLOCKS: Record<number, string> = {
  1: "07:00", 2: "07:50", 3: "08:40", 4: "09:35", 5: "10:25",
  6: "11:15", 7: "13:00", 8: "13:50", 9: "14:40", 10: "15:35",
  11: "16:25", 12: "17:15", 13: "18:00", 14: "18:50", 15: "19:40",
};
const EVENT_TONES = ["blue", "violet", "green", "orange", "rose"] as const;

function toneFor(value: string) {
  const score = Array.from(value).reduce((sum, character) => sum + character.charCodeAt(0), 0);
  return EVENT_TONES[score % EVENT_TONES.length];
}

export function CalendarView({ classes, settings }: { classes: ClassItem[]; settings: AppSettings }) {
  const assigned = useMemo(() => classes.filter((item) => item.lecturer), [classes]);
  const calendarItems = useMemo(() => {
    const grouped = new Map<string, ClassItem>();
    assigned.forEach((item) => {
      const key = `${item.lecturer}:${item.merged_group_id ?? `class-${item.id}`}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.class_code = [existing.class_code, item.class_code].sort((a, b) => a.localeCompare(b, "vi")).join(" + ");
      } else {
        grouped.set(key, { ...item });
      }
    });
    return Array.from(grouped.values());
  }, [assigned]);
  const lecturers = useMemo(
    () => Array.from(new Set(assigned.map((item) => item.lecturer as string))).sort((a, b) => a.localeCompare(b, "vi")),
    [assigned],
  );
  const [selected, setSelected] = useState(settings.primary_lecturer ?? "");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const activeLecturer = lecturers.includes(selected) ? selected : (lecturers[0] ?? "");

  const events = useMemo(
    () => calendarItems
      .filter((item) => item.lecturer === activeLecturer)
      .flatMap((item) => item.sessions.map((session, index) => ({ item, session, key: `${item.id}-${index}` }))),
    [activeLecturer, calendarItems],
  );

  async function copyCalendarLink() {
    const calendarUrl = api.calendarUrl(activeLecturer || undefined);
    let copied = false;
    try {
      await navigator.clipboard?.writeText(calendarUrl);
      copied = Boolean(navigator.clipboard?.writeText);
    } catch {
      // Some embedded browsers expose the API but block it at runtime.
    }
    if (!copied) {
      const temporaryInput = document.createElement("textarea");
      try {
        temporaryInput.value = calendarUrl;
        temporaryInput.style.position = "fixed";
        temporaryInput.style.opacity = "0";
        document.body.appendChild(temporaryInput);
        temporaryInput.select();
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      } finally {
        temporaryInput.remove();
      }
    }
    if (copied) {
      setCopyStatus("copied");
    } else {
      setCopyStatus("failed");
    }
    window.setTimeout(() => setCopyStatus("idle"), 2200);
  }

  return (
    <div className={dashboardStyles.viewStack}>
      <section className={dashboardStyles.sectionHeading}>
        <div>
          <span className={dashboardStyles.eyebrow}>Lịch tuần trực quan</span>
          <h2>Thời khóa biểu giảng viên</h2>
          <p>Lưới 15 tiết theo tuần, thiết kế tương tự Google Calendar và lọc riêng từng giảng viên.</p>
        </div>
        <label className={dashboardStyles.selectBox}>
          <Users size={17} />
          <select value={activeLecturer} onChange={(event) => setSelected(event.target.value)}>
            <option value="">Chọn giảng viên</option>
            {lecturers.map((name) => <option key={name}>{name}</option>)}
          </select>
          <ChevronDown size={16} />
        </label>
      </section>

      <section className={styles.calendarShell} aria-label={`Lịch tuần của ${activeLecturer || "giảng viên"}`}>
        <div className={styles.calendarMeta}>
          <div><strong>HK{settings.semester} · {settings.academic_year}</strong><span>{events.length} buổi học trong lịch mẫu</span></div>
          {activeLecturer && <a className={dashboardStyles.secondaryButton} href={api.calendarUrl(activeLecturer)}><CalendarPlus size={17} />Tải ICS cho Google Calendar</a>}
        </div>
        <div className={styles.calendarScroll}>
          <div className={styles.timeGrid}>
            <div className={styles.cornerCell}>GMT+7</div>
            {DAYS.map((day, index) => (
              <div className={styles.dayHeader} style={{ gridColumn: index + 2 }} key={day}>
                <strong>{day === 8 ? "CN" : `T${day}`}</strong>
                <span>{events.filter((event) => event.session.weekday === day).length} buổi</span>
              </div>
            ))}
            {PERIODS.map((period) => (
              <div className={styles.periodLabel} style={{ gridRow: period + 1 }} key={period}>
                <strong>Tiết {period}</strong><span>{CLOCKS[period]}</span>
              </div>
            ))}
            {DAYS.flatMap((day, dayIndex) => PERIODS.map((period) => (
              <div className={styles.gridCell} style={{ gridColumn: dayIndex + 2, gridRow: period + 1 }} key={`${day}-${period}`} />
            )))}
            {events.map(({ item, session, key }) => (
              <article
                className={`${styles.calendarEvent} ${styles[toneFor(item.course_code)]}`}
                style={{
                  gridColumn: DAYS.indexOf(session.weekday) + 2,
                  gridRow: `${session.start_period + 1} / ${session.end_period + 2}`,
                }}
                title={`${item.course_name} · ${item.class_code} · ${session.room}`}
                key={key}
              >
                <span>Tiết {session.start_period}–{session.end_period}</span>
                <strong>{item.course_name}</strong>
                <small>{item.class_code} · {session.room || "Chưa có phòng"}</small>
              </article>
            ))}
          </div>
        </div>
        {!activeLecturer && <div className={styles.emptyCalendar}>Chọn giảng viên để xem lịch.</div>}
      </section>

      <section className={styles.integrationPanel}>
        <div className={styles.integrationIntro}>
          <span className={dashboardStyles.eyebrow}>Kết nối hệ thống khác</span>
          <h3>Xuất và chia sẻ dữ liệu</h3>
          <p>ICS dùng cho Google Calendar, Outlook hoặc Apple Calendar. CSV và JSON dùng để chuyển dữ liệu sang khoa, phòng đào tạo hoặc hệ thống khác.</p>
        </div>
        <div className={styles.exportActions}>
          <a href={api.calendarUrl(activeLecturer || undefined)}><CalendarPlus size={19} /><span><strong>Xuất ICS</strong><small>Lịch chuẩn calendar</small></span><Download size={16} /></a>
          <a href={api.csvUrl(activeLecturer || undefined)}><Sheet size={19} /><span><strong>Xuất CSV</strong><small>Dùng cho Excel/hệ thống khác</small></span><Download size={16} /></a>
          <a href={api.jsonUrl(activeLecturer || undefined)}><FileJson size={19} /><span><strong>Xuất JSON</strong><small>Dữ liệu tích hợp có cấu trúc</small></span><Download size={16} /></a>
          <button type="button" onClick={() => void copyCalendarLink()} aria-live="polite"><Clipboard size={19} /><span><strong>{copyStatus === "copied" ? "Đã sao chép" : copyStatus === "failed" ? "Không thể sao chép" : "Sao chép link ICS"}</strong><small>{copyStatus === "failed" ? "Trình duyệt đang chặn clipboard" : "Dùng đăng ký lịch sau khi deploy"}</small></span></button>
          <a href={api.googleCalendarImportUrl} target="_blank" rel="noreferrer"><ExternalLink size={19} /><span><strong>Mở Google Calendar</strong><small>Vào mục Nhập và xuất</small></span><ExternalLink size={16} /></a>
        </div>
      </section>
    </div>
  );
}
