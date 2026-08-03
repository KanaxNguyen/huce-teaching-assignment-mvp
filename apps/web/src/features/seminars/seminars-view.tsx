"use client";

import { CalendarClock, Crown, Settings2, UsersRound } from "lucide-react";

import type { OptimizationRun, Seminar } from "@/src/types/api";
import dashboardStyles from "@/src/features/dashboard/dashboard.module.css";

import styles from "./seminars-view.module.css";

function dayLabel(day: number) {
  return day === 8 ? "Chủ Nhật" : `Thứ ${day}`;
}

export function SeminarsView({
  seminars,
  runs,
  busy,
  onUpdate,
}: {
  seminars: Seminar[];
  runs: OptimizationRun[];
  busy: string | null;
  onUpdate: (id: number, payload: Record<string, unknown>) => void;
}) {
  const selectedSlots = runs[0]?.summary.seminar_slots ?? {};
  return (
    <div className={dashboardStyles.viewStack}>
      <section className={dashboardStyles.sectionHeading}>
        <div>
          <span className={dashboardStyles.eyebrow}>Sinh hoạt chuyên môn</span>
          <h2>Seminar và khung giờ chung</h2>
          <p>Quản lý người tham gia, phương án thời gian và trọng số khi tối ưu lịch giảng.</p>
        </div>
      </section>
      <div className={dashboardStyles.infoStrip}>
        <CalendarClock size={19} />
        <span>Hệ thống tự chọn một phương án thời gian cho mỗi seminar và tính xung đột như ràng buộc mềm hoặc cứng.</span>
      </div>
      <section className={styles.grid}>
        {seminars.map((seminar) => {
          const selected = selectedSlots[seminar.name];
          return (
            <article className={dashboardStyles.card} key={seminar.id}>
              <div className={styles.cardTop}>
                <span className={styles.icon}><UsersRound size={20} /></span>
                <div><span className={dashboardStyles.cardEyebrow}>Nhóm seminar</span><h3>{seminar.name}</h3></div>
                <span className={`${dashboardStyles.badge} ${seminar.hardness === "hard" ? dashboardStyles.danger : dashboardStyles.warning}`}>
                  {seminar.hardness === "hard" ? "Cứng" : "Mềm"}
                </span>
              </div>
              <div className={styles.body}>
                <div className={styles.chair}><Crown size={16} /><span><small>Chủ trì</small><strong>{seminar.chair_name}</strong></span></div>
                <div className={styles.members}>
                  <small>{seminar.members.length} thành viên</small>
                  <p>{seminar.members.join(" · ")}</p>
                </div>
                <div className={styles.slots}>
                  {seminar.alternatives.map((slot) => {
                    const active = selected?.weekday === slot.weekday && selected.start_period === slot.start_period;
                    return <span className={active ? styles.selectedSlot : ""} key={`${slot.weekday}-${slot.start_period}`}>{dayLabel(slot.weekday)} · tiết {slot.start_period}–{slot.end_period}</span>;
                  })}
                </div>
                {selected && <div className={styles.selected}><CalendarClock size={16} /><span>Phương án gần nhất: <strong>{dayLabel(selected.weekday)}, tiết {selected.start_period}–{selected.end_period}</strong></span></div>}
              </div>
              <div className={styles.controls}>
                <label><Settings2 size={15} /><span>Mức độ</span><select value={seminar.hardness} disabled={!!busy} onChange={(event) => onUpdate(seminar.id, { hardness: event.target.value })}><option value="soft">Mềm</option><option value="hard">Cứng</option></select></label>
                <label><span>Trọng số</span><select value={seminar.weight.toFixed(1)} disabled={!!busy || seminar.hardness === "hard"} onChange={(event) => onUpdate(seminar.id, { weight: Number(event.target.value) })}>{Array.from({ length: 11 }, (_, index) => (index / 10).toFixed(1)).map((value) => <option key={value}>{value}</option>)}</select></label>
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}
