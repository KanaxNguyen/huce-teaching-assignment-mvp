"use client";

import React, { useMemo, useState, useEffect, useCallback } from "react";
import {
  CalendarDays,
  Lock,
  MapPin,
  Search,
  User,
  X,
  ChevronDown,
  Layers,
  Sparkles,
  Clock,
  AlertTriangle,
  Calendar,
  AlertCircle,
} from "lucide-react";
import type { ClassItem, Lecturer, Session, Constraint, Seminar } from "@/src/types/api";
import styles from "./apple-calendar-view.module.css";

export interface ScheduledEvent {
  classItem: ClassItem;
  session: Session;
  uniqueKey: string;
}

export interface AppleCalendarViewProps {
  classes: ClassItem[];
  lecturers?: Lecturer[];
  constraints?: Constraint[];
  seminars?: Seminar[];
  selectedLecturerId?: number | null;
  onSelectLecturerId?: (id: number | null) => void;
  onInspectClass?: (item: ClassItem) => void;
}

// 7 Weekdays (Thứ 2 -> Chủ Nhật)
const WEEKDAYS = [
  { day: 2, shortName: "T2", fullName: "Thứ Hai" },
  { day: 3, shortName: "T3", fullName: "Thứ Ba" },
  { day: 4, shortName: "T4", fullName: "Thứ Tư" },
  { day: 5, shortName: "T5", fullName: "Thứ Năm" },
  { day: 6, shortName: "T6", fullName: "Thứ Sáu" },
  { day: 7, shortName: "T7", fullName: "Thứ Bảy" },
  { day: 8, shortName: "CN", fullName: "Chủ Nhật" },
];

// 5 Period Blocks (Ca học chuẩn Trường Đại học Xây dựng Hà Nội - HUCE)
const PERIOD_BLOCKS = [
  { start: 1, end: 3, ca: "Ca 1", name: "Sáng sớm", time: "06:45 – 09:10" },
  { start: 4, end: 6, ca: "Ca 2", name: "Sáng muộn", time: "09:30 – 11:55" },
  { start: 7, end: 9, ca: "Ca 3", name: "Đầu chiều", time: "12:30 – 14:55" },
  { start: 10, end: 12, ca: "Ca 4", name: "Cuối chiều", time: "15:15 – 17:40" },
  { start: 13, end: 15, ca: "Ca 5", name: "Tối", time: "18:00 – 20:25" },
];

// Format array of active weeks to readable range, e.g. [6, 7, 8, 9, 10] -> "Tuần 6–10"
export function formatActiveWeeks(activeWeeks?: number[]): string {
  if (!activeWeeks || activeWeeks.length === 0) return "";
  const sorted = Array.from(new Set(activeWeeks)).sort((a, b) => a - b);
  const ranges: string[] = [];
  let start = sorted[0];
  let end = sorted[0];

  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === end + 1) {
      end = sorted[i];
    } else {
      ranges.push(start === end ? `${start}` : `${start}–${end}`);
      start = sorted[i];
      end = sorted[i];
    }
  }
  ranges.push(start === end ? `${start}` : `${start}–${end}`);
  return `Tuần ${ranges.join(", ")}`;
}

// Deterministic color theme assignment (7 Apple-inspired palettes)
function getThemeIndex(courseId: number, courseCode: string): number {
  const seed = (courseId * 13) ^ (courseCode.charCodeAt(courseCode.length - 1) || 0);
  return Math.abs(seed) % 7;
}

// Slot analysis: Detect merged classes, alternating weeks, or real timetable collision
interface SlotAnalysis {
  relationship: "SINGLE" | "MERGED" | "ALTERNATING" | "COLLISION";
  mergedRoom?: string;
  conflictingWeeks?: number[];
}

function analyzeSlotEvents(events: ScheduledEvent[]): SlotAnalysis {
  if (events.length <= 1) return { relationship: "SINGLE" };

  // Check if all classes in the slot are merged (same course name, same room, valid room)
  const firstCourse = events[0].classItem.course_name;
  const firstRoom = events[0].session.room;
  const isSameCourseAndRoom =
    Boolean(firstRoom) &&
    events.every(
      (e) => e.classItem.course_name === firstCourse && e.session.room === firstRoom
    );

  if (isSameCourseAndRoom) {
    return { relationship: "MERGED", mergedRoom: firstRoom };
  }

  // Check week intersection
  // If no two classes share any active week -> Alternating (so le tuần)
  let hasOverlap = false;
  const overlappingWeeks = new Set<number>();

  for (let i = 0; i < events.length; i++) {
    const weeksA = events[i].session.active_weeks || [];
    for (let j = i + 1; j < events.length; j++) {
      const weeksB = events[j].session.active_weeks || [];
      const intersection = weeksA.filter((w) => weeksB.includes(w));
      if (intersection.length > 0) {
        hasOverlap = true;
        intersection.forEach((w) => overlappingWeeks.add(w));
      }
    }
  }

  if (!hasOverlap) {
    return { relationship: "ALTERNATING" };
  }

  return {
    relationship: "COLLISION",
    conflictingWeeks: Array.from(overlappingWeeks).sort((a, b) => a - b),
  };
}

export function AppleCalendarView({
  classes,
  lecturers = [],
  constraints = [],
  seminars = [],
  selectedLecturerId,
  onSelectLecturerId,
  onInspectClass,
}: AppleCalendarViewProps) {
  const [internalLecturerId, setInternalLecturerId] = useState<number | null>(
    selectedLecturerId ?? null
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [activeEvent, setActiveEvent] = useState<ScheduledEvent | null>(null);
  const [expandedSlots, setExpandedSlots] = useState<Record<string, boolean>>({});

  // Synchronize internal state with external prop if provided
  useEffect(() => {
    if (selectedLecturerId !== undefined) {
      setInternalLecturerId(selectedLecturerId);
    }
  }, [selectedLecturerId]);

  const handleLecturerChange = (newId: number | null) => {
    setInternalLecturerId(newId);
    onSelectLecturerId?.(newId);
  };

  // Close popover with Esc key
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") {
      setActiveEvent(null);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // Lecturer statistics for the dropdown
  const lecturerStats = useMemo(() => {
    const map = new Map<number, { count: number; credits: number; name: string }>();
    for (const c of classes) {
      if (c.lecturer_id) {
        const prev = map.get(c.lecturer_id) || { count: 0, credits: 0, name: c.lecturer || "" };
        map.set(c.lecturer_id, {
          count: prev.count + 1,
          credits: prev.credits + (c.credits || 0),
          name: c.lecturer || prev.name,
        });
      }
    }
    return map;
  }, [classes]);

  const [selectedWeek, setSelectedWeek] = useState<number | null>(null);

  // List of all available active weeks across all classes for week filter dropdown
  const availableWeeks = useMemo(() => {
    const set = new Set<number>();
    for (const c of classes) {
      for (const s of c.sessions) {
        if (s.active_weeks) {
          for (const w of s.active_weeks) {
            set.add(w);
          }
        }
      }
    }
    return Array.from(set).sort((a, b) => a - b);
  }, [classes]);

  // Calculate busy/seminar slots for selected lecturer
  const lecturerBusySlots = useMemo(() => {
    const map = new Map<string, { type: "SEMINAR" | "UNAVAILABLE"; label: string }>();
    if (internalLecturerId === null) return map;

    // 1. Seminars
    if (seminars && seminars.length > 0) {
      for (const sem of seminars) {
        if (sem.members && sem.members.includes(internalLecturerId)) {
          if (sem.slots) {
            for (const slot of sem.slots) {
              const day = Number(slot.weekday);
              const start = Number(slot.start_period);
              const end = Number(slot.end_period);
              const block = PERIOD_BLOCKS.find((b) => start <= b.end && end >= b.start);
              if (block && day) {
                map.set(`${day}-${block.start}`, {
                  type: "SEMINAR",
                  label: sem.name ? `Seminar: ${sem.name}` : "Seminar bộ môn",
                });
              }
            }
          }
        }
      }
    }

    // 2. Constraints (hard unavailable)
    if (constraints && constraints.length > 0) {
      for (const con of constraints) {
        if (con.lecturer_id === internalLecturerId && con.active) {
          const type = (con.constraint_type || "").toLowerCase();
          if (type === "unavailable" || (con.hardness === "hard" && type.includes("unavailable"))) {
            const target = con.target as Record<string, unknown> | undefined;
            const weekday = target?.weekday ? Number(target.weekday) : null;
            const periods = Array.isArray(target?.periods) ? (target.periods as number[]) : [];
            const startPeriod = target?.start_period
              ? Number(target.start_period)
              : periods[0] ?? null;
            const endPeriod = target?.end_period
              ? Number(target.end_period)
              : periods[periods.length - 1] ?? null;

            if (weekday && startPeriod && endPeriod) {
              const block = PERIOD_BLOCKS.find((b) => startPeriod <= b.end && endPeriod >= b.start);
              if (block) {
                map.set(`${weekday}-${block.start}`, {
                  type: "UNAVAILABLE",
                  label: con.name || "Bận lịch cá nhân",
                });
              }
            }
          }
        }
      }
    }

    return map;
  }, [internalLecturerId, constraints, seminars]);

  // Filter classes according to selected lecturer and search query (Strict ID matching, NO name fallback!)
  const filteredClasses = useMemo(() => {
    return classes.filter((item) => {
      // Strict filter by lecturer ID
      if (internalLecturerId !== null) {
        if (item.lecturer_id !== internalLecturerId) {
          return false;
        }
      }

      // Filter by search query
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase();
        const matchClass = item.class_code.toLowerCase().includes(q);
        const matchCourse =
          item.course_name.toLowerCase().includes(q) || item.course_code.toLowerCase().includes(q);
        const matchLecturer = item.lecturer?.toLowerCase().includes(q);
        const matchRoom = item.sessions.some((s) => s.room.toLowerCase().includes(q));
        if (!matchClass && !matchCourse && !matchLecturer && !matchRoom) {
          return false;
        }
      }

      return true;
    });
  }, [classes, internalLecturerId, searchQuery]);

  // Map events to slot keys: `${weekday}-${startPeriod}` (with optional Week Filter)
  const eventsBySlot = useMemo(() => {
    const map = new Map<string, ScheduledEvent[]>();
    for (const item of filteredClasses) {
      for (let sIdx = 0; sIdx < item.sessions.length; sIdx++) {
        const session = item.sessions[sIdx];

        // Filter by selected week if active
        if (selectedWeek !== null) {
          if (!session.active_weeks || !session.active_weeks.includes(selectedWeek)) {
            continue;
          }
        }

        const block = PERIOD_BLOCKS.find(
          (b) => session.start_period <= b.end && session.end_period >= b.start
        );
        if (block) {
          const key = `${session.weekday}-${block.start}`;
          const current = map.get(key) || [];
          current.push({
            classItem: item,
            session,
            uniqueKey: `${item.id}-${sIdx}-${session.weekday}-${session.start_period}`,
          });
          map.set(key, current);
        }
      }
    }
    return map;
  }, [filteredClasses, selectedWeek]);

  // Day count for header pills
  const sessionCountByDay = useMemo(() => {
    const counts: Record<number, number> = {};
    for (const w of WEEKDAYS) counts[w.day] = 0;
    for (const [key, events] of eventsBySlot.entries()) {
      const day = Number(key.split("-")[0]);
      if (counts[day] !== undefined) {
        counts[day] += events.length;
      }
    }
    return counts;
  }, [eventsBySlot]);

  // Total session count for toolbar
  const totalSessions = useMemo(() => {
    let sum = 0;
    for (const events of eventsBySlot.values()) {
      sum += events.length;
    }
    return sum;
  }, [eventsBySlot]);

  const toggleSlotExpansion = (slotKey: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedSlots((prev) => ({ ...prev, [slotKey]: !prev[slotKey] }));
  };

  return (
    <div className={styles.calendarContainer}>
      {/* 1. Control Toolbar */}
      <div className={styles.calendarToolbar}>
        <div className={styles.toolbarHeading}>
          <span className={styles.toolbarEyebrow}>
            <CalendarDays size={13} />
            Thời khóa biểu Apple Calendar
          </span>
          <h3 className={styles.toolbarTitle}>
            Lịch học theo ca & giảng viên
          </h3>
        </div>

        <div className={styles.toolbarActions}>
          {/* Quick Search */}
          <div className={styles.searchBox}>
            <Search size={14} />
            <input
              type="text"
              placeholder="Tìm môn, mã lớp, phòng…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: "inherit" }}
              >
                <X size={13} />
              </button>
            )}
          </div>

          {/* Week Filter Dropdown */}
          <div className={styles.weekSelectWrap}>
            <Calendar size={14} />
            <select
              value={selectedWeek ?? ""}
              onChange={(e) => setSelectedWeek(e.target.value ? Number(e.target.value) : null)}
              aria-label="Lọc theo tuần học"
            >
              <option value="">Tất cả các tuần ({availableWeeks.length} tuần)</option>
              {availableWeeks.map((w) => (
                <option key={w} value={w}>
                  Tuần {w}
                </option>
              ))}
            </select>
          </div>

          {/* Lecturer Selector */}
          <div className={styles.lecturerSelectWrap}>
            <User size={15} />
            <select
              value={internalLecturerId ?? ""}
              onChange={(e) => handleLecturerChange(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Tất cả giảng viên ({classes.length} lớp)</option>
              {lecturers
                .filter((l) => l.status !== "INACTIVE")
                .map((lec) => {
                  const stat = lecturerStats.get(lec.id);
                  return (
                    <option key={lec.id} value={lec.id}>
                      {lec.name} ({stat?.count ?? 0} lớp · {stat?.credits ?? 0} TC)
                    </option>
                  );
                })}
            </select>
          </div>

          {/* Stat Summary */}
          <span className={styles.statBadge}>
            <Sparkles size={13} />
            {totalSessions} buổi học
            {selectedWeek !== null && ` · Tuần ${selectedWeek}`}
          </span>
        </div>
      </div>

      {/* 2. Grid Table with Sticky Headers & Sticky Axis */}
      <div className={styles.calendarScrollWrap}>
        <div className={styles.calendarGrid}>
          {/* Top-Left Corner Cell */}
          <div className={styles.gridCorner}>
            <span>CA HỌC</span>
            <small style={{ fontWeight: 500, fontSize: "0.625rem" }}>TIẾT</small>
          </div>

          {/* Day Headers (Columns) */}
          {WEEKDAYS.map(({ day, shortName, fullName }) => {
            const count = sessionCountByDay[day] || 0;
            return (
              <div
                key={day}
                className={`${styles.dayHeader} ${count > 0 ? styles.dayHeaderActive : ""}`}
              >
                <span className={styles.dayNameShort}>{shortName}</span>
                <span className={styles.dayNameFull}>{fullName}</span>
                <span className={`${styles.dayCountPill} ${count > 0 ? styles.dayCountPillActive : ""}`}>
                  {count} buổi
                </span>
              </div>
            );
          })}

          {/* Period Rows */}
          {PERIOD_BLOCKS.map((block) => (
            <React.Fragment key={`row-${block.start}`}>
              {/* Left Time Column (Sticky) */}
              <div className={styles.timeAxisCell}>
                <span className={styles.caLabel}>{block.ca}</span>
                <span className={styles.periodBadge}>
                  Tiết {block.start}–{block.end}
                </span>
                <span className={styles.timeRangeText}>{block.time}</span>
              </div>

              {/* Day Cells */}
              {WEEKDAYS.map(({ day }) => {
                const slotKey = `${day}-${block.start}`;
                const events = eventsBySlot.get(slotKey) || [];
                const busyInfo = lecturerBusySlots.get(slotKey);
                const slotAnalysis = analyzeSlotEvents(events);
                const isExpanded = Boolean(expandedSlots[slotKey]);
                const visibleEvents =
                  isExpanded || events.length <= 2 ? events : events.slice(0, 2);
                const hiddenCount = events.length - visibleEvents.length;

                return (
                  <div key={slotKey} className={styles.calendarCell}>
                    {events.length === 0 ? (
                      busyInfo ? (
                        <div className={styles.busySlotCell}>
                          <span className={styles.busySlotBadge}>
                            {busyInfo.type === "SEMINAR" ? "🏛️ " : "⛔ "}
                            {busyInfo.label}
                          </span>
                          <span className={styles.busySlotDesc}>Khung giờ bận của giảng viên</span>
                        </div>
                      ) : (
                        <div className={styles.cellEmptyState}>Trống</div>
                      )
                    ) : (
                      <div className={styles.eventStack}>
                        {/* Slot-level relation banner when there are multiple classes */}
                        {slotAnalysis.relationship === "MERGED" && (
                          <div className={`${styles.slotRelationBanner} ${styles.relationMerged}`}>
                            <Layers size={11} />
                            <span>Lớp ghép · Cùng phòng {slotAnalysis.mergedRoom}</span>
                          </div>
                        )}
                        {slotAnalysis.relationship === "ALTERNATING" && (
                          <div className={`${styles.slotRelationBanner} ${styles.relationAlternating}`}>
                            <Clock size={11} />
                            <span>Dạy so le tuần · Không trùng giờ</span>
                          </div>
                        )}
                        {slotAnalysis.relationship === "COLLISION" && (
                          <div className={`${styles.slotRelationBanner} ${styles.relationCollision}`}>
                            <AlertTriangle size={11} />
                            <span>
                              ⚠️ Trùng lịch tuần: {slotAnalysis.conflictingWeeks?.join(", ")}
                            </span>
                          </div>
                        )}
                        {busyInfo && (
                          <div className={`${styles.slotRelationBanner} ${styles.relationCollision}`}>
                            <AlertCircle size={11} />
                            <span>⚠️ Trùng giờ bận: {busyInfo.label}</span>
                          </div>
                        )}

                        {visibleEvents.map((evt) => {
                          const { classItem, session, uniqueKey } = evt;
                          const themeIdx = getThemeIndex(classItem.course_id, classItem.course_code);
                          const isSelected = activeEvent?.uniqueKey === uniqueKey;
                          const formattedWeeks = formatActiveWeeks(session.active_weeks);
                          const isCollisionCard =
                            slotAnalysis.relationship === "COLLISION" || Boolean(busyInfo);

                          return (
                            <article
                              key={uniqueKey}
                              className={`${styles.eventCard} ${styles[`theme${themeIdx}`]} ${
                                isSelected ? styles.eventCardSelected : ""
                              } ${isCollisionCard ? styles.conflictCard : ""}`}
                              tabIndex={0}
                              role="button"
                              aria-label={`${classItem.course_name}, lớp ${classItem.class_code}`}
                              onClick={() => {
                                setActiveEvent(evt);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  setActiveEvent(evt);
                                }
                              }}
                            >
                              <span className={styles.cardAccentBar} />
                              <div className={styles.cardTopRow}>
                                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                  <span className={styles.classBadge}>{classItem.class_code}</span>
                                  {slotAnalysis.relationship === "MERGED" && (
                                    <span className={`${styles.tagPill} ${styles.tagMerged}`}>Ghép</span>
                                  )}
                                  {slotAnalysis.relationship === "ALTERNATING" && (
                                    <span className={`${styles.tagPill} ${styles.tagAlternating}`}>So le</span>
                                  )}
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                  {classItem.locked_assignment && (
                                    <span className={styles.lockIndicator} title="Đã khóa phân công">
                                      <Lock size={12} />
                                    </span>
                                  )}
                                  {session.room && (
                                    <span className={styles.roomTag} title={`Phòng: ${session.room}`}>
                                      <MapPin size={10} />
                                      {session.room}
                                    </span>
                                  )}
                                </div>
                              </div>

                              <strong className={styles.courseTitle} title={classItem.course_name}>
                                {classItem.course_name}
                              </strong>

                              <div className={styles.cardBottomRow}>
                                <span
                                  className={`${styles.lecturerName} ${
                                    classItem.lecturer ? styles.lecturerNameAssigned : ""
                                  }`}
                                  title={classItem.lecturer ?? "Chưa phân công"}
                                >
                                  <User size={11} />
                                  {classItem.lecturer ? classItem.lecturer : "Chưa phân công"}
                                </span>
                                {formattedWeeks && (
                                  <span className={styles.weekBadge} title={`Lịch tuần: ${formattedWeeks}`}>
                                    <Clock size={10} />
                                    {formattedWeeks}
                                  </span>
                                )}
                              </div>
                            </article>
                          );
                        })}

                        {hiddenCount > 0 && (
                          <button
                            type="button"
                            className={styles.moreClassesToggle}
                            onClick={(e) => toggleSlotExpansion(slotKey, e)}
                          >
                            <ChevronDown size={12} />+ {hiddenCount} lớp khác
                          </button>
                        )}
                        {isExpanded && events.length > 2 && (
                          <button
                            type="button"
                            className={styles.moreClassesToggle}
                            onClick={(e) => toggleSlotExpansion(slotKey, e)}
                          >
                            Thu gọn ({events.length})
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* 3. Apple Calendar Event Detail Popover / Modal */}
      {activeEvent && (
        <div className={styles.popoverBackdrop} onClick={() => setActiveEvent(null)}>
          <div
            className={styles.detailPopover}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            {/* Top theme color indicator bar */}
            <div
              className={styles.popoverHeaderBar}
              style={{
                background: [
                  "#2563eb",
                  "#059669",
                  "#7c3aed",
                  "#d97706",
                  "#e11d48",
                  "#0d9488",
                  "#4f46e5",
                ][getThemeIndex(activeEvent.classItem.course_id, activeEvent.classItem.course_code)],
              }}
            />

            <div className={styles.popoverHeader}>
              <div className={styles.popoverTitleGroup}>
                <div className={styles.popoverBadgeRow}>
                  <span
                    className={styles.classBadge}
                    style={{
                      background: "var(--color-primary-soft)",
                      color: "var(--color-primary)",
                      padding: "2px 8px",
                      fontSize: "0.75rem",
                    }}
                  >
                    {activeEvent.classItem.class_code}
                  </span>
                  <span style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)", fontWeight: 600 }}>
                    Mã môn: {activeEvent.classItem.course_code}
                  </span>
                </div>
                <h4 className={styles.popoverTitle}>{activeEvent.classItem.course_name}</h4>
              </div>

              <button
                type="button"
                className={styles.closeButton}
                onClick={() => setActiveEvent(null)}
                aria-label="Đóng chi tiết"
              >
                <X size={16} />
              </button>
            </div>

            <div className={styles.popoverBody}>
              {/* Lecturer Info Card */}
              <div className={styles.lecturerCard}>
                <div className={styles.lecturerAvatar}>
                  {activeEvent.classItem.lecturer
                    ? activeEvent.classItem.lecturer
                        .split(" ")
                        .slice(-1)[0]
                        .charAt(0)
                        .toUpperCase()
                    : "?"}
                </div>
                <div className={styles.lecturerDetails}>
                  <span className={styles.lecturerTitle}>Giảng viên phụ trách</span>
                  <strong className={styles.lecturerFullName}>
                    {activeEvent.classItem.lecturer ?? "Chưa phân công"}
                  </strong>
                  <span style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)" }}>
                    Nguồn: {activeEvent.classItem.assignment_source ?? (activeEvent.classItem.lecturer ? "IMPORT" : "SOLVER")}
                    {activeEvent.classItem.locked_assignment ? " · Đã khóa (Locked)" : ""}
                  </span>
                </div>
              </div>

              {/* Grid of Key Properties */}
              <div className={styles.popoverGrid}>
                <div className={styles.infoBlock}>
                  <span className={styles.infoLabel}>Thời gian & Khung tiết</span>
                  <span className={styles.infoValue}>
                    {WEEKDAYS.find((w) => w.day === activeEvent.session.weekday)?.fullName} · Tiết{" "}
                    {activeEvent.session.start_period}–{activeEvent.session.end_period}
                  </span>
                </div>

                <div className={styles.infoBlock}>
                  <span className={styles.infoLabel}>Phòng học</span>
                  <span className={styles.infoValue}>
                    {activeEvent.session.room || "Chưa xếp phòng"}
                  </span>
                </div>

                <div className={styles.infoBlock}>
                  <span className={styles.infoLabel}>Số tín chỉ</span>
                  <span className={styles.infoValue}>{activeEvent.classItem.credits} TC</span>
                </div>

                <div className={styles.infoBlock}>
                  <span className={styles.infoLabel}>Tuần học</span>
                  <span className={styles.infoValue}>
                    {formatActiveWeeks(activeEvent.session.active_weeks) ||
                      activeEvent.session.raw_weeks ||
                      "Toàn kỳ"}
                  </span>
                </div>
              </div>

              {activeEvent.classItem.merged_group_id && (
                <div
                  style={{
                    padding: "8px 12px",
                    background: "var(--color-surface-muted)",
                    borderRadius: 8,
                    fontSize: "0.75rem",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    color: "var(--color-text)",
                  }}
                >
                  <Layers size={14} style={{ color: "var(--color-primary)" }} />
                  <span>
                    Lớp ghép: <strong>{activeEvent.classItem.merged_group_id}</strong>
                  </span>
                </div>
              )}

              <div className={styles.popoverFooter}>
                <button
                  type="button"
                  style={{
                    padding: "6px 14px",
                    background: "var(--color-surface-muted)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 8,
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    color: "var(--color-text)",
                  }}
                  onClick={() => setActiveEvent(null)}
                >
                  Đóng
                </button>
                {onInspectClass && (
                  <button
                    type="button"
                    style={{
                      padding: "6px 14px",
                      background: "var(--color-primary)",
                      color: "white",
                      border: "none",
                      borderRadius: 8,
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                    onClick={() => {
                      const itemToInspect = activeEvent.classItem;
                      setActiveEvent(null);
                      onInspectClass(itemToInspect);
                    }}
                  >
                    Xem ứng viên & Chỉnh phân công
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Keep CalendarPreview backward-compatible
export function CalendarPreview({ classes }: { classes: ClassItem[] }) {
  return <AppleCalendarView classes={classes} />;
}
