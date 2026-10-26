"use client";

import { AlertTriangle, ArrowRight, Check, GripVertical, LoaderCircle, Lock, Search, ShieldAlert, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/src/services/api";
import type { CandidateAnalysisItem, ClassItem, Lecturer, Precheck, ResolutionScenario, ResolutionScenarios, ScenarioOption } from "@/src/types/api";

import styles from "./resolution-tools.module.css";

const DAYS = [2, 3, 4, 5, 6, 7, 8];
const BLOCKS: Array<[number, number, string]> = [[1, 3, "Ca 1"], [4, 6, "Ca 2"], [7, 9, "Ca 3"], [10, 12, "Ca 4"], [13, 15, "Ca 5"]];
const dayLabel = (day: number) => (day === 8 ? "CN" : `T${day}`);
const blockOf = (start: number, end: number) => BLOCKS.flatMap(([from, to], index) => (start <= to && end >= from ? [index] : []));

/* ------------------------------------------------------------------ */
/* Pre-solve check: proven problems + a weekday × period heatmap        */
/* ------------------------------------------------------------------ */

export function PrecheckPanel({ report, loading, onOpenClass, onRefresh }: {
  report: Precheck | null;
  loading: boolean;
  onOpenClass: (classId: number) => void;
  onRefresh: () => void;
}) {
  if (!report) {
    return <div className={styles.panel}>{loading ? <><LoaderCircle size={16} className={styles.spin} /> Đang kiểm tra dữ liệu trước khi chạy…</> : "Chưa kiểm tra được dữ liệu."}</div>;
  }
  const cells = new Map(report.heatmap.map((cell) => [`${cell.weekday}-${cell.block}`, cell]));
  const days = DAYS.filter((day) => report.heatmap.some((cell) => cell.weekday === day));
  const tone = report.status === "blocking" ? styles.toneBlock : report.status === "warning" ? styles.toneWarn : styles.toneOk;
  return (
    <section className={`${styles.panel} ${tone}`} aria-label="Kiểm tra trước khi chạy">
      <header className={styles.panelHeader}>
        <div>
          <span className={styles.eyebrow}>KIỂM TRA TRƯỚC KHI CHẠY</span>
          <strong>
            {report.status === "blocking" ? "Có lỗi khiến không thể chạy phân công"
              : report.estimated_min_unassigned > 0 ? `Chắc chắn còn ít nhất ${report.estimated_min_unassigned} lớp không xếp được với dữ liệu hiện tại`
              : "Không phát hiện điểm bất khả thi nào"}
          </strong>
          <small>Chỉ dựa trên ràng buộc cứng (năng lực, lịch bận cứng, lớp đã khóa, trùng giờ) — đây là giới hạn chắc chắn, không phải dự đoán.</small>
        </div>
        <button type="button" className={styles.ghostButton} onClick={onRefresh} disabled={loading}>{loading ? <LoaderCircle size={14} className={styles.spin} /> : null}Kiểm tra lại</button>
      </header>
      <div className={styles.precheckBody}>
        <ul className={styles.findings}>
          {report.items.length ? report.items.map((item, index) => (
            <li key={`${item.code}-${index}`} className={styles[`sev_${item.severity}`]}>
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
              {item.suggestion ? <em>Cách xử lý: {item.suggestion}</em> : null}
              {item.class_ids.length ? (
                <div className={styles.chipRow}>
                  {item.class_ids.slice(0, 8).map((id, chip) => <button type="button" key={id} className={styles.classChip} onClick={() => onOpenClass(id)}>{item.class_codes[chip] ?? id}</button>)}
                  {item.class_ids.length > 8 ? <span className={styles.more}>+{item.class_ids.length - 8}</span> : null}
                </div>
              ) : null}
            </li>
          )) : <li className={styles.sev_info}><strong>Dữ liệu sạch</strong><span>Không có lớp nào chắc chắn bị bỏ trống do thiếu giảng viên.</span></li>}
        </ul>
        {days.length ? (
          <div className={styles.heatWrap}>
            <span className={styles.heatTitle}>Độ căng giảng viên theo ca (lớp học cùng lúc / giảng viên đủ điều kiện)</span>
            <table className={styles.heatmap}>
              <thead><tr><th />{days.map((day) => <th key={day}>{dayLabel(day)}</th>)}</tr></thead>
              <tbody>{BLOCKS.map(([, , label], block) => (
                <tr key={label}><th>{label}</th>{days.map((day) => {
                  const cell = cells.get(`${day}-${block}`);
                  if (!cell) return <td key={day} className={styles.heatEmpty}>·</td>;
                  const ratio = cell.capable ? cell.demand / cell.capable : 1;
                  const level = cell.deficit > 0 ? "heatShort" : ratio >= 0.85 ? "heatTight" : ratio >= 0.6 ? "heatBusy" : "heatCalm";
                  return <td key={day} className={styles[level]} title={`${dayLabel(day)} ${label}: ${cell.demand} lớp cùng lúc, ${cell.capable} giảng viên đủ điều kiện${cell.deficit ? `, thiếu ${cell.deficit}` : ""}`}>{cell.deficit > 0 ? `−${cell.deficit}` : `${cell.demand}/${cell.capable}`}</td>;
                })}</tr>
              ))}</tbody>
            </table>
            <div className={styles.legend}><span className={styles.heatCalm}>thoải mái</span><span className={styles.heatBusy}>khá đông</span><span className={styles.heatTight}>sát ngưỡng</span><span className={styles.heatShort}>thiếu GV</span></div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Scenario dialog: who could teach, what it bends, who must approve   */
/* ------------------------------------------------------------------ */

export function ScenarioDialog({ classId, semesterId, focusLecturerId, onClose, onApplied, onMerge }: {
  classId: number;
  semesterId: number;
  focusLecturerId?: number | null;
  onClose: () => void;
  onApplied: (message: string) => void;
  onMerge: (classIds: number[]) => Promise<unknown> | void;
}) {
  const [data, setData] = useState<ResolutionScenarios | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ scenario: ResolutionScenario; option: ScenarioOption | null } | null>(null);
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    setData(null); setError(null); setSelected(null);
    api.scenarios(classId, semesterId)
      .then((result) => {
        if (!current) return;
        setData(result);
        // Dropping a class on a lecturer opens straight onto the scenario that covers that lecturer.
        const focused = focusLecturerId
          ? result.scenarios.flatMap((scenario) => scenario.options.filter((option) => option.lecturer_id === focusLecturerId).map((option) => ({ scenario, option })))[0]
          : undefined;
        const recommended = result.scenarios.find((scenario) => scenario.key === result.recommended);
        setSelected(focused ?? (recommended ? { scenario: recommended, option: recommended.options[0] ?? null } : null));
      })
      .catch((reason: unknown) => { if (current) setError(reason instanceof Error ? reason.message : "Không tải được kịch bản."); });
    return () => { current = false; };
  }, [classId, semesterId, focusLecturerId]);

  useEffect(() => {
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const focusMissing = Boolean(focusLecturerId && data && !data.scenarios.some((scenario) => scenario.options.some((option) => option.lecturer_id === focusLecturerId)));
  const needsApproval = Boolean(selected && selected.scenario.level >= 2);
  const canApply = Boolean(selected && !busy && (selected.scenario.key === "escalate" || selected.option)
    && (!needsApproval || (approver.trim() && reason.trim().length >= 5)));

  async function apply() {
    if (!selected || !canApply) return;
    setBusy(true); setError(null);
    try {
      const { scenario, option } = selected;
      if (scenario.key === "merge" && option?.merge_with_class_id) {
        await onMerge([classId, option.merge_with_class_id]);
        onApplied(`Đã ghép ${data?.class.class_code} với ${option.merge_with_class_code}. Chạy lại phân công để áp dụng.`);
      } else {
        await api.applyScenario(classId, semesterId, { scenario: scenario.key, lecturer_id: option?.lecturer_id, approver: approver.trim(), reason: reason.trim() });
        onApplied(scenario.key === "escalate"
          ? `Đã chuyển lớp ${data?.class.class_code} cho ${scenario.authority.approver} xử lý.`
          : `Đã giao ${data?.class.class_code} cho ${option?.lecturer_name} (${scenario.title.toLowerCase()}).`);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không áp dụng được kịch bản.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-label="Kịch bản xử lý lớp chưa phân" tabIndex={-1} ref={dialogRef} onClick={(event) => event.stopPropagation()}>
        <header className={styles.dialogHeader}>
          <div>
            <span className={styles.eyebrow}>KỊCH BẢN XỬ LÝ</span>
            <h3>{data ? `${data.class.class_code} · ${data.class.course_name}` : "Đang phân tích…"}</h3>
            {data ? <small>{data.class.sessions.map((s) => `${dayLabel(s.weekday)} tiết ${s.start_period}–${s.end_period}${s.room ? ` · ${s.room}` : ""}`).join(" · ")}</small> : null}
          </div>
          <button type="button" className={styles.iconButton} aria-label="Đóng" onClick={onClose}><X size={18} /></button>
        </header>
        {error ? <p className={styles.errorLine} role="alert">{error}</p> : null}
        {!data && !error ? <div className={styles.loadingLine}><LoaderCircle size={16} className={styles.spin} />Đang thử từng giảng viên với mọi ràng buộc…</div> : null}
        {data ? (
          <div className={styles.dialogBody}>
            <ol className={styles.ladder} aria-label="Thang thẩm quyền">
              {data.authority_ladder.map((step) => (
                <li key={step.level} className={selected?.scenario.level === step.level ? styles.ladderActive : ""}>
                  <b>{step.level}</b><span>{step.approver}</span>
                </li>
              ))}
            </ol>
            {data.why_blocked.length ? (
              <details className={styles.why}>
                <summary>Vì sao solver không xếp được lớp này?</summary>
                <ul>{data.why_blocked.map((row) => <li key={row.reason}><strong>{row.lecturers.length} GV {row.reason}:</strong> {row.lecturers.slice(0, 8).join(", ")}{row.lecturers.length > 8 ? "…" : ""}</li>)}</ul>
              </details>
            ) : null}
            {focusMissing ? <p className={styles.errorLine}>Giảng viên vừa thả vào không thể nhận lớp này theo bất kỳ kịch bản nào (thường do trùng lịch dạy). Chọn một phương án bên dưới.</p> : null}
            <div className={styles.scenarioList}>
              {data.scenarios.filter((scenario) => scenario.available).map((scenario) => (
                <article key={scenario.key} className={`${styles.scenario} ${selected?.scenario.key === scenario.key ? styles.scenarioActive : ""}`}>
                  <header>
                    <span className={`${styles.levelBadge} ${styles[`level${scenario.level}`]}`}>Cấp {scenario.level}</span>
                    <div><strong>{scenario.title}</strong><small>Phê duyệt: {scenario.authority.approver}</small></div>
                  </header>
                  <p>{scenario.summary}</p>
                  {scenario.key === "escalate" ? (
                    <button type="button" className={styles.optionButton} aria-pressed={selected?.scenario.key === "escalate"} onClick={() => setSelected({ scenario, option: null })}>Chọn kịch bản này</button>
                  ) : scenario.options.map((option) => {
                    const active = selected?.scenario.key === scenario.key && selected.option?.lecturer_id === option.lecturer_id && selected.option?.merge_with_class_id === option.merge_with_class_id;
                    return (
                      <button type="button" key={`${option.lecturer_id}-${option.merge_with_class_id ?? ""}`} className={`${styles.optionButton} ${active ? styles.optionActive : ""}`} aria-pressed={active} onClick={() => setSelected({ scenario, option })}>
                        <span className={styles.optionName}>{option.lecturer_name}{option.lecturer_code ? <small> · {option.lecturer_code}</small> : null}</span>
                        <span className={styles.optionLoad}>{option.load.classes} lớp · {option.load.credits} TC</span>
                        {option.moves.map((move) => <span key={move.class_id} className={styles.move}>Chuyển {move.class_code}: {move.from_lecturer} <ArrowRight size={11} /> {move.to_lecturer}</span>)}
                        {option.bends.length ? <span className={styles.bends}><ShieldAlert size={12} /> Vượt: {option.bends.join(", ")}</span> : null}
                        {option.note ? <span className={styles.note}>{option.note}</span> : null}
                      </button>
                    );
                  })}
                </article>
              ))}
            </div>
          </div>
        ) : null}
        {selected ? (
          <footer className={styles.dialogFooter}>
            {needsApproval ? (
              <div className={styles.approval}>
                <label><span>Người phê duyệt ({selected.scenario.authority.approver}) *</span><input value={approver} onChange={(event) => setApprover(event.target.value)} placeholder="Họ tên người phê duyệt" /></label>
                <label><span>Lý do / căn cứ *</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="VD: GV đã đồng ý qua email ngày 26/10" /></label>
                <small>Quyết định được ghi vào nhật ký kiểm toán và lớp sẽ được khóa để solver không đổi lại.</small>
              </div>
            ) : selected.scenario.key === "escalate" ? (
              <div className={styles.approval}><label><span>Ghi chú gửi kèm</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="VD: đề nghị dời lớp sang Thứ 6 ca 2" /></label></div>
            ) : <small className={styles.footerHint}>Trong quyền Trưởng bộ môn — không vi phạm ràng buộc cứng nào.</small>}
            <div className={styles.footerActions}>
              <button type="button" className={styles.ghostButton} onClick={onClose}>Đóng</button>
              <button type="button" className={styles.primaryButton} disabled={!canApply} onClick={() => void apply()}>
                {busy ? <LoaderCircle size={15} className={styles.spin} /> : <Check size={15} />}
                {selected.scenario.key === "escalate" ? "Chuyển xử lý" : selected.scenario.key === "merge" ? "Ghép lớp" : "Áp dụng"}
              </button>
            </div>
          </footer>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Drag-and-drop board with a live per-lecturer week view              */
/* ------------------------------------------------------------------ */

type DropVerdict = "ok" | "approval" | "clash";

export function AssignmentBoard({ classes, lecturers, semesterId, busy, onAssign, onOpenScenarios }: {
  classes: ClassItem[];
  lecturers: Lecturer[];
  semesterId: number;
  busy: boolean;
  onAssign: (classId: number, lecturerId: number) => void;
  onOpenScenarios: (classId: number, lecturerId?: number) => void;
}) {
  const [dragging, setDragging] = useState<ClassItem | null>(null);
  const [picked, setPicked] = useState<ClassItem | null>(null);
  const [hoverLecturer, setHoverLecturer] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<Record<number, Record<number, CandidateAnalysisItem>>>({});
  const [loadingClass, setLoadingClass] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [lecturerQuery, setLecturerQuery] = useState("");
  const active = dragging ?? picked;

  // Assignments change after every drop; cached verdicts must not outlive them.
  const assignmentKey = classes.map((item) => `${item.id}:${item.lecturer_id ?? ""}`).join(",");
  useEffect(() => { setAnalysis({}); }, [assignmentKey]);

  const loadAnalysis = (item: ClassItem) => {
    if (analysis[item.id] || loadingClass === item.id) return;
    setLoadingClass(item.id);
    api.candidateAnalysis(item.id, semesterId)
      .then((rows) => setAnalysis((current) => ({ ...current, [item.id]: Object.fromEntries(rows.map((row) => [row.lecturer_id, row])) })))
      .catch(() => setAnalysis((current) => ({ ...current, [item.id]: {} })))
      .finally(() => setLoadingClass((current) => (current === item.id ? null : current)));
  };

  const byLecturer = useMemo(() => {
    const map = new Map<number, ClassItem[]>();
    for (const item of classes) if (item.lecturer_id) map.set(item.lecturer_id, [...(map.get(item.lecturer_id) ?? []), item]);
    return map;
  }, [classes]);
  const credits = (items: ClassItem[]) => items.reduce((sum, item) => sum + (item.credits || 0), 0);
  const maxCredits = Math.max(1, ...lecturers.map((lecturer) => credits(byLecturer.get(lecturer.id) ?? [])));

  const pool = classes.filter((item) => (showAll || !item.lecturer_id)
    && `${item.class_code} ${item.course_name} ${item.course_code}`.toLowerCase().includes(query.trim().toLowerCase()));
  const visibleLecturers = lecturers.filter((lecturer) => `${lecturer.code ?? ""} ${lecturer.name}`.toLowerCase().includes(lecturerQuery.trim().toLowerCase()));

  const verdict = (lecturerId: number): DropVerdict | null => {
    if (!active) return null;
    // Live clash check from sessions alone, before the server analysis arrives.
    const clashes = (byLecturer.get(lecturerId) ?? []).some((other) => other.id !== active.id && sessionsClash(active, other));
    if (clashes) return "clash";
    const row = analysis[active.id]?.[lecturerId];
    if (!row) return null;
    if (row.is_eligible) return "ok";
    return row.has_collision ? "clash" : "approval";
  };

  // While a class is being placed, show who can take it first, then who needs approval, then the clashes.
  const rank: Record<DropVerdict, number> = { ok: 0, approval: 1, clash: 2 };
  const lanes = active
    ? [...visibleLecturers].sort((left, right) => {
        const a = verdict(left.id); const b = verdict(right.id);
        return (a ? rank[a] : 3) - (b ? rank[b] : 3) || credits(byLecturer.get(left.id) ?? []) - credits(byLecturer.get(right.id) ?? []);
      })
    : visibleLecturers;

  const drop = (lecturerId: number) => {
    const item = active;
    setDragging(null); setPicked(null); setHoverLecturer(null);
    if (!item || item.lecturer_id === lecturerId) return;
    const result = verdict(lecturerId);
    if (result === "ok") onAssign(item.id, lecturerId);
    else onOpenScenarios(item.id, lecturerId);
  };

  return (
    <div className={styles.board}>
      <aside className={styles.pool} aria-label="Lớp cần xếp">
        <header>
          <strong>{showAll ? "Tất cả lớp" : "Lớp chưa phân"} ({pool.length})</strong>
          <label className={styles.toggle}><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Hiện cả lớp đã phân</label>
          <label className={styles.search}><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm lớp / môn" aria-label="Tìm lớp" /></label>
          <small>Kéo một lớp thả vào giảng viên, hoặc bấm chọn lớp rồi bấm vào giảng viên.</small>
        </header>
        <div className={styles.poolList}>
          {pool.map((item) => (
            <div
              key={item.id}
              role="button"
              tabIndex={0}
              draggable={!busy}
              aria-pressed={picked?.id === item.id}
              className={`${styles.card} ${picked?.id === item.id ? styles.cardPicked : ""} ${item.lecturer_id ? styles.cardAssigned : ""}`}
              onDragStart={(event) => { event.dataTransfer.setData("text/plain", String(item.id)); event.dataTransfer.effectAllowed = "move"; setDragging(item); loadAnalysis(item); }}
              onDragEnd={() => { setDragging(null); setHoverLecturer(null); }}
              onClick={() => { const next = picked?.id === item.id ? null : item; setPicked(next); if (next) loadAnalysis(next); }}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setPicked(item); loadAnalysis(item); } }}
            >
              <GripVertical size={14} className={styles.grip} />
              <div>
                <strong>{item.class_code}</strong>
                <span>{item.course_name}</span>
                <small>{item.sessions.map((s) => `${dayLabel(s.weekday)} ${s.start_period}–${s.end_period}`).join(" · ")}{item.lecturer ? ` · ${item.lecturer}` : ""}</small>
              </div>
              {item.locked_assignment ? <Lock size={13} aria-label="Đã khóa" /> : null}
              <button type="button" className={styles.cardAction} onClick={(event) => { event.stopPropagation(); onOpenScenarios(item.id); }}>Kịch bản</button>
            </div>
          ))}
          {!pool.length ? <p className={styles.emptyPool}>{showAll ? "Không có lớp phù hợp." : "Mọi lớp đều đã có giảng viên."}</p> : null}
        </div>
      </aside>
      <section className={styles.lanes} aria-label="Giảng viên">
        <header className={styles.lanesHeader}>
          {active ? (
            <span className={styles.activeHint}>
              Đang xếp <b>{active.class_code}</b> — {loadingClass === active.id ? "đang kiểm tra từng giảng viên…" : "màu ô cho biết ai nhận được."}
              <button type="button" className={styles.ghostButton} onClick={() => { setPicked(null); setDragging(null); }}>Bỏ chọn</button>
            </span>
          ) : <span className={styles.activeHint}>Chọn hoặc kéo một lớp để xem ngay ai dạy được, ai cần phê duyệt, ai trùng lịch.</span>}
          <label className={styles.search}><Search size={14} /><input value={lecturerQuery} onChange={(event) => setLecturerQuery(event.target.value)} placeholder="Tìm giảng viên" aria-label="Tìm giảng viên" /></label>
          <div className={styles.legend}><span className={styles.vOk}>nhận được</span><span className={styles.vApproval}>cần phê duyệt</span><span className={styles.vClash}>trùng lịch</span></div>
        </header>
        <div className={styles.laneGrid}>
          {lanes.map((lecturer) => {
            const own = byLecturer.get(lecturer.id) ?? [];
            const result = verdict(lecturer.id);
            const occupied = new Set(own.flatMap((item) => item.sessions.flatMap((s) => blockOf(s.start_period, s.end_period).map((b) => `${s.weekday}-${b}`))));
            const target = new Set(active ? active.sessions.flatMap((s) => blockOf(s.start_period, s.end_period).map((b) => `${s.weekday}-${b}`)) : []);
            const row = active ? analysis[active.id]?.[lecturer.id] : undefined;
            return (
              <div
                key={lecturer.id}
                role="button"
                tabIndex={0}
                aria-label={`${lecturer.name}: ${own.length} lớp${result ? `, ${result === "ok" ? "nhận được" : result === "clash" ? "trùng lịch" : "cần phê duyệt"}` : ""}`}
                className={`${styles.lane} ${result ? styles[`lane_${result}`] : ""} ${hoverLecturer === lecturer.id ? styles.laneHover : ""}`}
                onDragOver={(event) => { if (dragging) { event.preventDefault(); setHoverLecturer(lecturer.id); } }}
                onDragLeave={() => setHoverLecturer((current) => (current === lecturer.id ? null : current))}
                onDrop={(event) => { event.preventDefault(); drop(lecturer.id); }}
                onClick={() => { if (picked) drop(lecturer.id); }}
                onKeyDown={(event) => { if (picked && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); drop(lecturer.id); } }}
              >
                <div className={styles.laneTop}>
                  <strong>{lecturer.name}</strong>
                  <small>{lecturer.code ?? ""} · {own.length} lớp · {credits(own)} TC</small>
                </div>
                <div className={styles.loadBar}><span style={{ width: `${(credits(own) / maxCredits) * 100}%` }} /></div>
                <div className={styles.miniWeek} aria-hidden="true">
                  {BLOCKS.map((_, block) => DAYS.slice(0, 6).map((day) => {
                    const key = `${day}-${block}`;
                    const isTarget = target.has(key);
                    const isBusy = occupied.has(key);
                    return <i key={key} className={isTarget && isBusy ? (result === "clash" ? styles.cellClash : styles.cellShared) : isTarget ? styles.cellTarget : isBusy ? styles.cellBusy : ""} title={isTarget && isBusy && result !== "clash" ? "Cùng ca nhưng khác tuần học" : undefined} />;
                  }))}
                </div>
                {result === "clash" ? <small className={styles.laneWhy}><AlertTriangle size={11} /> Trùng giờ với lớp đang dạy</small> : null}
                {result === "approval" && row ? <small className={styles.laneWhy}>{row.status_label} — thả vào để xem cấp phê duyệt</small> : null}
                {result === "ok" ? <small className={styles.laneWhy}><Check size={11} /> Nhận được ngay</small> : null}
                <div className={styles.laneChips}>
                  {own.slice(0, 6).map((item) => (
                    <span key={item.id} draggable={!busy && !item.locked_assignment} className={styles.laneChip}
                      onDragStart={(event) => { event.stopPropagation(); event.dataTransfer.setData("text/plain", String(item.id)); setDragging(item); loadAnalysis(item); }}
                      onDragEnd={() => { setDragging(null); setHoverLecturer(null); }}
                      title={`${item.class_code} · ${item.course_name}${item.locked_assignment ? " (đã khóa)" : " — kéo sang giảng viên khác để đổi"}`}>
                      {item.locked_assignment ? <Lock size={9} /> : null}{item.class_code}
                    </span>
                  ))}
                  {own.length > 6 ? <span className={styles.more}>+{own.length - 6}</span> : null}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function sessionsClash(left: ClassItem, right: ClassItem) {
  // Confirmed merged classes are one lesson taught together, not a clash.
  if (left.merged_group_id && left.merged_group_id === right.merged_group_id && left.merged_confirmed && right.merged_confirmed) return false;
  return left.sessions.some((a) => right.sessions.some((b) =>
    a.weekday === b.weekday && a.start_period <= b.end_period && b.start_period <= a.end_period
    && (a.active_weeks ?? []).some((week) => (b.active_weeks ?? []).includes(week))));
}
