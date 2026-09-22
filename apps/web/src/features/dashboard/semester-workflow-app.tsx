"use client";

import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CalendarRange,
  Check,
  CheckCircle2,
  ChevronRight,
  Columns3,
  Download,
  FileCheck2,
  FileDown,
  FileSpreadsheet,
  FileUp,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  Lock,
  Menu,
  Merge,
  PencilLine,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Table,
  Trash2,
  UploadCloud,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { HuceWordmark } from "@/src/components/brand/huce-wordmark";
import { api } from "@/src/services/api";
import type {
  ClassItem,
  Constraint,
  DashboardMetrics,
  Lecturer,
  LecturerImportPreview,
  LecturerImportResult,
  LecturerReviewItem,
  LecturerReviewResponse,
  MergeCandidate,
  PreferenceDraft,
  Problem,
  Readiness,
  CapabilityReadiness,
  RunDiff,
  Seminar,
  Semester,
  SourceState,
  TemplateDetection,
  CandidateAnalysisItem,
  UnassignedDiagnosticItem,
  ValidationIssue,
  Workload,
} from "@/src/types/api";

import styles from "./semester-workflow.module.css";
import { SourceAuthorityPanel } from "./source-authority-panel";
import { preferenceRuleTypesForContext } from "./preference-context";
import { AppleCalendarView } from "./apple-calendar-view";

type View = "semester" | "template" | "inputs" | "preferences" | "workspace" | "publish";

const steps: { id: View; label: string; hint: string; icon: typeof CalendarRange }[] = [
  { id: "semester", label: "Kỳ học", hint: "Thông tin chung", icon: CalendarRange },
  { id: "template", label: "Mẫu đầu ra", hint: "Học dữ liệu & cấu trúc", icon: Columns3 },
  { id: "inputs", label: "Dữ liệu đầu vào", hint: "Hai file bắt buộc", icon: UploadCloud },
  { id: "preferences", label: "Duyệt nguyện vọng", hint: "Human in the loop", icon: FileCheck2 },
  { id: "workspace", label: "Phân công", hint: "Tối ưu & rà soát", icon: LayoutDashboard },
  { id: "publish", label: "Xuất kết quả", hint: "Chốt phiên bản", icon: Download },
];

const emptyMetrics: DashboardMetrics = {
  classes: 0,
  locked_classes: 0,
  unassigned_classes: 0,
  merged_suggestions: 0,
  lecturers: 0,
  validation_errors: 0,
  optimization_status: "not_run",
  optimization_score: null,
};

const fieldLabels: Record<string, string> = {
  lecturer: "Giảng viên",
  course_code: "Mã học phần",
  course_name: "Tên môn học",
  class_code: "Mã lớp",
  merged_class: "Lớp ghép",
  weekday: "Thứ",
  periods: "Tiết học",
  room: "Phòng học",
  start_date: "Ngày bắt đầu",
  end_date: "Ngày kết thúc",
  weeks: "Tuần học",
  credits: "Số TC",
  group: "Nhóm",
};

const requiredTemplateFields = new Set([
  "lecturer",
  "course_code",
  "course_name",
  "class_code",
  "weekday",
  "periods",
]);

export function SemesterWorkflowApp() {
  const [view, setView] = useState<View>("semester");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [metrics, setMetrics] = useState(emptyMetrics);
  const [semesters, setSemesters] = useState<Semester[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [preferenceDrafts, setPreferenceDrafts] = useState<PreferenceDraft[]>([]);
  const [lecturers, setLecturers] = useState<Lecturer[]>([]);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [template, setTemplate] = useState<TemplateDetection | null>(null);

  const loadAll = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [semesterRows, dashboard, classRows, constraintRows, lecturerRows, issueRows, latestTemplate] = await Promise.all([
        api.semesters(),
        api.dashboard(),
        api.classes(),
        api.constraints(),
        api.lecturers(),
        api.conflicts(),
        api.latestTemplate(),
      ]);
      setSemesters(semesterRows);
      setMetrics(dashboard);
      setClasses(classRows);
      setConstraints(constraintRows);
      setLecturers(lecturerRows);
      setIssues(issueRows);
      setTemplate(latestTemplate);
      const active = semesterRows.find((item) => item.is_active) ?? semesterRows[0];
      setPreferenceDrafts(active ? await api.preferenceDrafts(active.id) : []);
      setProblems(active ? await api.problems(active.id) : []);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể kết nối máy chủ.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const activeSemester = semesters.find((item) => item.is_active) ?? semesters[0] ?? null;
  const currentStep = steps.findIndex((item) => item.id === view);

  async function execute(name: string, action: () => Promise<unknown>, success: string) {
    setBusy(name);
    setError(null);
    try {
      await action();
      setNotice(success);
      await loadAll(true);
      window.setTimeout(() => setNotice(null), 3600);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Thao tác chưa hoàn tất.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.appShell}>
      <aside className={`${styles.sidebar} ${drawerOpen ? styles.drawerOpen : ""}`}>
        <div className={styles.brandRow}>
          <HuceWordmark />
          <button type="button" className={styles.mobileClose} aria-label="Đóng menu" onClick={() => setDrawerOpen(false)}>
            <X size={19} />
          </button>
        </div>
        <div className={styles.contextLabel}>QUY TRÌNH LẬP LỊCH</div>
        <nav className={styles.stepNav} aria-label="Các bước lập lịch">
          {steps.map((step, index) => {
            const Icon = step.icon;
            const completed = index < currentStep;
            return (
              <button
                type="button"
                key={step.id}
                className={`${styles.stepButton} ${view === step.id ? styles.stepActive : ""}`}
                aria-current={view === step.id ? "step" : undefined}
                onClick={() => {
                  setView(step.id);
                  setDrawerOpen(false);
                }}
              >
                <span className={styles.stepIcon}>{completed ? <Check size={16} /> : <Icon size={17} />}</span>
                <span><strong>{step.label}</strong><small>{step.hint}</small></span>
                <ChevronRight size={15} className={styles.stepChevron} />
              </button>
            );
          })}
        </nav>
        <div className={styles.semesterSummary}>
          <span className={styles.liveDot} />
          <span>
            <small>Kỳ đang làm việc</small>
            <strong>{activeSemester?.name ?? "Chưa tạo kỳ học"}</strong>
          </span>
        </div>
      </aside>

      {drawerOpen ? <button type="button" className={styles.scrim} aria-label="Đóng menu" onClick={() => setDrawerOpen(false)} /> : null}

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.topbarTitle}>
            <button type="button" className={styles.menuButton} aria-label="Mở menu" onClick={() => setDrawerOpen(true)}><Menu size={20} /></button>
            <div><span>HUCE · BỘ MÔN TOÁN HỌC</span><h1>{steps[currentStep]?.label}</h1></div>
          </div>
          <div className={styles.topbarActions}>
            <button type="button" className={styles.iconButton} aria-label="Làm mới dữ liệu" onClick={() => void loadAll()}>
              <RefreshCw size={17} className={loading ? styles.spin : ""} />
            </button>
            <span className={styles.adminIdentity}><span>PT</span><span><small>Trưởng bộ môn</small><strong>{activeSemester?.head_name ?? "Quản trị viên"}</strong></span></span>
          </div>
        </header>

        <div className={styles.content}>
          {notice ? <div className={styles.notice}><CheckCircle2 size={18} />{notice}</div> : null}
          {error ? <div className={styles.errorBanner} role="alert"><AlertCircle size={18} /><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Đóng cảnh báo"><X size={16} /></button></div> : null}
          {loading ? <div className={styles.loading}><LoaderCircle size={22} className={styles.spin} />Đang đồng bộ không gian làm việc…</div> : null}

          {!loading && view === "semester" ? (
            <SemesterView
              activeSemester={activeSemester}
              busy={busy}
              onCreate={(payload) => execute("semester", () => api.createSemester(payload), "Đã tạo kỳ học và đặt làm kỳ đang hoạt động.")}
              onNext={() => setView("template")}
            />
          ) : null}
          {!loading && view === "template" ? (
            <TemplateView
              activeSemester={activeSemester}
              template={template}
              setTemplate={setTemplate}
              busy={busy}
              onDetect={(file) => execute("template", async () => setTemplate(await api.detectTemplate(file, activeSemester?.id)), "Đã nhận diện cấu trúc mẫu đầu ra.")}
              onSave={(value) => execute("mapping", () => api.updateTemplate(value.profile_id, value.mappings, value.missing_fields), "Đã lưu ánh xạ cột cho kỳ học này.")}
              onNext={() => setView("inputs")}
            />
          ) : null}
          {!loading && view === "inputs" ? (
            <InputView
              busy={busy}
              metrics={metrics}
              semesterId={activeSemester?.id ?? null}
              activeSemester={activeSemester}
              onUpload={(schedule, preference) => execute("inputs", () => api.uploadPair(schedule, preference, activeSemester?.id), "Đã lưu hai nguồn ứng viên. Hãy đối chiếu và kích hoạt từng nguồn.")}
              onNext={() => setView("preferences")}
              onReload={loadAll}
            />
          ) : null}
          {!loading && view === "preferences" ? (
            <PreferenceReview
              drafts={preferenceDrafts}
              lecturers={lecturers}
              semesterId={activeSemester?.id ?? null}
              busy={busy}
              onSave={(item, payload) => execute(`draft-${item.id}`, () => api.updatePreferenceDraft(item.id, payload, activeSemester?.id ?? 0), "Đã lưu quyết định duyệt.")}
              onConfirmHigh={() => execute("confirm-high", () => api.confirmHighPreferenceDrafts(activeSemester?.id ?? 0), "Đã xác nhận các rule HIGH có identity rõ ràng.")}
              onApply={(ids) => execute("apply-drafts", () => api.applyPreferenceDrafts(ids, activeSemester?.id ?? 0), "Đã áp dụng các nguyện vọng đã xác nhận.")}
              onCreate={(payload) => execute("new-preference", () => api.createPreferenceDraft(payload, activeSemester?.id ?? 0), "Đã thêm bản nháp nguyện vọng để duyệt.")}
              onNext={() => setView("workspace")}
            />
          ) : null}
          {!loading && view === "workspace" ? (
            <SchedulingWorkspace
              metrics={metrics}
              classes={classes}
              constraints={constraints}
              lecturers={lecturers}
              issues={issues}
              problems={problems}
              semesterId={activeSemester?.id ?? null}
              busy={busy}
              onRun={() => execute("optimize", () => api.optimize(false), "Đã tạo phương án phân công mới.")}
              onCreate={(payload) => execute("new-constraint", () => api.createConstraint(payload), "Đã thêm ràng buộc và cập nhật vùng xem trước.")}
              onUpdateConstraint={(item, payload) => execute(`constraint-${item.id}`, () => api.updateConstraint(item.id, payload), "Đã cập nhật ràng buộc.")}
              onDeleteConstraint={(item) => execute(`delete-${item.id}`, () => api.deleteConstraint(item.id), "Đã xóa ràng buộc.")}
              onManual={(classId, lecturerId, lock, allowOverride = false, overrideReason = "") => execute(`assignment-${classId}`, () => api.assign(classId, lecturerId, lock, activeSemester?.id ?? 0, allowOverride, overrideReason), lock ? "Đã phân công và khóa lớp học phần." : "Đã cập nhật phân công thủ công.")}
              onOverrideLock={(classId, lecturerId, reason, lock) => execute(`override-${classId}`, () => api.overrideLock(classId, lecturerId, reason, lock, activeSemester?.id ?? 0), "Đã mở khóa và ghi đè phân công thủ công có kiểm toán.")}
              onUnlock={(classId) => execute(`unlock-${classId}`, () => api.unlock(classId, activeSemester?.id ?? 0), "Đã mở khóa phân công.")}
              onNext={() => setView("publish")}
              onSwitchView={(v) => setView(v)}
            />
          ) : null}
          {!loading && view === "publish" ? <PublishView metrics={metrics} problems={problems} semesterId={activeSemester?.id} /> : null}
        </div>
      </main>
    </div>
  );
}

function PageHeading({ eyebrow, title, text, action }: { eyebrow: string; title: string; text: string; action?: React.ReactNode }) {
  return <header className={styles.pageHeading}><div><span>{eyebrow}</span><h2>{title}</h2><p>{text}</p></div>{action ?? null}</header>;
}

function SemesterView({ activeSemester, busy, onCreate, onNext }: {
  activeSemester: Semester | null;
  busy: string | null;
  onCreate: (payload: Omit<Semester, "id" | "status" | "is_active">) => void;
  onNext: () => void;
}) {
  const [form, setForm] = useState({
    name: "Học kỳ I · 2026–2027",
    department_name: "Bộ môn Toán học",
    start_date: "2026-09-07",
    end_date: "2027-01-24",
    head_name: "Phạm Đức Thoan",
  });
  const update = (field: keyof typeof form, value: string) => setForm((current) => ({ ...current, [field]: value }));
  return <section className={styles.viewEnter}>
    <PageHeading eyebrow="BƯỚC 01" title="Thiết lập kỳ học" text="Thông tin này là ngữ cảnh chung cho toàn bộ dữ liệu, ràng buộc và file xuất." />
    <div className={styles.formCard}>
      <div className={styles.formIntro}><CalendarRange size={22} /><div><strong>Hồ sơ kỳ học</strong><span>Một kỳ học tương ứng với một phiên lập lịch độc lập.</span></div></div>
      <div className={styles.formGrid}>
        <label className={styles.field}><span>Tên kỳ học</span><input value={form.name} onChange={(event) => update("name", event.target.value)} /></label>
        <label className={styles.field}><span>Môn / đơn vị chuyên môn</span><input value={form.department_name} onChange={(event) => update("department_name", event.target.value)} /></label>
        <label className={styles.field}><span>Ngày bắt đầu</span><input type="date" value={form.start_date} onChange={(event) => update("start_date", event.target.value)} /></label>
        <label className={styles.field}><span>Ngày kết thúc</span><input type="date" value={form.end_date} onChange={(event) => update("end_date", event.target.value)} /></label>
        <label className={`${styles.field} ${styles.fullField}`}><span>Trưởng bộ môn phụ trách</span><input value={form.head_name} onChange={(event) => update("head_name", event.target.value)} /></label>
      </div>
      <div className={styles.cardFooter}>
        <span>{activeSemester ? `Kỳ hiện tại: ${activeSemester.name}` : "Chưa có kỳ học đang hoạt động."}</span>
        <div><button type="button" className={styles.primaryButton} disabled={busy === "semester" || Object.values(form).some((value) => !value.trim())} onClick={() => onCreate(form)}>{busy === "semester" ? <LoaderCircle size={17} className={styles.spin} /> : <Plus size={17} />}Tạo kỳ học</button><button type="button" className={styles.textButton} disabled={!activeSemester} onClick={onNext}>Tiếp tục<ArrowRight size={16} /></button></div>
      </div>
    </div>
  </section>;
}

function TemplateView({ activeSemester, template, setTemplate, busy, onDetect, onSave, onNext }: {
  activeSemester: Semester | null;
  template: TemplateDetection | null;
  setTemplate: React.Dispatch<React.SetStateAction<TemplateDetection | null>>;
  busy: string | null;
  onDetect: (file: File) => void;
  onSave: (template: TemplateDetection) => void;
  onNext: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const fields = Object.keys(fieldLabels);

  function mapField(field: string, columnIndex: number) {
    if (!template) return;
    const column = template.available_columns.find((item) => item.column_index === columnIndex);
    if (!column) return;
    const mappings = { ...template.mappings, [field]: { ...column, confidence: 1.0 } };
    const missingFields = template.missing_fields.filter((item) => item !== field);
    const isReady = !Array.from(requiredTemplateFields).some((req) => !mappings[req]);
    setTemplate({ ...template, mappings, missing_fields: missingFields, ready: isReady });
  }

  function clearField(field: string) {
    if (!template) return;
    const mappings = { ...template.mappings };
    delete mappings[field];
    const missingFields = requiredTemplateFields.has(field)
      ? Array.from(new Set([...template.missing_fields, field]))
      : template.missing_fields;
    const isReady = !Array.from(requiredTemplateFields).some((req) => !mappings[req]);
    setTemplate({ ...template, mappings, missing_fields: missingFields, ready: isReady });
  }

  const headerRowText = template
    ? template.header_start_row && template.header_end_row && template.header_start_row !== template.header_end_row
      ? `tiêu đề dòng ${template.header_start_row}–${template.header_end_row}`
      : `tiêu đề tại dòng ${template.header_row}`
    : "File phân công hoặc TKB đã xuất ở học kỳ trước (.xls, .xlsx)";

  return <section className={styles.viewEnter}>
    <PageHeading
      eyebrow="BƯỚC 02"
      title="Học dữ liệu và cấu trúc kỳ trước"
      text="Tải file kết quả kỳ trước để hệ thống tự động học cấu trúc bảng (thứ, tiết, phòng, môn, giảng viên) và phân tích lịch sử giảng dạy."
    />
    <div className={styles.uploadSingle}>
      <input ref={inputRef} hidden type="file" accept=".xls,.xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) onDetect(file); }} />
      <span className={styles.fileIcon}><FileSpreadsheet size={23} /></span>
      <div><strong>{template?.source_file ?? "Chưa chọn file mẫu"}</strong><span>{template ? `${template.source_sheet} · ${headerRowText}` : "File phân công hoặc TKB đã xuất ở học kỳ trước (.xls, .xlsx)"}</span></div>
      <button type="button" className={styles.secondaryButton} disabled={busy === "template" || !activeSemester} onClick={() => inputRef.current?.click()}>{busy === "template" ? <LoaderCircle size={17} className={styles.spin} /> : <UploadCloud size={17} />}Chọn file mẫu</button>
    </div>
    {template && (template.historical_summary || template.lecturer_identity_summary) ? (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "16px", marginTop: "16px" }}>
        {template.historical_summary ? (
          <div className={styles.summaryStrip} style={{ marginTop: 0 }}>
            <span><strong>{template.historical_summary.data_rows_count}</strong>Dòng trong mẫu nhận diện (tối đa 120 dòng đầu)</span>
            <span><strong>{template.historical_summary.courses_count}</strong>Môn trong mẫu</span>
            <span><strong>{template.historical_summary.classes_count}</strong>Lớp trong mẫu</span>
            <span><strong>{template.historical_summary.lecturers_count}</strong>Giảng viên trong mẫu</span>
          </div>
        ) : null}
        {template.lecturer_identity_summary ? (
          <div className={styles.summaryStrip} style={{ marginTop: 0, background: "linear-gradient(135deg, #1e293b, #0f172a)" }}>
            <span><strong>{template.lecturer_identity_summary.total}</strong>Giảng viên từ trích xuất toàn file</span>
            <span><strong>{template.lecturer_identity_summary.with_code}</strong>Có mã CBGV</span>
            <span><strong>{template.lecturer_identity_summary.matched_master}</strong>Khớp danh mục</span>
            <span><strong>{template.lecturer_identity_summary.need_review}</strong>Cần rà soát</span>
          </div>
        ) : null}
      </div>
    ) : null}
    {template ? <p>Nhận diện cột dùng mẫu tối đa 120 dòng đầu. Trích xuất lịch sử toàn file chỉ lưu danh tính, môn và lớp (mẫu ma trận chỉ lưu danh tính); chưa học giờ, phòng, tuần hoặc ngày, và không tạo phân công hay khóa.</p> : null}
    {template?.historical_learning?.message ? <p role="alert">{template.historical_learning.message}</p> : null}
    {template ? <div className={styles.mappingCard}>
      <div className={styles.mappingHeader}><div><strong>{template.layout_label}</strong><span>{template.ready ? "Tất cả các trường cốt lõi đã được tự động khớp chính xác." : `${template.missing_fields.length} trường cần rà soát hoặc chọn thủ công.`}</span></div><span className={template.ready ? styles.readyBadge : styles.reviewBadge}>{template.ready ? "Sẵn sàng" : "Cần rà soát"}</span></div>
      {template.layout === "matrix" ? <div className={styles.matrixDetection}>
        <div className={styles.matrixDiagram}><span>GIẢNG VIÊN</span>{template.weekday_columns.map((column) => <span key={column.weekday}>{column.header.toUpperCase()}</span>)}</div>
        <div className={styles.matrixCopy}><CheckCircle2 size={20} /><div><strong>Đã hiểu mẫu lịch dạng ma trận</strong><p>Cột A chứa giảng viên; mỗi cột ngày chứa nhiều lớp với tên môn, mã lớp, tiết và khoảng ngày. Khi xuất, hệ thống sẽ gom kết quả về đúng cấu trúc này.</p></div></div>
        {template.preview.length ? <div className={styles.templatePreview}>{template.preview.slice(0, 3).map((row, index) => <span key={`${row.lecturer}-${index}`}><strong>{row.lecturer}</strong><small>{row.schedule_days || "Chưa có lịch"}</small></span>)}</div> : null}
      </div> : <div className={styles.mappingGrid}>
        {fields.map((field) => {
          const mapping = template.mappings[field];
          const isRequired = requiredTemplateFields.has(field);
          return (
            <label className={styles.mappingRow} key={field}>
              <span>
                <strong>{fieldLabels[field]}{isRequired ? " *" : ""}</strong>
                <small>{mapping ? `${mapping.column_letter} · ${mapping.header} (${Math.round((mapping.confidence ?? 0.8) * 100)}%)` : "Chưa nhận diện"}</small>
              </span>
              <select
                aria-label={`Cột cho ${fieldLabels[field]}`}
                value={mapping?.column_index ?? ""}
                onChange={(event) => {
                  const val = event.target.value;
                  if (val === "") {
                    clearField(field);
                  } else {
                    mapField(field, Number(val));
                  }
                }}
              >
                <option value="">Chọn cột…</option>
                {template.available_columns.map((column) => (
                  <option key={column.column_index} value={column.column_index}>{column.column_letter} · {column.header}</option>
                ))}
              </select>
            </label>
          );
        })}
      </div>}
      <div className={styles.cardFooter}>
        <span>Thay đổi chỉ áp dụng cho mẫu đầu ra của kỳ đang chọn.</span>
        <div>
          <button type="button" className={styles.secondaryButton} disabled={busy === "mapping"} onClick={() => onSave(template)}>
            {busy === "mapping" ? <LoaderCircle size={15} className={styles.spin} /> : null}
            Lưu ánh xạ
          </button>
          <button type="button" className={styles.primaryButton} disabled={!template.ready} onClick={() => { onSave(template); onNext(); }}>
            Dùng mẫu này
            <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </div> : <div className={styles.emptyPanel}><Columns3 size={24} /><strong>Hệ thống sẽ tự tìm dòng tiêu đề và đối chiếu tên cột</strong><span>Các trường chưa chắc chắn sẽ được đánh dấu để bạn chọn lại, không tự động điền sai.</span></div>}
  </section>;
}

export function LecturerHitlSection({
  semesterId,
  onReload,
  onNext,
  sourcesActive,
}: {
  semesterId: number | null;
  onReload?: () => void;
  onNext: () => void;
  sourcesActive: boolean;
}) {
  const [data, setData] = useState<LecturerReviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Modals
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<LecturerReviewItem | null>(null);
  const [mergeSource, setMergeSource] = useState<LecturerReviewItem | null>(null);
  const [mergeTargetId, setMergeTargetId] = useState<string>("");

  // Import Modal
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<LecturerImportPreview | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<LecturerImportResult | null>(null);

  // Form State
  const [formCode, setFormCode] = useState("");
  const [formName, setFormName] = useState("");
  const [formEmail, setFormEmail] = useState("");
  const [formDept, setFormDept] = useState("");
  const [formQuotaMin, setFormQuotaMin] = useState("0");
  const [formQuotaMax, setFormQuotaMax] = useState("24");
  const [formAliases, setFormAliases] = useState("");
  const [formParticipates, setFormParticipates] = useState(true);

  const fetchReview = useCallback(async () => {
    if (!semesterId) return;
    setLoading(true);
    try {
      const res = await api.lecturerReview(semesterId);
      setData(res);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải dữ liệu rà soát giảng viên.");
    } finally {
      setLoading(false);
    }
  }, [semesterId]);

  useEffect(() => {
    fetchReview();
  }, [fetchReview]);

  const openAdd = () => {
    setFormCode("");
    setFormName("");
    setFormEmail("");
    setFormDept("");
    setFormQuotaMin("0");
    setFormQuotaMax("24");
    setFormAliases("");
    setFormParticipates(true);
    setAddOpen(true);
  };

  const openEdit = (item: LecturerReviewItem) => {
    setEditTarget(item);
    setFormCode(item.code ?? "");
    setFormName(item.name);
    setFormEmail(item.email ?? "");
    setFormDept(item.department ?? "");
    setFormQuotaMin(String(item.quota_min));
    setFormQuotaMax(String(item.quota_max));
    setFormAliases(item.aliases.join(", "));
    setFormParticipates(item.participates);
  };

  const handleSaveAdd = async () => {
    if (!semesterId || !formName.trim()) return;
    setActionBusy("save-add");
    try {
      await api.createLecturer(
        {
          code: formCode.trim() || null,
          name: formName.trim(),
          email: formEmail.trim() || null,
          department: formDept.trim() || null,
          quota_min: Number(formQuotaMin) || 0,
          quota_max: Number(formQuotaMax) || 24,
          aliases: formAliases.split(",").map((s) => s.trim()).filter(Boolean),
          participates: formParticipates,
        },
        semesterId
      );
      setAddOpen(false);
      setSuccessMsg("Đã thêm giảng viên thành công.");
      await fetchReview();
      onReload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tạo giảng viên.");
    } finally {
      setActionBusy(null);
    }
  };

  const handleSaveEdit = async () => {
    if (!semesterId || !editTarget || !formName.trim()) return;
    setActionBusy("save-edit");
    try {
      await api.updateLecturer(
        editTarget.id,
        {
          code: formCode.trim() || null,
          name: formName.trim(),
          email: formEmail.trim() || null,
          department: formDept.trim() || null,
          quota_min: Number(formQuotaMin) || 0,
          quota_max: Number(formQuotaMax) || 24,
          aliases: formAliases.split(",").map((s) => s.trim()).filter(Boolean),
          participates: formParticipates,
        },
        semesterId
      );
      setEditTarget(null);
      setSuccessMsg("Đã cập nhật thông tin giảng viên.");
      await fetchReview();
      onReload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể cập nhật giảng viên.");
    } finally {
      setActionBusy(null);
    }
  };

  const handleToggleParticipate = async (item: LecturerReviewItem) => {
    if (!semesterId) return;
    setActionBusy(`toggle-${item.id}`);
    try {
      await api.updateLecturer(item.id, { participates: !item.participates }, semesterId);
      await fetchReview();
      onReload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cập nhật tham gia thất bại.");
    } finally {
      setActionBusy(null);
    }
  };

  const handleMerge = async () => {
    if (!semesterId || !mergeSource || !mergeTargetId) return;
    setActionBusy("merge");
    try {
      await api.mergeLecturers(mergeSource.id, Number(mergeTargetId), semesterId);
      setMergeSource(null);
      setMergeTargetId("");
      setSuccessMsg(`Đã gộp ${mergeSource.name} thành công.`);
      await fetchReview();
      onReload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gộp giảng viên thất bại.");
    } finally {
      setActionBusy(null);
    }
  };

  const handleSelectImportFile = async (file: File) => {
    if (!semesterId) return;
    setImportFile(file);
    setImportLoading(true);
    setImportPreview(null);
    setImportResult(null);
    try {
      const preview = await api.previewLecturerImport(file, semesterId);
      setImportPreview(preview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Xem trước file import thất bại.");
    } finally {
      setImportLoading(false);
    }
  };

  const handleCommitImport = async () => {
    if (!semesterId || !importFile) return;
    setActionBusy("commit-import");
    try {
      const res = await api.commitLecturerImport(importFile, semesterId);
      setImportResult(res);
      setImportPreview(null);
      setSuccessMsg(`Đã nhập dữ liệu: thêm ${res.added}, cập nhật ${res.updated}.`);
      await fetchReview();
      onReload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nhập danh sách thất bại.");
    } finally {
      setActionBusy(null);
    }
  };

  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    return data.items.filter((item) => {
      const matchSearch =
        !search ||
        item.name.toLowerCase().includes(search.toLowerCase()) ||
        (item.code && item.code.toLowerCase().includes(search.toLowerCase())) ||
        item.aliases.some((a) => a.toLowerCase().includes(search.toLowerCase()));
      const matchFilter = statusFilter === "ALL" || item.identity_status === statusFilter;
      return matchSearch && matchFilter;
    });
  }, [data, search, statusFilter]);

  if (!semesterId) return null;

  return (
    <div className={styles.hitlContainer}>
      <div className={styles.hitlToolbar}>
        <div className={styles.hitlTitle}>
          <strong>Rà soát & Chuẩn hóa Giảng viên (Human-in-the-Loop)</strong>
          <span>Chuẩn hóa danh tính, danh xưng (alias), giải quyết trùng lặp và xác nhận tham gia trước khi duyệt nguyện vọng.</span>
        </div>
        <div className={styles.hitlActions}>
          <button type="button" className={styles.secondaryButton} onClick={openAdd}>
            <Plus size={15} /> Thêm GV
          </button>
          <button type="button" className={styles.secondaryButton} onClick={() => { setImportOpen(true); setImportPreview(null); setImportResult(null); setImportFile(null); }}>
            <FileUp size={15} /> Nhập Excel (.xlsx)
          </button>
          <a className={styles.secondaryButton} href={api.exportLecturersUrl(semesterId)} download="danh_sach_giang_vien.xlsx" target="_blank" rel="noreferrer">
            <FileDown size={15} /> Xuất Excel
          </a>
        </div>
      </div>

      {error ? <div className={styles.blockerAlert}><AlertTriangle size={16} /><span>{error}</span><button type="button" onClick={() => setError(null)} style={{ marginLeft: "auto", background: "none", border: 0, cursor: "pointer" }}><X size={14} /></button></div> : null}
      {successMsg ? <div className={styles.cleanLog} style={{ minHeight: "auto", padding: "8px 14px", borderRadius: "8px" }}><CheckCircle2 size={16} /><span>{successMsg}</span><button type="button" onClick={() => setSuccessMsg(null)} style={{ marginLeft: "auto", background: "none", border: 0, cursor: "pointer" }}><X size={14} /></button></div> : null}

      <div className={styles.hitlSummaryStrip}>
        <span>Tổng giảng viên: <strong>{data?.total_lecturers ?? 0}</strong></span>
        <span>Đã chuẩn hóa: <strong style={{ color: "#047857" }}>{data?.ready_count ?? 0}</strong></span>
        <span>Cần rà soát: <strong style={{ color: "#b45309" }}>{data?.needs_review_count ?? 0}</strong></span>
        <span>Vấn đề chặn (Blockers): <strong style={{ color: data?.blockers_count ? "#b91c1c" : "inherit" }}>{data?.blockers_count ?? 0}</strong></span>
        {loading ? <LoaderCircle size={15} className={styles.spin} style={{ marginLeft: "auto" }} /> : null}
      </div>

      {data?.blockers && data.blockers.length > 0 ? (
        <div className={styles.blockerAlert}>
          <AlertTriangle size={20} style={{ flexShrink: 0, marginTop: 2 }} />
          <div>
            <strong>Phát hiện {data.blockers.length} vấn đề định danh cần xử lý trước khi sang bước tiếp theo:</strong>
            <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
              {data.blockers.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: 1, minWidth: "220px" }}>
          <input
            type="text"
            placeholder="Tìm theo tên, mã GV, alias..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: "100%", padding: "7px 10px 7px 30px", fontSize: "0.8125rem", borderRadius: "8px", border: "1px solid var(--color-border)" }}
          />
          <Search size={14} style={{ position: "absolute", left: 10, top: 10, color: "var(--color-text-muted)" }} />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ padding: "7px 10px", fontSize: "0.8125rem", borderRadius: "8px", border: "1px solid var(--color-border)" }}
        >
          <option value="ALL">Tất cả trạng thái</option>
          <option value="STANDARDIZED">Đã chuẩn hóa</option>
          <option value="NEEDS_CONFIRMATION">Cần xác nhận</option>
          <option value="POSSIBLE_DUPLICATE">Nghi ngờ trùng lặp</option>
        </select>
        <button type="button" className={styles.secondaryButton} onClick={fetchReview} disabled={loading} title="Làm mới">
          <RotateCcw size={14} className={loading ? styles.spin : ""} />
        </button>
      </div>

      <div className={styles.hitlTableWrap}>
        <table className={styles.hitlTable}>
          <thead>
            <tr>
              <th>Mã GV</th>
              <th>Họ và tên</th>
              <th>Nguồn phát hiện</th>
              <th>Danh xưng / Alias</th>
              <th>Trạng thái</th>
              <th>Tham gia</th>
              <th>Năng lực</th>
              <th style={{ textAlign: "right" }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {filteredItems.length ? (
              filteredItems.map((item) => (
                <tr key={item.id}>
                  <td>
                    {item.code ? <strong>{item.code}</strong> : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                  </td>
                  <td>
                    <div>
                      <strong>{item.name}</strong>
                      {item.department ? (
                        <small style={{ display: "block", color: "var(--color-text-muted)" }}>{item.department}</small>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    {item.sources.map((s) => (
                      <span key={s} className={styles.sourceBadge}>
                        {s}
                      </span>
                    ))}
                  </td>
                  <td>
                    {item.aliases.length ? (
                      item.aliases.map((a) => (
                        <span key={a} className={styles.aliasTag}>
                          {a}
                        </span>
                      ))
                    ) : (
                      <span style={{ color: "var(--color-text-muted)" }}>—</span>
                    )}
                  </td>
                  <td>
                    {item.identity_status === "STANDARDIZED" ? (
                      <span className={`${styles.identityBadge} ${styles.identityStandardized}`}>
                        <Check size={11} /> Chuẩn hóa
                      </span>
                    ) : item.identity_status === "NEEDS_CONFIRMATION" ? (
                      <span className={`${styles.identityBadge} ${styles.identityNeedsConfirmation}`}>
                        <AlertTriangle size={11} /> Cần xác nhận
                      </span>
                    ) : (
                      <span className={`${styles.identityBadge} ${styles.identityDuplicate}`}>
                        <X size={11} /> Trùng lặp
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={item.participates}
                      disabled={actionBusy === `toggle-${item.id}`}
                      onChange={() => handleToggleParticipate(item)}
                      title="Tham gia giảng dạy trong học kỳ này"
                    />
                  </td>
                  <td>
                    <details>
                      <summary>{item.courses_can_teach.length} môn được dạy</summary>
                      {item.capabilities?.length ? <ul>
                        {item.capabilities.map((capability) => <li key={capability.course_id}>
                          {capability.course_name} ({capability.course_code}) · {capability.allowed && capability.confirmed ? "Được dạy" : !capability.allowed ? "Không được dạy" : "Chưa xác nhận"} · {capability.source ?? "Không rõ nguồn"}
                        </li>)}
                      </ul> : <small>Chưa có capability môn học.</small>}
                    </details>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div style={{ display: "inline-flex", gap: "4px" }}>
                      <button
                        type="button"
                        className={styles.editIcon}
                        onClick={() => openEdit(item)}
                        title="Chỉnh sửa giảng viên"
                      >
                        <PencilLine size={14} />
                      </button>
                      <button
                        type="button"
                        className={styles.editIcon}
                        onClick={() => {
                          setMergeSource(item);
                          setMergeTargetId("");
                        }}
                        title="Gộp vào giảng viên khác"
                      >
                        <Merge size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={8} style={{ textAlign: "center", padding: "24px", color: "var(--color-text-muted)" }}>
                  {loading ? "Đang tải danh sách giảng viên..." : "Không tìm thấy giảng viên nào phù hợp bộ lọc."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.stickyContinue} style={{ marginTop: 12 }}>
        <span>
          {!sourcesActive
            ? "Kích hoạt cả nguồn Lịch học và Nguyện vọng ở phía trên trước khi duyệt nguyện vọng."
            : data?.blockers_count
            ? `Cảnh báo: Còn ${data.blockers_count} vấn đề định danh cần xử lý.`
            : "Định danh giảng viên đã sẵn sàng để duyệt nguyện vọng."}
        </span>
        <button type="button" className={styles.primaryButton} onClick={onNext} disabled={!sourcesActive} title={!sourcesActive ? "Cần kích hoạt nguồn Lịch học và Nguyện vọng." : undefined}>
          Chuyển sang duyệt nguyện vọng
          <ArrowRight size={16} />
        </button>
      </div>

      {/* Modal Add Lecturer */}
      {addOpen && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalBox}>
            <div className={styles.modalHeader}>
              <h3>Thêm giảng viên mới</h3>
              <button type="button" onClick={() => setAddOpen(false)} style={{ background: "none", border: 0, cursor: "pointer" }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10 }}>
                <label className={styles.field}>
                  <span>Mã GV (nếu có)</span>
                  <input value={formCode} onChange={(e) => setFormCode(e.target.value)} placeholder="GV01" />
                </label>
                <label className={styles.field}>
                  <span>Họ và tên (*)</span>
                  <input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Nguyễn Văn A" />
                </label>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label className={styles.field}>
                  <span>Email</span>
                  <input value={formEmail} onChange={(e) => setFormEmail(e.target.value)} placeholder="anv@huce.edu.vn" />
                </label>
                <label className={styles.field}>
                  <span>Bộ môn / Khoa</span>
                  <input value={formDept} onChange={(e) => setFormDept(e.target.value)} placeholder="Bộ môn Tin học XD" />
                </label>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label className={styles.field}>
                  <span>Định mức tối thiểu (tiết)</span>
                  <input type="number" value={formQuotaMin} onChange={(e) => setFormQuotaMin(e.target.value)} />
                </label>
                <label className={styles.field}>
                  <span>Định mức tối đa (tiết)</span>
                  <input type="number" value={formQuotaMax} onChange={(e) => setFormQuotaMax(e.target.value)} />
                </label>
              </div>
              <label className={styles.field}>
                <span>Danh xưng phụ / Alias (ngăn cách bằng dấu phẩy)</span>
                <input value={formAliases} onChange={(e) => setFormAliases(e.target.value)} placeholder="Thầy A, A THXD" />
              </label>
              <label className={styles.switchLabel}>
                <input type="checkbox" checked={formParticipates} onChange={(e) => setFormParticipates(e.target.checked)} />
                <span>Tham gia giảng dạy trong học kỳ này</span>
              </label>
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.secondaryButton} onClick={() => setAddOpen(false)}>
                Hủy
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!formName.trim() || actionBusy === "save-add"}
                onClick={handleSaveAdd}
              >
                {actionBusy === "save-add" ? <LoaderCircle size={15} className={styles.spin} /> : null}
                Lưu giảng viên
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Edit Lecturer */}
      {editTarget && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalBox}>
            <div className={styles.modalHeader}>
              <h3>Chỉnh sửa thông tin giảng viên</h3>
              <button type="button" onClick={() => setEditTarget(null)} style={{ background: "none", border: 0, cursor: "pointer" }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10 }}>
                <label className={styles.field}>
                  <span>Mã GV</span>
                  <input value={formCode} onChange={(e) => setFormCode(e.target.value)} placeholder="GV01" />
                </label>
                <label className={styles.field}>
                  <span>Họ và tên (*)</span>
                  <input value={formName} onChange={(e) => setFormName(e.target.value)} />
                </label>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label className={styles.field}>
                  <span>Email</span>
                  <input value={formEmail} onChange={(e) => setFormEmail(e.target.value)} />
                </label>
                <label className={styles.field}>
                  <span>Bộ môn / Khoa</span>
                  <input value={formDept} onChange={(e) => setFormDept(e.target.value)} />
                </label>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label className={styles.field}>
                  <span>Định mức tối thiểu (tiết)</span>
                  <input type="number" value={formQuotaMin} onChange={(e) => setFormQuotaMin(e.target.value)} />
                </label>
                <label className={styles.field}>
                  <span>Định mức tối đa (tiết)</span>
                  <input type="number" value={formQuotaMax} onChange={(e) => setFormQuotaMax(e.target.value)} />
                </label>
              </div>
              <label className={styles.field}>
                <span>Danh xưng phụ / Alias (ngăn cách bằng dấu phẩy)</span>
                <input value={formAliases} onChange={(e) => setFormAliases(e.target.value)} placeholder="Thầy A, A THXD" />
              </label>
              <label className={styles.switchLabel}>
                <input type="checkbox" checked={formParticipates} onChange={(e) => setFormParticipates(e.target.checked)} />
                <span>Tham gia giảng dạy trong học kỳ này</span>
              </label>
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.secondaryButton} onClick={() => setEditTarget(null)}>
                Hủy
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!formName.trim() || actionBusy === "save-edit"}
                onClick={handleSaveEdit}
              >
                {actionBusy === "save-edit" ? <LoaderCircle size={15} className={styles.spin} /> : null}
                Cập nhật
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Merge Lecturer */}
      {mergeSource && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalBox}>
            <div className={styles.modalHeader}>
              <h3>Gộp định danh giảng viên</h3>
              <button type="button" onClick={() => setMergeSource(null)} style={{ background: "none", border: 0, cursor: "pointer" }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p>
                Gộp giảng viên nguồn: <strong>{mergeSource.name}</strong> ({mergeSource.code ?? "Chưa có mã"}) vào giảng viên đích.
              </p>
              <div className={styles.blockerAlert} style={{ background: "#eff6ff", borderColor: "#bfdbfe", color: "#1e40af" }}>
                <span>Toàn bộ phân công, danh xưng (alias) và nguyện vọng của giảng viên nguồn sẽ được chuyển sang giảng viên đích chuẩn. Giảng viên nguồn sẽ ngừng hoạt động.</span>
              </div>
              <label className={styles.field}>
                <span>Chọn giảng viên đích (chuẩn) (*)</span>
                <select value={mergeTargetId} onChange={(e) => setMergeTargetId(e.target.value)}>
                  <option value="">Chọn giảng viên đích…</option>
                  {data?.items
                    .filter((i) => i.id !== mergeSource.id)
                    .map((target) => (
                      <option key={target.id} value={target.id}>
                        {target.code ? `${target.code} · ` : ""}{target.name}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.secondaryButton} onClick={() => setMergeSource(null)}>
                Hủy
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!mergeTargetId || actionBusy === "merge"}
                onClick={handleMerge}
              >
                {actionBusy === "merge" ? <LoaderCircle size={15} className={styles.spin} /> : <Merge size={15} />}
                Xác nhận gộp
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Import Excel with Preview */}
      {importOpen && (
        <div className={styles.modalOverlay}>
          <div className={`${styles.modalBox} ${styles.modalBoxLarge}`}>
            <div className={styles.modalHeader}>
              <h3>Nhập danh sách giảng viên từ Excel (.xlsx / .xls)</h3>
              <button type="button" onClick={() => setImportOpen(false)} style={{ background: "none", border: 0, cursor: "pointer" }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--color-text-muted)" }}>
                Hệ thống ưu tiên nhận diện theo: <strong>Mã GV chính xác &gt; Alias đã xác nhận &gt; Họ tên chuẩn hóa &gt; Rà soát</strong>.
              </p>

              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <input
                  type="file"
                  accept=".xlsx,.xls"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleSelectImportFile(f);
                  }}
                />
                {importLoading ? <LoaderCircle size={18} className={styles.spin} /> : null}
              </div>

              {importPreview ? (
                <div>
                  <div className={styles.hitlSummaryStrip}>
                    <span>Tổng dòng: <strong>{importPreview.total_rows}</strong></span>
                    <span>Thêm mới: <strong style={{ color: "#047857" }}>{importPreview.to_add.length}</strong></span>
                    <span>Cập nhật: <strong style={{ color: "#1d4ed8" }}>{importPreview.to_update.length}</strong></span>
                    <span>Cần xác nhận: <strong style={{ color: "#b45309" }}>{importPreview.needs_confirmation.length}</strong></span>
                    <span>Nghi ngờ trùng: <strong style={{ color: "#b91c1c" }}>{importPreview.possible_duplicates.length}</strong></span>
                    <span>Bỏ qua: <strong>{importPreview.skipped.length}</strong></span>
                  </div>

                  {importPreview.needs_confirmation.length > 0 ? (
                    <div className={styles.previewCategory}>
                      <div className={styles.previewCategoryTitle} style={{ color: "#b45309" }}>
                        <span>Dòng cần xác nhận ({importPreview.needs_confirmation.length})</span>
                      </div>
                      <div style={{ maxHeight: "140px", overflowY: "auto", fontSize: "0.78rem" }}>
                        {importPreview.needs_confirmation.map((r, i) => (
                          <div key={i} style={{ padding: "4px 0", borderBottom: "1px solid var(--color-border)" }}>
                            Dòng {r.row}: <strong>{r.name}</strong> ({r.code || "không mã"}) — {r.issues.join("; ")}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {importPreview.possible_duplicates.length > 0 ? (
                    <div className={styles.previewCategory}>
                      <div className={styles.previewCategoryTitle} style={{ color: "#b91c1c" }}>
                        <span>Dòng trùng lặp ({importPreview.possible_duplicates.length})</span>
                      </div>
                      <div style={{ maxHeight: "140px", overflowY: "auto", fontSize: "0.78rem" }}>
                        {importPreview.possible_duplicates.map((r, i) => (
                          <div key={i} style={{ padding: "4px 0", borderBottom: "1px solid var(--color-border)" }}>
                            Dòng {r.row}: <strong>{r.name}</strong> ({r.code || "không mã"}) — {r.issues.join("; ")}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {importResult ? (
                <div className={styles.cleanLog} style={{ padding: 14 }}>
                  <CheckCircle2 size={20} />
                  <div>
                    <strong>Nhập danh sách thành công!</strong>
                    <div>Đã thêm: {importResult.added}, Đã cập nhật: {importResult.updated}, Alias tạo mới: {importResult.aliases_created}</div>
                  </div>
                </div>
              ) : null}
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.secondaryButton} onClick={() => setImportOpen(false)}>
                Đóng
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!importPreview || !importPreview.can_commit || actionBusy === "commit-import"}
                onClick={handleCommitImport}
              >
                {actionBusy === "commit-import" ? <LoaderCircle size={15} className={styles.spin} /> : <Check size={15} />}
                Xác nhận nhập danh sách
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function InputView({
  busy,
  metrics,
  semesterId,
  activeSemester,
  onUpload,
  onNext,
  onReload,
}: {
  busy: string | null;
  metrics: DashboardMetrics;
  semesterId: number | null;
  activeSemester: Semester | null;
  onUpload: (schedule: File, preference: File) => void;
  onNext: () => void;
  onReload?: () => void;
}) {
  const scheduleRef = useRef<HTMLInputElement>(null);
  const preferenceRef = useRef<HTMLInputElement>(null);
  const [schedule, setSchedule] = useState<File | null>(null);
  const [preference, setPreference] = useState<File | null>(null);
  const [sourceState, setSourceState] = useState<SourceState | null>(null);
  const sourcesActive = Boolean(sourceState?.active_schedule_source_id && sourceState?.active_preference_source_id);

  return (
    <section className={styles.viewEnter}>
      <PageHeading
        eyebrow="BƯỚC 03"
        title={`Nhập dữ liệu học kỳ & Rà soát giảng viên${activeSemester ? ` · ${activeSemester.name}` : ""}`}
        text="Hai file được đọc riêng, sau đó đối chiếu và chuẩn hóa danh tính giảng viên trước khi duyệt nguyện vọng."
      />
      <div className={styles.dualUpload}>
        <UploadCard
          number="01"
          title="Thời khóa biểu kỳ này"
          text="Lớp, môn, thứ, tiết, phòng và tuần học"
          file={schedule}
          inputRef={scheduleRef}
          onChange={setSchedule}
        />
        <UploadCard
          number="02"
          title="Nguyện vọng giảng viên"
          text="Ngày bận, ưu tiên, seminar và phân công mong muốn"
          file={preference}
          inputRef={preferenceRef}
          onChange={setPreference}
        />
      </div>
      <div className={styles.importBar}>
        <span>
          {metrics.classes
            ? `${metrics.classes} lớp và ${metrics.lecturers} giảng viên đang có trong phiên.`
            : "Chọn đủ hai file để bắt đầu chuẩn hóa."}
        </span>
        <div>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={!schedule || !preference || busy === "inputs"}
            onClick={() => (schedule && preference ? onUpload(schedule, preference) : undefined)}
          >
            {busy === "inputs" ? <LoaderCircle size={17} className={styles.spin} /> : <Sparkles size={17} />}
            Lưu nguồn ứng viên
          </button>
        </div>
      </div>
      {metrics.classes ? (
        <div className={styles.summaryStrip}>
          <span>
            <strong>{metrics.classes}</strong>Lớp học phần
          </span>
          <span>
            <strong>{metrics.locked_classes}</strong>Phân công đã khóa
          </span>
          <span>
            <strong>{metrics.merged_suggestions}</strong>Nhóm ghép đề xuất
          </span>
          <span>
            <strong>{metrics.validation_errors}</strong>Lỗi cần xử lý
          </span>
        </div>
      ) : null}

      {semesterId ? <SourceAuthorityPanel semesterId={semesterId} refreshKey={busy} onChanged={onReload} onStateChanged={setSourceState} /> : null}

      {/* Lecturer Human-in-the-Loop Review Section */}
      <LecturerHitlSection semesterId={semesterId} onReload={onReload} onNext={onNext} sourcesActive={sourcesActive} />
    </section>
  );
}

function UploadCard({
  number,
  title,
  text,
  file,
  inputRef,
  onChange,
}: {
  number: string;
  title: string;
  text: string;
  file: File | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onChange: (file: File | null) => void;
}) {
  return (
    <div
      className={`${styles.uploadCard} ${file ? styles.uploadReady : ""}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const selected = Array.from(event.dataTransfer.files).find(
          (item) => /\.xlsx?$/i.test(item.name) || /\.xls$/i.test(item.name)
        );
        if (selected) onChange(selected);
      }}
    >
      <input
        ref={inputRef}
        hidden
        type="file"
        accept=".xls,.xlsx"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      <div className={styles.uploadTitle}>
        <span>{number}</span>
        <div>
          <strong>{title}</strong>
          <small>{text}</small>
        </div>
      </div>
      <div className={styles.fileSelection}>
        <FileSpreadsheet size={22} />
        <span>
          <strong>{file?.name ?? "Chưa chọn file"}</strong>
          <small>{file ? `${(file.size / 1024).toFixed(1)} KB · sẵn sàng` : "Kéo thả hoặc chọn từ máy"}</small>
        </span>
        {file ? (
          <button type="button" aria-label={`Bỏ ${title}`} onClick={() => onChange(null)}>
            <X size={16} />
          </button>
        ) : (
          <button type="button" onClick={() => inputRef.current?.click()}>
            Chọn file
          </button>
        )}
      </div>
    </div>
  );
}

function getPreferenceSortRank(item: PreferenceDraft): number {
  if (item.status === "REJECTED" || item.status === "INTERPRETED") return 2;
  if (item.status === "CONFIRMED") return 1;
  return 0; // Actionable (DRAFT, NEEDS_REVIEW, needs_review=true)
}

export function PreferenceReview({
  drafts,
  lecturers,
  semesterId,
  busy,
  onSave,
  onConfirmHigh,
  onApply,
  onCreate,
  onNext,
}: {
  drafts: PreferenceDraft[];
  lecturers: Lecturer[];
  semesterId: number | null;
  busy: string | null;
  onSave: (item: PreferenceDraft, payload: Partial<PreferenceDraft>) => void;
  onConfirmHigh: () => void;
  onApply: (ids: number[]) => void;
  onCreate: (payload: Record<string, unknown>) => Promise<void>;
  onNext: () => void;
}) {
  const [tab, setTab] = useState<"ALL" | "REVIEW" | "CONFIRMED" | "REJECTED" | "BY_LECTURER">("ALL");
  const [filter, setFilter] = useState<"ALL" | "HIGH" | "REVIEW" | "CONFIRMED" | "REJECTED">("ALL");
  const [selectedLecturerId, setSelectedLecturerId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [rejectingDraft, setRejectingDraft] = useState<PreferenceDraft | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const pending = drafts.filter(
    (item) => item.status === "DRAFT" || item.status === "NEEDS_REVIEW" || item.needs_review
  );
  const confirmedDrafts = drafts.filter((item) => item.status === "CONFIRMED");
  const rejectedDrafts = drafts.filter((item) => item.status === "REJECTED");
  const applicable = drafts.filter(
    (item) =>
      item.status === "CONFIRMED" &&
      !item.needs_review &&
      item.is_confirmable === true &&
      !item.applied_constraint_id &&
      !item.applied_seminar_id
  );

  const visible = useMemo(() => {
    let list: PreferenceDraft[];
    if (tab === "REVIEW") {
      list = drafts.filter(
        (item) => item.status === "DRAFT" || item.status === "NEEDS_REVIEW" || item.needs_review
      );
    } else if (tab === "CONFIRMED") {
      list = drafts.filter((item) => item.status === "CONFIRMED");
    } else if (tab === "REJECTED") {
      list = drafts.filter((item) => item.status === "REJECTED");
    } else if (tab === "BY_LECTURER") {
      list =
        selectedLecturerId === null
          ? [...drafts]
          : drafts.filter((item) => item.lecturer_id === selectedLecturerId);
      // Sort under lecturer: Actionable -> Confirmed -> Rejected
      list.sort((a, b) => getPreferenceSortRank(a) - getPreferenceSortRank(b));
      return list;
    } else {
      list = drafts.filter(
        (item) =>
          filter === "ALL" ||
          (filter === "REVIEW"
            ? item.needs_review
            : filter === item.confidence || filter === item.status)
      );
    }
    return list;
  }, [drafts, tab, filter, selectedLecturerId]);

  return (
    <section className={styles.viewEnter}>
      <PageHeading
        eyebrow="BƯỚC 04"
        title="Duyệt nguyện vọng đã chuẩn hóa"
        text="Parser chỉ tạo bản nháp. Chỉ quy tắc được trưởng bộ môn xác nhận và áp dụng mới đi vào solver. Các bản nháp bị từ chối có thể khôi phục bất cứ lúc nào."
        action={
          <div className={styles.reviewActions}>
            <span className={pending.length ? styles.reviewBadge : styles.readyBadge}>
              {pending.length} cần xử lý
            </span>
            <button type="button" className={styles.secondaryButton} onClick={() => setAdding((value) => !value)}>
              <Plus size={16} />
              Thêm thủ công
            </button>
          </div>
        }
      />
      <div className={styles.importBar}>
        <div className={styles.contextSegments}>
          <button
            type="button"
            className={tab === "ALL" ? styles.contextActive : ""}
            onClick={() => setTab("ALL")}
          >
            Tất cả ({drafts.length})
          </button>
          <button
            type="button"
            className={tab === "REVIEW" ? styles.contextActive : ""}
            onClick={() => setTab("REVIEW")}
          >
            Cần xác nhận ({pending.length})
          </button>
          <button
            type="button"
            className={tab === "CONFIRMED" ? styles.contextActive : ""}
            onClick={() => setTab("CONFIRMED")}
          >
            Đã xác nhận ({confirmedDrafts.length})
          </button>
          <button
            type="button"
            className={tab === "REJECTED" ? styles.contextActive : ""}
            onClick={() => setTab("REJECTED")}
          >
            Đã từ chối ({rejectedDrafts.length})
          </button>
          <button
            type="button"
            className={tab === "BY_LECTURER" ? styles.contextActive : ""}
            onClick={() => setTab("BY_LECTURER")}
          >
            Theo giảng viên
          </button>
        </div>
        <div>
          {tab === "BY_LECTURER" ? (
            <select
              aria-label="Chọn giảng viên"
              value={selectedLecturerId ?? ""}
              onChange={(event) => setSelectedLecturerId(event.target.value ? Number(event.target.value) : null)}
            >
              <option value="">Tất cả giảng viên</option>
              {lecturers.map((lec) => (
                <option key={lec.id} value={lec.id}>
                  {lec.code ? `${lec.code} · ` : ""}
                  {lec.name}
                </option>
              ))}
            </select>
          ) : tab === "ALL" ? (
            <select
              aria-label="Lọc bản nháp"
              value={filter}
              onChange={(event) => setFilter(event.target.value as typeof filter)}
            >
              <option value="ALL">Mọi trạng thái</option>
              <option value="HIGH">Độ tin cậy cao</option>
              <option value="REVIEW">Cần rà soát</option>
              <option value="CONFIRMED">Đã xác nhận</option>
              <option value="REJECTED">Đã từ chối</option>
            </select>
          ) : null}
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={!semesterId || !!busy}
            onClick={onConfirmHigh}
          >
            Xác nhận tất cả HIGH
          </button>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={!applicable.length || !!busy}
            onClick={() => onApply(applicable.map((item) => item.id))}
          >
            Áp dụng đã xác nhận ({applicable.length})
          </button>
        </div>
      </div>
      {adding ? (
        <ManualDraftComposer
          lecturers={lecturers}
          semesterId={semesterId}
          busy={busy === "new-preference"}
          onClose={() => setAdding(false)}
          onCreate={onCreate}
        />
      ) : null}
      <div className={styles.preferenceList}>
        {visible.length ? (
          visible.map((item) => (
            <DraftPreferenceRow
              key={`${item.id}-${item.status}-${item.lecturer_id}`}
              item={item}
              lecturers={lecturers}
              semesterId={semesterId}
              busy={busy === `draft-${item.id}`}
              onSave={onSave}
              onRejectClick={(draft) => {
                setRejectReason("");
                setRejectingDraft(draft);
              }}
            />
          ))
        ) : (
          <div className={styles.emptyPanel}>
            <FileCheck2 size={24} />
            <strong>Không có bản nháp trong bộ lọc</strong>
            <span>Upload file nguyện vọng hoặc đổi bộ lọc.</span>
          </div>
        )}
      </div>

      {rejectingDraft && (
        <div className={styles.fixedScreenModalOverlay} onClick={() => setRejectingDraft(null)}>
          <div className={styles.fixedModalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.fixedModalHeader}>
              <div className={styles.fixedModalTitleRow}>
                <span className={styles.rejectHeaderBadge}>
                  <X size={18} />
                </span>
                <div>
                  <h3>Từ chối bản nháp nguyện vọng</h3>
                  <small>Quy tắc này sẽ không đi vào solver và có thể khôi phục sau</small>
                </div>
              </div>
              <button
                type="button"
                className={styles.closeModalBtn}
                onClick={() => setRejectingDraft(null)}
                aria-label="Đóng hộp thoại"
              >
                <X size={18} />
              </button>
            </div>
            <div className={styles.fixedModalBody}>
              <div className={styles.rejectItemSummary}>
                <strong>{rejectingDraft.lecturer ?? rejectingDraft.lecturer_alias ?? "Chưa xác định"}</strong>
                <p>{rejectingDraft.raw_text || `${rejectingDraft.constraint_type} (${rejectingDraft.day_scope ?? ""})`}</p>
                <small>{rejectingDraft.source_sheet}!{rejectingDraft.source_cell}</small>
              </div>
              <label className={styles.field}>
                <span>Lý do từ chối (bắt buộc hoặc ghi chú)</span>
                <textarea
                  rows={3}
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="VD: Không phù hợp với phân công kỳ này / Giảng viên đã thỏa thuận riêng..."
                  autoFocus
                />
              </label>
            </div>
            <div className={styles.fixedModalFooter}>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => setRejectingDraft(null)}
              >
                Hủy
              </button>
              <button
                type="button"
                className={styles.rejectConfirmButton}
                onClick={() => {
                  onSave(rejectingDraft, {
                    status: "REJECTED",
                    rejected_reason: rejectReason.trim() || "Trưởng bộ môn từ chối",
                  });
                  setRejectingDraft(null);
                }}
              >
                <Check size={16} /> Xác nhận từ chối
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={styles.stickyContinue}>
        <span>RAW_NOTE và các bản nháp bị từ chối sẽ không bao giờ được đưa vào solver.</span>
        <button type="button" className={styles.primaryButton} disabled={!drafts.length} onClick={onNext}>
          Mở bàn phân công
          <ArrowRight size={16} />
        </button>
      </div>
    </section>
  );
}

const draftScopes = ["T2", "T3", "T4", "T5", "T6", "T7", "CN", "ALL_WEEKDAYS", "ALL_DAYS"];

function parseDraftPeriods(value:string):number[] {
  if (!value.trim()) return [];
  return value.split(',').flatMap(part=>{
    const match=part.trim().match(/^(\d+)(?:\s*[-–]\s*(\d+))?$/);
    if (!match) return [0];
    const first=Number(match[1]),last=Number(match[2] ?? match[1]);
    if (first<1 || last>15 || first>last) return [0];
    return Array.from({length:last-first+1},(_,i)=>first+i);
  });
}

function ManualDraftComposer({ lecturers, semesterId, busy, onCreate, onClose }: { lecturers: Lecturer[]; semesterId: number | null; busy: boolean; onCreate: (payload: Record<string, unknown>) => Promise<void>; onClose: () => void }) {
  const [lecturerId, setLecturerId] = useState("");
  const [context, setContext] = useState<"TEACHING" | "SEMINAR" | "MIXED">("TEACHING");
  const [type, setType] = useState("UNAVAILABLE");
  const [scope, setScope] = useState("");
  const [periodText, setPeriodText] = useState("");
  const [startDate, setStartDate] = useState(""); const [endDate, setEndDate] = useState("");
  const [hardness, setHardness] = useState<"hard" | "soft">("soft"); const [weight, setWeight] = useState(0.8);
  const [numeric, setNumeric] = useState(""); const [seminarLink, setSeminarLink] = useState(""); const [note, setNote] = useState("");
  const [mixedSeminarScope, setMixedSeminarScope] = useState(""); const [mixedSeminarPeriods, setMixedSeminarPeriods] = useState("");
  const [mixedTeachingScope, setMixedTeachingScope] = useState(""); const [mixedTeachingPeriods, setMixedTeachingPeriods] = useState("");
  const periods = parseDraftPeriods;
  const selected = lecturers.find((item) => item.id === Number(lecturerId));
  const setContextSafely = (next: typeof context) => { setContext(next); setType(next === "SEMINAR" ? "SEMINAR_COMMITMENT" : "UNAVAILABLE"); };
  const basePart = (partContext: "TEACHING" | "SEMINAR", partType: string, partScope: string, partPeriods: string) => ({ context_type: partContext, constraint_type: partType, day_scope: partScope || null, periods: periods(partPeriods), start_date: startDate || null, end_date: endDate || null, hardness, weight, numeric_value: numeric ? Number(numeric) : null, seminar_link: partContext === "SEMINAR" ? seminarLink || null : null, note, status: "DRAFT" });
  const makePayload = (status: "DRAFT" | "CONFIRMED") => {
    if (context === "MIXED") {
      return { lecturer_id: lecturerId ? Number(lecturerId) : null, context_type: "MIXED", constraint_type: "RAW_NOTE", day_scope: null, periods: [], hardness, weight, note, status: "DRAFT", parts: [
        { ...basePart("SEMINAR", mixedSeminarPeriods ? "SEMINAR_COMMITMENT" : "SEMINAR_NOTE", mixedSeminarScope, mixedSeminarPeriods), status },
        { ...basePart("TEACHING", "PREFERRED_PERIOD", mixedTeachingScope, mixedTeachingPeriods), status },
      ] };
    } else {
      return { lecturer_id: lecturerId ? Number(lecturerId) : null, ...basePart(context, type, scope, periodText), status };
    }
  };
  const validationKey=JSON.stringify(makePayload('DRAFT'));
  const [validation,setValidation]=useState({is_confirmable:false,validation_errors:[] as Array<{code:string;field:string;message:string}>});
  const [validatedKey,setValidatedKey]=useState<string | null>(null);
  useEffect(()=>{
    if (!semesterId) return;
    let current=true;
    const timer=setTimeout(()=>{void api.validateNewPreferenceDraft(JSON.parse(validationKey),semesterId).then(result=>{if(current){setValidation(result);setValidatedKey(validationKey);}}).catch(()=>{if(current){setValidation({is_confirmable:false,validation_errors:[{code:'VALIDATION_UNAVAILABLE',field:'',message:'Chưa kiểm tra được dữ liệu với máy chủ.'}]});setValidatedKey(validationKey);}});},150);
    return ()=>{current=false;clearTimeout(timer);};
  },[semesterId,validationKey]);
  const save = async (status: 'DRAFT' | 'CONFIRMED') => {
    if (!lecturerId) return;
    await onCreate(makePayload(status));
    onClose();
  };
  const ruleOptions = preferenceRuleTypesForContext(context);
  return <div className={styles.flatPanel}>
    <span className={styles.eyebrow}>RÀNG BUỘC THỦ CÔNG</span><strong>Thêm dưới dạng bản nháp có ngữ cảnh rõ ràng</strong>
    <div aria-live="polite">{validation.validation_errors.map((error,index)=><p key={`${error.code}-${index}`}>{error.message}</p>)}</div>
    <div className={styles.composerGrid}><label className={styles.field}><span>1. Giảng viên</span><select value={lecturerId} onChange={(event) => setLecturerId(event.target.value)}><option value="">Chọn giảng viên…</option>{lecturers.map((item) => <option key={item.id} value={item.id}>{item.code ? `${item.code} · ` : ""}{item.name}</option>)}</select></label></div>
    <div className={styles.field}><span>2. Ngữ cảnh</span><div className={styles.contextSegments}>{(["TEACHING", "SEMINAR", "MIXED"] as const).map((value) => <button type="button" key={value} className={context === value ? styles.contextActive : ""} onClick={() => setContextSafely(value)}>{value === "TEACHING" ? "Lịch dạy" : value === "SEMINAR" ? "Lịch seminar" : "Cả hai"}</button>)}</div></div>
    {context !== "MIXED" ? <><div className={styles.composerGrid}><label className={styles.field}><span>3. Rule type</span><select value={type} onChange={(event) => setType(event.target.value)}>{ruleOptions.map((value) => <option key={value}>{value}</option>)}</select></label><label className={styles.field}><span>4. Ngày / phạm vi</span><select value={scope} onChange={(event) => setScope(event.target.value)}><option value="">Chưa xác định</option>{draftScopes.map((value) => <option key={value}>{value}</option>)}</select></label><label className={styles.field}><span>5. Tiết</span><input value={periodText} onChange={(event) => setPeriodText(event.target.value)} placeholder="4-6" /></label></div></> : <div className={styles.inlineFields}><div className={styles.flatPanel}><strong>Phần A · Seminar</strong><label className={styles.field}><span>Ngày</span><select value={mixedSeminarScope} onChange={(event) => setMixedSeminarScope(event.target.value)}><option value="">Chưa xác định</option>{draftScopes.map((value) => <option key={value}>{value}</option>)}</select></label><label className={styles.field}><span>Tiết (để trống nếu chưa rõ)</span><input value={mixedSeminarPeriods} onChange={(event) => setMixedSeminarPeriods(event.target.value)} /></label></div><div className={styles.flatPanel}><strong>Phần B · Lịch dạy</strong><label className={styles.field}><span>Ngày ưu tiên</span><select value={mixedTeachingScope} onChange={(event) => setMixedTeachingScope(event.target.value)}><option value="">Chưa xác định</option>{draftScopes.map((value) => <option key={value}>{value}</option>)}</select></label><label className={styles.field}><span>Tiết</span><input value={mixedTeachingPeriods} onChange={(event) => setMixedTeachingPeriods(event.target.value)} /></label></div></div>}
    <div className={styles.composerGrid}><label className={styles.field}><span>6. Từ ngày</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label className={styles.field}><span>Đến ngày</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label><label className={styles.field}><span>7. Hard/Soft</span><select value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}><option value="soft">SOFT</option><option value="hard">HARD</option></select></label><label className={styles.field}><span>8. Weight</span><input type="number" min="0" max="1" step="0.1" value={Number.isNaN(weight) ? "" : weight} onChange={(event) => setWeight(event.target.value === "" ? NaN : Number(event.target.value))} /></label><label className={styles.field}><span>9. Giá trị số</span><input type="number" value={numeric} onChange={(event) => setNumeric(event.target.value)} /></label>{context !== "TEACHING" ? <label className={styles.field}><span>10. Liên kết seminar</span><input value={seminarLink} onChange={(event) => setSeminarLink(event.target.value)} placeholder="SEM-THOAN" /></label> : null}</div>
    <label className={styles.field}><span>11. Ghi chú / nguyên văn</span><textarea value={note} onChange={(event) => setNote(event.target.value)} /></label>
    <div className={styles.livePreview}><span>APP SẼ HIỂU RÀNG BUỘC NÀY LÀ:</span><strong>{selected?.name ?? "Chưa chọn giảng viên"}</strong><p>Ngữ cảnh: {context === "TEACHING" ? "Lịch dạy" : context === "SEMINAR" ? "Lịch seminar" : "Cả hai · tách thành 2 draft"}<br />{context === "MIXED" ? "Phần seminar và phần lịch dạy được xác nhận độc lập." : `${type} · ${scope}${periodText ? ` · tiết ${periodText}` : " · tiết chưa xác định"}`}<br />{hardness.toUpperCase()} · {weight.toFixed(1)}</p></div>
    <div className={styles.dialogFooter}><button type="button" className={styles.ghostButton} onClick={onClose}>Hủy</button><button type="button" className={styles.secondaryButton} disabled={busy || !lecturerId} onClick={() => void save("DRAFT")}>Lưu bản nháp</button><button type="button" className={styles.primaryButton} disabled={busy || validatedKey!==validationKey || !validation.is_confirmable} onClick={() => void save("CONFIRMED")}>Lưu và xác nhận</button></div>
  </div>;
}

function DraftPreferenceRow({
  item,
  lecturers,
  semesterId,
  busy,
  onSave,
  onRejectClick,
}: {
  item: PreferenceDraft;
  lecturers: Lecturer[];
  semesterId: number | null;
  busy: boolean;
  onSave: (item: PreferenceDraft, payload: Partial<PreferenceDraft>) => void;
  onRejectClick: (item: PreferenceDraft) => void;
}) {
  const [lecturerId, setLecturerId] = useState(String(item.lecturer_id ?? ""));
  const [type, setType] = useState(item.constraint_type);
  const [context, setContext] = useState(item.context_type ?? "TEACHING");
  const [scope, setScope] = useState(item.day_scope ?? "ALL_WEEKDAYS");
  const [periods, setPeriods] = useState(
    item.periods.length ? `${Math.min(...item.periods)}-${Math.max(...item.periods)}` : ""
  );
  const [hardness, setHardness] = useState(item.hardness);
  const [weight, setWeight] = useState(item.weight);
  const [startDate, setStartDate] = useState(item.start_date ?? "");
  const [endDate, setEndDate] = useState(item.end_date ?? "");
  const [numeric, setNumeric] = useState(item.numeric_value == null ? "" : String(item.numeric_value));
  const [seminarLink, setSeminarLink] = useState(item.seminar_link ?? "");

  useEffect(() => {
    setLecturerId(String(item.lecturer_id ?? ""));
  }, [item.lecturer_id]);

  const parsedPeriods = () => {
    const bounds = (periods.match(/\d+/g) ?? []).map(Number);
    return bounds.length === 2
      ? Array.from({ length: bounds[1] - bounds[0] + 1 }, (_, index) => bounds[0] + index)
      : bounds;
  };
  const availableTypes = preferenceRuleTypesForContext(context);
  const payload = (status: PreferenceDraft["status"]): Partial<PreferenceDraft> => ({
    lecturer_id: lecturerId ? Number(lecturerId) : null,
    context_type: context,
    constraint_type: type,
    day_scope: scope || null,
    periods: parsedPeriods(),
    start_date: startDate || null,
    end_date: endDate || null,
    hardness,
    weight,
    numeric_value: numeric ? Number(numeric) : null,
    seminar_link: context === "SEMINAR" ? seminarLink || null : null,
    status,
  });

  const isRejected = item.status === "REJECTED";
  const isInterpreted = item.status === "INTERPRETED";

  const validationKey = JSON.stringify(payload(item.status));
  const [validation, setValidation] = useState({
    is_confirmable: item.is_confirmable ?? true,
    validation_errors: item.validation_errors ?? [],
  });
  const [, setValidatedKey] = useState<string | null>(null);

  useEffect(() => {
    if (!semesterId || isRejected || isInterpreted) return;
    let current = true;
    const timer = setTimeout(() => {
      void api
        .validatePreferenceDraft(item.id, JSON.parse(validationKey), semesterId)
        .then((result) => {
          if (current) {
            setValidation(result);
            setValidatedKey(validationKey);
          }
        })
        .catch(() => {
          if (current) {
            setValidation({
              is_confirmable: false,
              validation_errors: [
                {
                  code: "VALIDATION_UNAVAILABLE",
                  field: "",
                  message: "Chưa kiểm tra được dữ liệu với máy chủ.",
                },
              ],
            });
            setValidatedKey(validationKey);
          }
        });
    }, 150);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [item.id, semesterId, validationKey, isRejected, isInterpreted]);

  return (
    <article className={`${styles.preferenceRow} ${isRejected ? styles.preferenceRowRejected : ""}`}>
      <span
        className={`${styles.preferenceState} ${
          isRejected ? styles.stateRejected : item.status === "CONFIRMED" ? styles.stateConfirmed : ""
        }`}
      >
        {isRejected ? <X size={15} /> : item.status === "CONFIRMED" ? <Check size={15} /> : <PencilLine size={15} />}
      </span>
      <div className={styles.preferenceCopy}>
        <div>
          <strong>{item.lecturer ?? item.lecturer_alias ?? "Chưa xác định"}</strong>
          <span>
            {item.context_type === "TEACHING"
              ? "Lịch dạy"
              : item.context_type === "SEMINAR"
              ? "Seminar"
              : "Cả hai · Cần tách"}
          </span>
          <span>{item.constraint_type}</span>
          <span>{item.confidence}</span>
          {isRejected ? <span className={styles.rejectedBadge}>Đã từ chối</span> : null}
          {item.status === "NEEDS_REVIEW" ? <span className={styles.reviewBadge}>Cần rà soát</span> : null}
        </div>
        <p>{item.raw_text || "Không có câu gốc"}</p>
        <small className={styles.normalizedRule}>
          {item.source_sheet}!{item.source_cell}
          {item.review_reason ? ` · ${item.review_reason}` : ""}
        </small>
        {isRejected && item.rejected_reason ? (
          <div className={styles.rejectionReasonBox}>
            <strong>Lý do từ chối:</strong> {item.rejected_reason}
          </div>
        ) : null}
      </div>
      <div className={styles.preferenceEditor}>
        <label className={styles.field}>
          <span>Giảng viên</span>
          <select value={lecturerId} onChange={(event) => setLecturerId(event.target.value)}>
            <option value="">Cần resolve…</option>
            {lecturers.map((lecturer) => (
              <option key={lecturer.id} value={lecturer.id}>
                {lecturer.code ? `${lecturer.code} · ` : ""}
                {lecturer.name}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Ngữ cảnh</span>
          <select
            value={context}
            onChange={(event) => {
              const next = event.target.value as typeof context;
              setContext(next);
              setType(next === "SEMINAR" ? "SEMINAR_COMMITMENT" : "RAW_NOTE");
            }}
          >
            <option value="TEACHING">Lịch dạy</option>
            <option value="SEMINAR">Lịch seminar</option>
            <option value="MIXED">Cả hai · cần tách</option>
          </select>
        </label>
        <label className={styles.field}>
          <span>Loại</span>
          <select value={type} onChange={(event) => setType(event.target.value)}>
            {availableTypes.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Phạm vi</span>
          <select value={scope} onChange={(event) => setScope(event.target.value)}>
            {draftScopes.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Tiết</span>
          <input value={periods} onChange={(event) => setPeriods(event.target.value)} placeholder="4-6" />
        </label>
        <label className={styles.field}>
          <span>Từ ngày</span>
          <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </label>
        <label className={styles.field}>
          <span>Đến ngày</span>
          <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
        </label>
        <label className={styles.field}>
          <span>Giá trị số</span>
          <input type="number" value={numeric} onChange={(event) => setNumeric(event.target.value)} />
        </label>
        {context === "SEMINAR" ? (
          <label className={styles.field}>
            <span>Liên kết seminar</span>
            <input value={seminarLink} onChange={(event) => setSeminarLink(event.target.value)} />
          </label>
        ) : null}
        <label className={styles.field}>
          <span>Độ cứng</span>
          <select value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}>
            <option value="soft">SOFT</option>
            <option value="hard">HARD</option>
          </select>
        </label>
        <label className={styles.field}>
          <span>Weight</span>
          <input
            type="number"
            min="0"
            max="1"
            step="0.1"
            value={weight}
            onChange={(event) => setWeight(Number(event.target.value))}
          />
        </label>
      </div>
      {validation.validation_errors.length > 0 && (
        <div className={styles.validationErrorInline}>
          {validation.validation_errors.map((error, idx) => (
            <p key={`${error.code}-${idx}`} style={{ margin: 0 }}>
              {error.message}
            </p>
          ))}
        </div>
      )}
      <div className={styles.rowActions}>
        {isRejected ? (
          <button
            type="button"
            className={styles.restoreButton}
            disabled={busy}
            onClick={() => onSave(item, { status: "NEEDS_REVIEW", rejected_reason: null, rejected_at: null })}
            title="Khôi phục trạng thái cần rà soát"
          >
            <RotateCcw size={14} />Khôi phục
          </button>
        ) : (
          <>
            <button
              type="button"
              className={styles.saveIcon}
              disabled={
                busy ||
                !lecturerId ||
                type === "RAW_NOTE" ||
                type === "SEMINAR_NOTE" ||
                context === "MIXED" ||
                !validation.is_confirmable
              }
              onClick={() => onSave(item, payload("CONFIRMED"))}
              title="Xác nhận nguyện vọng"
            >
              <Check size={14} />Xác nhận
            </button>
            <button
              type="button"
              className={styles.deleteIcon}
              disabled={busy}
              onClick={() => onRejectClick(item)}
              title="Từ chối nguyện vọng"
            >
              <X size={14} />Từ chối
            </button>
          </>
        )}
      </div>
    </article>
  );
}


function PreferenceRow({ item, lecturers, busy, onSave, onDelete }: { item: Constraint; lecturers: Lecturer[]; busy: boolean; onSave: (item: Constraint, payload: Partial<Constraint>) => void; onDelete: (item: Constraint) => void }) {
  const [hardness, setHardness] = useState(item.hardness);
  const [weight, setWeight] = useState(item.weight);
  const [active, setActive] = useState(item.active);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(item.name);
  const [rawText, setRawText] = useState(item.raw_text ?? "");
  const [type, setType] = useState(item.constraint_type);
  const [lecturerId, setLecturerId] = useState(String(item.lecturer_id ?? ""));
  const [weekday, setWeekday] = useState(String(item.target?.weekday ?? ""));
  const [periods, setPeriods] = useState(periodLabel(item.target));
  const save = () => onSave(item, { name, raw_text: rawText, constraint_type: type, lecturer_id: lecturerId ? Number(lecturerId) : null, target: makeTarget(weekday, periods, item.target), hardness, weight: hardness === "hard" ? 1 : weight, active, confirmed: true });
  return <article className={styles.preferenceRow}>
    <span className={`${styles.preferenceState} ${item.confirmed ? styles.stateConfirmed : ""}`}>{item.confirmed ? <Check size={15} /> : <PencilLine size={15} />}</span>
    <div className={styles.preferenceCopy}><div><strong>{item.lecturer ?? "Toàn bộ giảng viên"}</strong><span>{item.constraint_type.replaceAll("_", " ")}</span></div><p>{item.raw_text || item.name}</p><small className={styles.normalizedRule}>→ {item.normalized_text || item.name}</small></div>
    <div className={styles.preferenceControls}><select aria-label="Mức ràng buộc" value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}><option value="soft">Ưu tiên mềm</option><option value="hard">Bắt buộc</option></select><label><span>Trọng số {hardness === "hard" ? "1.0" : weight.toFixed(1)}</span><input type="range" min="0" max="1" step="0.1" disabled={hardness === "hard"} value={hardness === "hard" ? 1 : weight} onChange={(event) => setWeight(Number(event.target.value))} /></label><label className={styles.switchLabel}><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /><span>Áp dụng</span></label></div>
    <div className={styles.rowActions}><button type="button" className={styles.editIcon} disabled={busy} aria-label="Chỉnh sửa ràng buộc" onClick={() => setEditing((value) => !value)}><PencilLine size={15} /></button><button type="button" className={styles.saveIcon} disabled={busy} aria-label="Lưu và xác nhận" onClick={save}>{busy ? <LoaderCircle size={16} className={styles.spin} /> : <Check size={16} />}</button><button type="button" className={styles.deleteIcon} disabled={busy} aria-label="Xóa ràng buộc" onClick={() => onDelete(item)}><Trash2 size={15} /></button></div>
    {editing ? <div className={styles.preferenceEditor}><label className={styles.field}><span>Tên ràng buộc</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label className={styles.field}><span>Giảng viên</span><select value={lecturerId} onChange={(event) => setLecturerId(event.target.value)}><option value="">Toàn bộ giảng viên</option>{lecturers.map((lecturer) => <option key={lecturer.id} value={lecturer.id}>{lecturer.name}</option>)}</select></label><label className={styles.field}><span>Câu gốc / ghi chú</span><input value={rawText} onChange={(event) => setRawText(event.target.value)} /></label><label className={styles.field}><span>Loại quy tắc</span><ConstraintTypeSelect value={type} onChange={setType} /></label><label className={styles.field}><span>Ngày</span><WeekdaySelect value={weekday} onChange={setWeekday} /></label><label className={styles.field}><span>Tiết (vd: 4-6)</span><input value={periods} onChange={(event) => setPeriods(event.target.value)} /></label><button type="button" className={styles.secondaryButton} disabled={busy || !name.trim()} onClick={save}><Check size={16} />Lưu nội dung chỉnh sửa</button></div> : null}
  </article>;
}

function ConstraintTypeSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <select value={value} onChange={(event) => onChange(event.target.value)}><option value="unavailable">Không thể dạy</option><option value="avoid">Muốn tránh</option><option value="available">Ưu tiên dạy</option><option value="busy_event">Bận cố định</option><option value="raw_preference">Cần rà soát</option></select>; }
function WeekdaySelect({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <select value={value} onChange={(event) => onChange(event.target.value)}><option value="">Mọi ngày</option>{[2, 3, 4, 5, 6, 7, 8].map((day) => <option key={day} value={day}>{day === 8 ? "Chủ Nhật" : `Thứ ${day}`}</option>)}</select>; }
function periodLabel(target?: Record<string, unknown>) { const values = (target?.periods ?? target?.period_range ?? []) as number[]; return values.length ? `${Math.min(...values)}-${Math.max(...values)}` : ""; }
function makeTarget(weekday: string, periodText: string, existing?: Record<string, unknown>) { const values = Array.from(new Set((periodText.match(/\d+/g) ?? []).map(Number).filter((item) => item >= 1 && item <= 15))); const periods = values.length === 2 ? Array.from({ length: values[1] - values[0] + 1 }, (_, index) => values[0] + index) : values; return { ...existing, weekday: weekday ? Number(weekday) : null, periods, analysis: { source: "manual" } }; }
const timetableDays = [2, 3, 4, 5, 6, 7, 8];
const timetableBlocks = [
  { label: "Tiết 1–3", periods: [1, 2, 3] },
  { label: "Tiết 4–6", periods: [4, 5, 6] },
  { label: "Tiết 7–9", periods: [7, 8, 9] },
  { label: "Tiết 10–12", periods: [10, 11, 12] },
  { label: "Tiết 13–15", periods: [13, 14, 15] },
];

type PaintedSlot = { slot: string; type: string; draftId: string };
type ConstraintDraft = {
  id: string;
  slots: string[];
  type: string;
  name: string;
  hardness: "hard" | "soft";
  weight: number;
  startDate: string;
  endDate: string;
};

function paintClass(type: string) {
  return type === "unavailable" || type === "busy_event" ? styles.slotUnavailable : type === "available" ? styles.slotAvailable : type === "prefer_period" || type === "avoid" ? styles.slotPreferred : styles.slotOther;
}

function constraintTypeLabel(type: string) {
  return type === "unavailable" ? "Không thể dạy" : type === "busy_event" ? "Bận cố định" : type === "available" ? "Ưu tiên dạy" : type === "avoid" ? "Muốn tránh" : type === "prefer_period" ? "Ưu tiên" : "Ràng buộc khác";
}

function TimetableSlotPicker({ selected, painted, disabled, onEditDraft, onChange }: { selected: string[]; painted: PaintedSlot[]; disabled?: boolean; onEditDraft: (draftId: string) => void; onChange: (slots: string[]) => void }) {
  const paintedBySlot = new Map(painted.map((item) => [item.slot, item]));
  const toggle = (slot: string) => {
    if (selected.includes(slot)) {
      onChange(selected.filter((item) => item !== slot));
      return;
    }
    const existing = paintedBySlot.get(slot);
    if (existing && selected.length === 0) onEditDraft(existing.draftId);
    onChange([...selected, slot]);
  };
  return <div className={styles.slotPicker}>
    <div className={styles.slotPickerHeader}><div><strong>Chọn ô để tạo hoặc sửa ràng buộc</strong><small>{disabled ? "Chọn giảng viên trước khi thao tác trên lịch." : "Bấm một ô đã tô để sửa; chọn nhiều ô để gán cùng một trạng thái."}</small></div><span>{selected.length ? `${selected.length} ô đang chọn` : "Chưa chọn ô"}</span></div>
    <div className={styles.slotLegend} aria-label="Chú giải trạng thái"><span className={styles.legendAvailable}>Ưu tiên dạy</span><span className={styles.legendPreferred}>Muốn tránh</span><span className={styles.legendUnavailable}>Không thể dạy / Bận cố định</span></div>
    <div className={styles.slotGrid}><div className={styles.slotCorner}>BLOCK</div>{timetableDays.map((day) => <div key={day} className={styles.slotDay}>{day === 8 ? "CN" : `T${day}`}</div>)}{timetableBlocks.flatMap((block) => [<div className={styles.slotLabel} key={block.label}>{block.label}</div>, ...timetableDays.map((day) => { const slot = `${day}:${block.periods[0]}-${block.periods.at(-1)}`; const active = selected.includes(slot); const paintedType = paintedBySlot.get(slot)?.type; return <button type="button" key={slot} disabled={disabled} aria-pressed={active} aria-label={`${active ? "Bỏ chọn" : "Chọn"} ${day === 8 ? "Chủ Nhật" : `Thứ ${day}`}, ${block.label}${paintedType ? `, hiện là ${constraintTypeLabel(paintedType)}` : ""}`} className={`${styles.slotCell} ${paintedType ? paintClass(paintedType) : ""} ${active ? styles.slotCellActive : ""}`} onClick={() => toggle(slot)}>{active ? <Check size={15} /> : paintedType ? <span className={styles.slotStateDot} /> : null}</button>; })])}</div>
  </div>;
}

function slotsTarget(selected: string[], startDate = "", endDate = "") {
  return {
    slots: selected.map((slot) => {
      const [day, periodRange] = slot.split(":");
      const [start, end] = periodRange.split("-").map(Number);
      return { weekday: Number(day), periods: Array.from({ length: end - start + 1 }, (_, index) => start + index) };
    }),
    analysis: { source: "visual_timetable" },
    ...(startDate ? { start_date: startDate } : {}),
    ...(endDate ? { end_date: endDate } : {}),
  };
}

function preferenceSlots(item: Constraint): string[] {
  const slots = item.target?.slots;
  if (Array.isArray(slots)) return slots.flatMap((slot) => {
    const value = slot as { weekday?: number; periods?: number[] };
    return timetableBlocks.filter((block) => value.weekday && value.periods?.some((period) => block.periods.includes(period))).map((block) => `${value.weekday}:${block.periods[0]}-${block.periods.at(-1)}`);
  });
  const weekday = item.target?.weekday;
  // Imported preferences use both `periods` and the older `period_range`
  // spelling.  The solver already accepts both; preserve that same view in
  // the calendar so an existing preference does not disappear on hydrate.
  const periods = (item.target?.periods ?? item.target?.period_range ?? []) as number[];
  return typeof weekday === "number" ? timetableBlocks.filter((block) => periods.some((period) => block.periods.includes(period))).map((block) => `${weekday}:${block.periods[0]}-${block.periods.at(-1)}`) : [];
}

function PreferenceComposer({ lecturers, constraints = [], busy, onCreate, onClose }: { lecturers: Lecturer[]; constraints?: Constraint[]; busy: boolean; onCreate: (payload: Record<string, unknown>) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState("Không xếp lịch vào khung giờ này");
  const [lecturerId, setLecturerId] = useState("");
  const [type, setType] = useState("unavailable");
  const [selectedSlots, setSelectedSlots] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<ConstraintDraft[]>([]);
  const [hardness, setHardness] = useState<"hard" | "soft">("soft");
  const [weight, setWeight] = useState(0.8);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const paintedSlots = [
    ...constraints.filter((item) => item.active && item.lecturer_id === Number(lecturerId)).flatMap((item) => preferenceSlots(item).map((slot) => ({ slot, type: item.constraint_type, draftId: `saved-${item.id}` }))),
    ...drafts.flatMap((draft) => draft.slots.map((slot) => ({ slot, type: draft.type, draftId: draft.id }))),
  ];
  const mergeDraft = (current: ConstraintDraft[]) => {
    const remaining = current.map((draft) => ({ ...draft, slots: draft.slots.filter((slot) => !selectedSlots.includes(slot)) })).filter((draft) => draft.slots.length);
    return [...remaining, { id: globalThis.crypto.randomUUID(), slots: selectedSlots, type, name, hardness, weight: hardness === "hard" ? 1 : weight, startDate, endDate }];
  };
  const recordRegion = () => {
    if (!lecturerId || !selectedSlots.length) return;
    setDrafts(mergeDraft);
    setSelectedSlots([]);
  };
  const editDraft = (draftId: string) => {
    const draft = drafts.find((item) => item.id === draftId);
    if (!draft) return;
    setType(draft.type);
    setName(draft.name);
    setHardness(draft.hardness);
    setWeight(draft.weight);
    setStartDate(draft.startDate);
    setEndDate(draft.endDate);
  };
  const finishPainting = async () => {
    const finalDrafts = selectedSlots.length ? mergeDraft(drafts) : drafts;
    for (const draft of finalDrafts) {
      await onCreate({ name: draft.name, lecturer_id: Number(lecturerId), constraint_type: draft.type, hardness: draft.hardness, weight: draft.weight, target: slotsTarget(draft.slots, draft.startDate, draft.endDate), raw_text: "Ràng buộc do trưởng bộ môn chỉnh trực tiếp trên thời khoá biểu", confirmed: true });
    }
    onClose();
  };
  return <div className={styles.composer}>
    <div><span className={styles.eyebrow}>RÀNG BUỘC THỦ CÔNG</span><strong>Biên tập trực tiếp trên lịch của từng giảng viên</strong></div>
    <div className={styles.composerGrid}><label className={styles.field}><span>Giảng viên áp dụng</span><select value={lecturerId} onChange={(event) => { setLecturerId(event.target.value); setSelectedSlots([]); setDrafts([]); }}><option value="">Chọn giảng viên…</option>{lecturers.map((lecturer) => <option key={lecturer.id} value={lecturer.id}>{lecturer.name}</option>)}</select></label><label className={styles.field}><span>Tên ràng buộc</span><input value={name} onChange={(event) => setName(event.target.value)} /></label></div>
    <TimetableSlotPicker selected={selectedSlots} painted={paintedSlots} disabled={!lecturerId} onEditDraft={editDraft} onChange={setSelectedSlots} />
    <div className={`${styles.cellEditor} ${selectedSlots.length ? styles.cellEditorActive : ""}`}>
      <div><span className={styles.eyebrow}>THUỘC TÍNH Ô ĐANG CHỌN</span><strong>{selectedSlots.length ? `${selectedSlots.length} ô sẽ áp dụng cùng trạng thái` : "Chọn một hoặc nhiều ô trên lịch"}</strong></div>
      <div className={styles.constraintChoices} role="group" aria-label="Gán trạng thái cho ô đã chọn">
        {[{ value: "unavailable", label: "Không thể dạy" }, { value: "avoid", label: "Muốn tránh" }, { value: "available", label: "Ưu tiên dạy" }, { value: "busy_event", label: "Bận cố định" }].map((choice) => <button type="button" key={choice.value} disabled={!selectedSlots.length} aria-pressed={type === choice.value} className={`${styles.constraintChoice} ${paintClass(choice.value)} ${type === choice.value ? styles.constraintChoiceActive : ""}`} onClick={() => { setType(choice.value); setHardness(["unavailable", "busy_event"].includes(choice.value) ? "hard" : "soft"); }}>{choice.label}</button>)}
      </div>
      <div className={styles.composerGrid}><label className={styles.field}><span>Từ ngày (tùy chọn)</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label className={styles.field}><span>Đến ngày (tùy chọn)</span><input type="date" min={startDate} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>
      <div className={styles.cellEditorSettings}><label className={styles.field}><span>Mức độ</span><select disabled={!selectedSlots.length} value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}><option value="soft">Ưu tiên mềm</option><option value="hard">Bắt buộc</option></select></label><label className={styles.switchLabel}><span>Trọng số {hardness === "hard" ? "1.0" : weight.toFixed(1)}</span><input type="range" min="0" max="1" step="0.1" disabled={!selectedSlots.length || hardness === "hard"} value={hardness === "hard" ? 1 : weight} onChange={(event) => setWeight(Number(event.target.value))} /></label><button type="button" className={styles.secondaryButton} disabled={!selectedSlots.length} onClick={() => setSelectedSlots([])}>Bỏ chọn</button><button type="button" className={styles.primaryButton} disabled={!name.trim() || !lecturerId || !selectedSlots.length} onClick={recordRegion}><Check size={16} />Ghi vào lịch</button></div>
    </div>
    <div className={styles.composerFooter}><span className={styles.currentPaintType}>{drafts.length ? <><strong>{drafts.length}</strong> vùng đã ghi tạm</> : "Chưa có vùng nào được ghi"}</span><div><button type="button" className={styles.ghostButton} onClick={onClose}>Hủy</button><button type="button" className={styles.primaryButton} disabled={!lecturerId || (!selectedSlots.length && !drafts.length) || busy} onClick={() => void finishPainting()}>{busy ? <LoaderCircle size={16} className={styles.spin} /> : <Check size={16} />}Chốt tất cả</button></div></div>
    <small className={styles.paintHint}>Các vùng chỉ được gửi vào bộ tối ưu khi bấm “Chốt tất cả”. Trước đó, bấm lại ô đã tô để sửa trạng thái ngay trong bảng.</small>
  </div>;
}

function WorkloadConstraintComposer({ lecturers, busy, onCreate }: { lecturers: Lecturer[]; busy: boolean; onCreate: (payload: Record<string, unknown>) => void }) {
  const [lecturerId, setLecturerId] = useState(""); const [rule, setRule] = useState("MAX_CLASSES"); const [limit, setLimit] = useState(4); const [hardness, setHardness] = useState<"hard" | "soft">("hard"); const [weight, setWeight] = useState(0.8);
  const min = rule === "MIN_CLASSES";
  return <div className={styles.flatPanel}><span className={styles.eyebrow}>WORKLOAD CONSTRAINT</span><strong>Giới hạn tải là rule chuẩn, tách biệt với nguyện vọng theo lịch.</strong><div className={styles.composerGrid}><label className={styles.field}><span>Giảng viên</span><select value={lecturerId} onChange={(event) => setLecturerId(event.target.value)}><option value="">Chọn giảng viên…</option>{lecturers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className={styles.field}><span>Rule</span><select value={rule} onChange={(event) => setRule(event.target.value)}><option value="MIN_CLASSES">Min TeachingGroups</option><option value="MAX_CLASSES">Max TeachingGroups</option><option value="MAX_SESSIONS_PER_DAY">Max sessions/day</option><option value="MAX_DAYS_PER_WEEK">Max days/week</option><option value="MAX_CONSECUTIVE_BLOCKS">Avoid consecutive blocks</option></select></label><label className={styles.field}><span>Giới hạn</span><input type="number" min="1" value={limit} onChange={(event) => setLimit(Number(event.target.value))} /></label></div><div className={styles.inlineFields}><label className={styles.field}><span>Loại</span><select value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}><option value="hard">HARD — không được phép vi phạm</option><option value="soft">SOFT — có thể vi phạm nếu cần</option></select></label><label className={styles.field}><span>Weight (SOFT)</span><input type="number" min="0" max="1" step="0.1" disabled={hardness === "hard"} value={Number.isNaN(weight) ? "" : weight} onChange={(event) => setWeight(event.target.value === "" ? NaN : Number(event.target.value))} /></label></div><button type="button" className={styles.secondaryButton} disabled={!lecturerId || limit < 1 || busy} onClick={() => onCreate({ name: `${rule} · ${limit}`, lecturer_id: Number(lecturerId), constraint_type: rule, hardness, weight: hardness === "soft" ? weight : 0, target: min ? { min: limit } : { max: limit }, confirmed: true })}>Thêm workload rule</button></div>;
}

function CourseAssignmentConstraintComposer({ lecturers, classes, busy, onCreate }: { lecturers: Lecturer[]; classes: ClassItem[]; busy: boolean; onCreate: (payload: Record<string, unknown>) => void }) {
  const [lecturerId, setLecturerId] = useState(""); const [courseId, setCourseId] = useState(""); const courses = Array.from(new Map(classes.map((item) => [item.course_code, item])).values());
  return <div className={styles.flatPanel}><span className={styles.eyebrow}>COURSE ASSIGNMENT RULE</span><strong>Không cho một giảng viên dạy toàn bộ các TeachingGroup của một môn.</strong><div className={styles.composerGrid}><label className={styles.field}><span>Giảng viên</span><select value={lecturerId} onChange={(event) => setLecturerId(event.target.value)}><option value="">Chọn giảng viên…</option>{lecturers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className={styles.field}><span>Môn học</span><select value={courseId} onChange={(event) => setCourseId(event.target.value)}><option value="">Chọn môn…</option>{courses.map((item) => <option key={item.course_code} value={item.course_code}>{item.course_code} · {item.course_name}</option>)}</select></label></div><button type="button" className={styles.secondaryButton} disabled={!lecturerId || !courseId || busy} onClick={() => { const course = courses.find((item) => item.course_code === courseId); if (course) onCreate({ name: `Không phân ${course.course_code}`, lecturer_id: Number(lecturerId), constraint_type: "FORBIDDEN_ASSIGNMENT", hardness: "hard", weight: 0, target: { course_id: course.id }, confirmed: true }); }}>Không được dạy môn này</button></div>;
}

type WorkspaceTab = "overview" | "unassigned" | "readiness" | "workload" | "assignments" | "calendar" | "constraints" | "seminars" | "merges" | "problems" | "runs" | "export";

const workspaceItems: Array<{ id: WorkspaceTab; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Tổng quan", icon: LayoutDashboard },
  { id: "unassigned", label: "Chưa phân công", icon: AlertTriangle },
  { id: "readiness", label: "Sẵn sàng", icon: ShieldCheck },
  { id: "workload", label: "Tải giảng dạy", icon: Users },
  { id: "assignments", label: "Phân công", icon: Users },
  { id: "calendar", label: "Lịch", icon: CalendarRange },
  { id: "constraints", label: "Ràng buộc", icon: Settings2 },
  { id: "seminars", label: "Seminar", icon: CalendarRange },
  { id: "merges", label: "Lớp ghép", icon: Columns3 },
  { id: "problems", label: "Vấn đề", icon: AlertCircle },
  { id: "runs", label: "Phiên bản", icon: RefreshCw },
  { id: "export", label: "Xuất file", icon: Download },
];

function statusFor(item: ClassItem) {
  if (item.locked_assignment) return "Locked";
  if (item.assignment_source === "MANUAL") return "Manual";
  return item.lecturer ? "Assigned" : "Unassigned";
}

function UnassignedWorkflowPanel({
  classes,
  items,
  loading,
  onInspectClass,
  onSwitchTab,
  onRefresh,
  onUpdateStatus,
}: {
  classes: ClassItem[];
  items: UnassignedDiagnosticItem[];
  loading: boolean;
  onInspectClass: (item: ClassItem) => void;
  onSwitchTab: (tab: WorkspaceTab) => void;
  onRefresh: () => void;
  onUpdateStatus: (classId: number, status: string, notes?: string) => Promise<void>;
}) {
  const [filterCause, setFilterCause] = useState<string>("ALL");
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [search, setSearch] = useState<string>("");

  const filtered = items.filter((item) => {
    if (filterCause !== "ALL" && item.root_cause !== filterCause) return false;
    if (filterStatus !== "ALL" && item.resolution_status !== filterStatus) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const match =
        item.class_code.toLowerCase().includes(q) ||
        item.course_name.toLowerCase().includes(q) ||
        item.course_code.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });

  const bottlenecks = useMemo(() => {
    const list: NonNullable<UnassignedDiagnosticItem["bottleneck_details"]>[] = [];
    const seen = new Set<string>();
    items.forEach((item) => {
      if (item.bottleneck_details) {
        const key = `${item.bottleneck_details.weekday}-${item.bottleneck_details.period_range}`;
        if (!seen.has(key)) {
          seen.add(key);
          list.push(item.bottleneck_details);
        }
      }
    });
    return list;
  }, [items]);

  const rootCauseBadgeClass = (severity: string) => {
    if (severity === "critical") return styles.badgeCritical;
    if (severity === "warning") return styles.badgeWarning;
    return styles.badgeInfo;
  };

  return (
    <div className={styles.unassignedShell}>
      <div className={styles.unassignedFilterBar}>
        <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <Search size={15} color="var(--color-text-muted)" />
            <input
              type="text"
              placeholder="Tìm theo mã lớp, môn..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                padding: "5px 9px",
                fontSize: "0.78rem",
                borderRadius: "6px",
                border: "1px solid var(--color-border)",
                width: "180px",
              }}
            />
          </div>

          <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.78rem" }}>
            <span>Nguyên nhân:</span>
            <select
              value={filterCause}
              onChange={(e) => setFilterCause(e.target.value)}
              style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: "6px", border: "1px solid var(--color-border)" }}
            >
              <option value="ALL">Tất cả nguyên nhân</option>
              <option value="HARD_AVAILABILITY_CONFLICT">Bận cứng theo nguyện vọng</option>
              <option value="TIMETABLE_COLLISION">Trùng lịch với lớp khác</option>
              <option value="GLOBAL_INFEASIBILITY">Thiếu nguồn lực tiết học (Bottleneck)</option>
              <option value="WORKLOAD_HARD_LIMIT">Đụng trần tải giảng dạy</option>
              <option value="LOCKED_CONFLICT">Xung đột phân công đã khóa</option>
              <option value="NO_CAPABILITY">Chưa có giảng viên đủ năng lực</option>
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.78rem" }}>
            <span>Trạng thái:</span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: "6px", border: "1px solid var(--color-border)" }}
            >
              <option value="ALL">Tất cả trạng thái</option>
              <option value="NEW">Mới (Chưa xử lý)</option>
              <option value="UNDER_REVIEW">Đang xem xét</option>
              <option value="WAITING_FOR_DATA">Chờ dữ liệu</option>
              <option value="MANUALLY_RESOLVED">Đã xử lý thủ công</option>
              <option value="ACCEPTED_UNRESOLVED">Chấp nhận chưa phân</option>
            </select>
          </label>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button type="button" className={styles.btnSm} onClick={onRefresh} title="Tải lại danh sách">
            <RefreshCw size={14} className={loading ? styles.spin : ""} /> Làm mới
          </button>
          <span style={{ fontSize: "0.78rem", color: "var(--color-text-muted)", fontWeight: 600 }}>
            {filtered.length} / {items.length} lớp
          </span>
        </div>
      </div>

      {bottlenecks.map((b, i) => (
        <div key={i} className={styles.hitlLockCallout} style={{ background: "#fffbeb", borderColor: "#fde68a", color: "#92400e" }}>
          <strong style={{ color: "#b45309" }}>
            <AlertTriangle size={16} /> Nút thắt tài nguyên: Thứ {b.weekday}, tiết {b.period_range}
          </strong>
          <p>
            Có {b.overlapping_classes_count} lớp diễn ra đồng thời nhưng chỉ có {b.available_lecturers_count} giảng viên có capability môn học và không bận cứng.
            Thiếu hụt thực tế: {b.shortage} giảng viên. Đề xuất: Đổi lịch lớp hoặc mở rộng capability giảng viên.
          </p>
        </div>
      ))}

      <div className={styles.unassignedTableWrap}>
        <table className={styles.unassignedTable}>
          <thead>
            <tr>
              <th>Mã lớp</th>
              <th>Môn học</th>
              <th>Lịch học</th>
              <th>Nguyên nhân chính</th>
              <th>Ứng viên</th>
              <th>Trạng thái xử lý</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => {
              const classObj = classes.find((c) => c.id === item.class_id);
              return (
                <tr key={item.class_id}>
                  <td>
                    <strong>{item.class_code}</strong>
                  </td>
                  <td>
                    <div>
                      <strong>{item.course_name}</strong>
                      <small style={{ display: "block", color: "var(--color-text-muted)" }}>{item.course_code} · {item.credits} TC</small>
                    </div>
                  </td>
                  <td>
                    <span style={{ fontSize: "0.78rem" }}>{item.schedule_summary}</span>
                  </td>
                  <td>
                    <span className={`${styles.rootCauseBadge} ${rootCauseBadgeClass(item.root_cause_severity)}`}>
                      <AlertCircle size={13} /> {item.root_cause_label}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, color: item.eligible_candidates_count > 0 ? "#16a34a" : "#dc2626" }}>
                      {item.eligible_candidates_count} / {item.total_candidates_count} GV
                    </span>
                  </td>
                  <td>
                    <select
                      value={item.resolution_status}
                      onChange={(e) => void onUpdateStatus(item.class_id, e.target.value)}
                      style={{
                        padding: "3px 7px",
                        fontSize: "0.74rem",
                        borderRadius: "5px",
                        border: "1px solid var(--color-border)",
                        background: "var(--color-surface)",
                      }}
                    >
                      <option value="NEW">Mới</option>
                      <option value="UNDER_REVIEW">Đang xem xét</option>
                      <option value="WAITING_FOR_DATA">Chờ dữ liệu</option>
                      <option value="MANUALLY_RESOLVED">Đã xử lý thủ công</option>
                      <option value="ACCEPTED_UNRESOLVED">Chấp nhận chưa phân</option>
                    </select>
                  </td>
                  <td>
                    <div className={styles.actionBtnGroup}>
                      <button
                        type="button"
                        className={`${styles.btnSm} ${styles.btnSmPrimary}`}
                        onClick={() => classObj && onInspectClass(classObj)}
                        title="Xem chi tiết 20 giảng viên và phân công"
                      >
                        <Users size={13} /> Phân công
                      </button>
                      <button
                        type="button"
                        className={styles.btnSm}
                        onClick={() => onSwitchTab("calendar")}
                        title="Xem khung giờ trên lịch tuần"
                      >
                        <CalendarRange size={13} /> Lịch
                      </button>
                      <button
                        type="button"
                        className={styles.btnSm}
                        onClick={() => onSwitchTab("constraints")}
                        title="Xem danh sách ràng buộc / nguyện vọng"
                      >
                        <Settings2 size={13} /> Nguyện vọng
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!filtered.length && !loading ? (
          <div className={styles.emptyPanel} style={{ padding: "30px" }}>
            <CheckCircle2 size={24} color="#16a34a" />
            <strong>Không có lớp nào phù hợp bộ lọc</strong>
            <span>Hãy thay đổi điều kiện lọc hoặc từ khóa tìm kiếm.</span>
          </div>
        ) : null}
        {loading ? (
          <div className={styles.candidateLoading} style={{ padding: "30px", justifyContent: "center" }}>
            <LoaderCircle size={18} className={styles.spin} /> Đang phân tích chẩn đoán TeachingGroups...
          </div>
        ) : null}
      </div>
    </div>
  );
}

function SchedulingWorkspace({
  metrics,
  classes,
  constraints,
  lecturers,
  issues,
  problems,
  semesterId,
  busy,
  onRun,
  onCreate,
  onUpdateConstraint,
  onDeleteConstraint,
  onManual,
  onOverrideLock,
  onUnlock,
  onNext,
  onSwitchView,
}: {
  metrics: DashboardMetrics;
  classes: ClassItem[];
  constraints: Constraint[];
  lecturers: Lecturer[];
  issues: ValidationIssue[];
  problems: Problem[];
  semesterId: number | null;
  busy: string | null;
  onRun: () => void;
  onCreate: (payload: Record<string, unknown>) => void;
  onUpdateConstraint: (item: Constraint, payload: Partial<Constraint>) => void;
  onDeleteConstraint: (item: Constraint) => void;
  onManual: (classId: number, lecturerId: number, lock: boolean, allowOverride?: boolean, overrideReason?: string) => void;
  onOverrideLock?: (classId: number, lecturerId: number, reason: string, lock: boolean) => void;
  onUnlock: (classId: number) => void;
  onNext: () => void;
  onSwitchView?: (view: View) => void;
}) {
  void issues;
  void onSwitchView;
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [selectedClass, setSelectedClass] = useState<ClassItem | null>(null);
  const [selectedLecturerId, setSelectedLecturerId] = useState<number | null>(null);
  const [candidateAnalysisRows, setCandidateAnalysisRows] = useState<CandidateAnalysisItem[]>([]);
  const [candidateAnalysisLoading, setCandidateAnalysisLoading] = useState(false);
  const [problemFilter, setProblemFilter] = useState<"all" | "critical" | "warning" | "info">("all");
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [workload, setWorkload] = useState<Workload[]>([]);
  const [merges, setMerges] = useState<MergeCandidate[]>([]);
  const [seminars, setSeminars] = useState<Seminar[]>([]);
  const [runDiff, setRunDiff] = useState<RunDiff | null>(null);

  // Unassigned diagnostics state
  const [unassignedItems, setUnassignedItems] = useState<UnassignedDiagnosticItem[]>([]);
  const [unassignedLoading, setUnassignedLoading] = useState(false);

  // Human-in-the-Loop Lock Override Modal state
  const [overrideModal, setOverrideModal] = useState<{
    isOpen: boolean;
    classItem: ClassItem;
    lecturerId: number;
    lecturerName: string;
    collisionDetails?: string;
    reason: string;
    confirmedCheckbox: boolean;
  } | null>(null);

  // Privileged Final Export Modal state
  const [privilegedExportModal, setPrivilegedExportModal] = useState<{
    isOpen: boolean;
    reason: string;
    confirmedCheckbox: boolean;
  } | null>(null);

  const assigned = classes.filter((item) => Boolean(item.lecturer)).length;
  const hardProblems = problems.filter((item) => item.severity === "critical").length;
  const finalReady = metrics.unassigned_classes === 0 && hardProblems === 0 && ["optimal", "feasible"].includes(metrics.optimization_status);

  const refreshUnassigned = useCallback(() => {
    if (!semesterId) return;
    setUnassignedLoading(true);
    api.unassignedClasses(semesterId)
      .then(setUnassignedItems)
      .catch(() => setUnassignedItems([]))
      .finally(() => setUnassignedLoading(false));
  }, [semesterId]);

  useEffect(() => {
    refreshUnassigned();
  }, [refreshUnassigned, classes, metrics.unassigned_classes]);

  useEffect(() => {
    if (!selectedClass || !semesterId) {
      setCandidateAnalysisRows([]);
      return;
    }
    setCandidateAnalysisLoading(true);
    void api.candidateAnalysis(selectedClass.id, semesterId).then(setCandidateAnalysisRows).catch(() => setCandidateAnalysisRows([])).finally(() => setCandidateAnalysisLoading(false));
  }, [selectedClass, semesterId]);

  useEffect(() => {
    setSelectedClass((current) => current ? classes.find((item) => item.id === current.id) ?? null : null);
  }, [classes]);

  useEffect(() => {
    if (!semesterId) return;
    void Promise.all([api.readiness(semesterId), api.workload(semesterId), api.mergeCandidates(semesterId), api.seminars(semesterId), api.runs(semesterId)])
      .then(([nextReadiness, nextWorkload, nextMerges, nextSeminars, runs]) => {
        setReadiness(nextReadiness); setWorkload(nextWorkload); setMerges(nextMerges); setSeminars(nextSeminars);
        const latest = runs[0];
        if (latest) void api.runDiff(latest.id, semesterId).then(setRunDiff).catch(() => setRunDiff(null));
      }).catch(() => undefined);
  }, [semesterId, classes, constraints, metrics.optimization_status]);

  const inspectClass = (item: ClassItem) => { setSelectedClass(item); setSelectedLecturerId(null); };
  const filteredProblems = problems.filter((item) => problemFilter === "all" || item.severity === problemFilter);
  const decideMerge = (candidate: MergeCandidate, confirmed: boolean) => {
    if (!semesterId || candidate.kind !== "FULL") return;
    void api.decideMerge(candidate.id, confirmed, semesterId).then(() => setMerges((current) => current.map((item) => item.id === candidate.id ? { ...item, status: confirmed ? "confirmed" : "rejected" } : item)));
  };

  const handleUpdateStatus = async (classId: number, status: string, notes?: string) => {
    if (!semesterId) return;
    try {
      await api.updateResolutionStatus(classId, status, notes ?? null, semesterId);
      refreshUnassigned();
    } catch {
      // Ignored
    }
  };

  return <section className={styles.schedulingShell}>
    <header className={styles.workspaceHeading}>
      <div><span className={styles.eyebrow}>BƯỚC 05 · WORKSPACE</span><h2>Phân công giảng dạy</h2><p>Rà soát dữ liệu, chỉnh phân công và xử lý vấn đề trên một không gian làm việc.</p></div>
      <button type="button" className={styles.primaryButton} disabled={busy === "optimize" || !classes.length} onClick={onRun}>{busy === "optimize" ? <LoaderCircle size={17} className={styles.spin} /> : <Play size={17} />}Chạy lại phân công</button>
    </header>
    <div className={styles.workspaceLayout}>
      <nav className={styles.workspaceNav} aria-label="Không gian phân công">
        {workspaceItems.filter((item) => item.id !== "runs" || metrics.optimization_status !== "not_run").map((item) => {
          const Icon = item.icon;
          return (
            <button type="button" key={item.id} className={tab === item.id ? styles.workspaceNavActive : ""} onClick={() => setTab(item.id)}>
              <Icon size={17} />
              {item.label}
              {item.id === "unassigned" && metrics.unassigned_classes > 0 ? (
                <small style={{ background: "#ef4444", color: "#fff" }}>{metrics.unassigned_classes}</small>
              ) : null}
              {item.id === "problems" && problems.length ? <small>{problems.length}</small> : null}
            </button>
          );
        })}
      </nav>
      <div className={styles.workspaceCenter}>
        {tab === "overview" ? <>
          <div className={styles.metricGrid}>
            <Metric label="TeachingGroups" value={String(metrics.classes)} detail="Tổng số lớp học phần" tone="blue" />
            <Metric label="Đã phân" value={String(assigned)} detail="Theo dữ liệu hiện tại" tone="green" />
            <Metric label="Chưa phân" value={String(metrics.unassigned_classes)} detail="Cần solver hoặc xử lý" tone="violet" />
            <Metric label="Đã khóa" value={String(metrics.locked_classes)} detail="Solver không thay đổi" tone="blue" />
            <Metric label="Hard problems" value={String(hardProblems)} detail="Cần trưởng bộ môn xử lý" tone={hardProblems ? "red" : "green"} />
          </div>

          {metrics.unassigned_classes > 0 ? (
            <div className={styles.unassignedActionCard}>
              <div>
                <strong>Cần xử lý {metrics.unassigned_classes} TeachingGroup chưa được phân công</strong>
                <p>Solver đã hoàn tất nhưng còn các lớp vướng xung đột bận cứng, trùng lịch hoặc thiếu nguồn lực tiết học.</p>
                <div className={styles.unassignedBreakdownPills}>
                  {metrics.unassigned_breakdown?.hard_availability ? (
                    <span className={styles.unassignedBreakdownPill}>Bận cứng: {metrics.unassigned_breakdown.hard_availability}</span>
                  ) : null}
                  {metrics.unassigned_breakdown?.global_infeasibility ? (
                    <span className={styles.unassignedBreakdownPill}>Nguồn lực ca học: {metrics.unassigned_breakdown.global_infeasibility}</span>
                  ) : null}
                  {metrics.unassigned_breakdown?.timetable_collision ? (
                    <span className={styles.unassignedBreakdownPill}>Trùng lịch: {metrics.unassigned_breakdown.timetable_collision}</span>
                  ) : null}
                  {metrics.unassigned_breakdown?.workload_limit ? (
                    <span className={styles.unassignedBreakdownPill}>Quá tải: {metrics.unassigned_breakdown.workload_limit}</span>
                  ) : null}
                  {metrics.unassigned_breakdown?.no_capability ? (
                    <span className={styles.unassignedBreakdownPill}>Không có capability: {metrics.unassigned_breakdown.no_capability}</span>
                  ) : null}
                </div>
              </div>
              <button type="button" className={styles.primaryButton} onClick={() => setTab("unassigned")}>
                Xử lý ngay ({metrics.unassigned_classes}) <ArrowRight size={16} />
              </button>
            </div>
          ) : null}

          {runDiff ? (
            <div className={styles.reSolveDiffBanner}>
              <div>
                <strong>Kết quả chạy lại solver:</strong> Đã phân {runDiff.assigned} lớp · Chưa phân: {runDiff.unassigned} lớp · Đã thay đổi: {runDiff.changed_assignments} phân công.
              </div>
              {runDiff.unassigned > 0 ? (
                <button type="button" className={styles.btnSm} onClick={() => setTab("unassigned")}>
                  Xem lớp chưa phân
                </button>
              ) : null}
            </div>
          ) : null}

          <div className={styles.readinessPanel}><div><span className={styles.eyebrow}>READINESS</span><strong>Draft: sẵn sàng · Final: {finalReady ? "sẵn sàng" : "chưa sẵn sàng"}</strong><p>{finalReady ? "Có thể xuất file Final." : `Cần xử lý ${hardProblems} vấn đề nghiêm trọng và ${metrics.unassigned_classes} TeachingGroup chưa phân trước khi xuất Final.`}</p></div><button type="button" className={styles.secondaryButton} onClick={() => setTab("export")}>Xem điều kiện xuất<ArrowRight size={16} /></button></div>
          <div className={styles.overviewSplit}><div className={styles.flatPanel}><div className={styles.panelHeader}><div><span>PHIÊN GẦN NHẤT</span><strong>{metrics.optimization_status === "not_run" ? "Chưa chạy solver" : metrics.optimization_status}</strong></div><ShieldCheck size={19} /></div><p>{metrics.optimization_status === "blocked" ? "Không thể tạo phương án mới vì có xung đột giữa các phân công đã khóa." : "Mỗi lần chạy tạo một snapshot độc lập; các phân công đã khóa được giữ nguyên."}</p></div><div className={styles.flatPanel}><div className={styles.panelHeader}><div><span>VẤN ĐỀ</span><strong>{problems.length} mục cần theo dõi</strong></div><ListChecks size={19} /></div>{problems.slice(0, 2).map((item) => <button type="button" key={`${item.code}-${item.entity_id}`} className={styles.problemPreview} onClick={() => { setTab("problems"); if (item.entity_type === "class_section") { const found = classes.find((row) => row.id === Number(item.entity_id)); if (found) inspectClass(found); } }}><AlertCircle size={16} /><span>{item.message}</span></button>)}</div></div>
        </> : null}
        {tab === "unassigned" ? (
          <UnassignedWorkflowPanel
            classes={classes}
            items={unassignedItems}
            loading={unassignedLoading}
            onInspectClass={inspectClass}
            onSwitchTab={setTab}
            onRefresh={refreshUnassigned}
            onUpdateStatus={handleUpdateStatus}
          />
        ) : null}
        {tab === "readiness" ? <ReadinessPanel readiness={readiness} lecturers={lecturers} issues={issues} semesterId={semesterId} onProblems={() => setTab("problems")} onResolved={async () => { if (semesterId) setReadiness(await api.readiness(semesterId)); }} /> : null}
        {tab === "workload" ? <WorkloadPanel workload={workload} /> : null}
        {tab === "assignments" ? <div className={styles.assignmentTableWrap}><div className={styles.tableToolbar}><div><strong>Danh sách TeachingGroup</strong><small>Bấm một dòng để xem candidate và chỉnh phân công.</small></div><span>{classes.length} lớp</span></div><table className={styles.assignmentTable}><thead><tr><th>Mã lớp</th><th>Môn</th><th>Lịch</th><th>Giảng viên</th><th>Source</th><th>Lock</th><th>Status</th></tr></thead><tbody>{classes.map((item) => <tr key={item.id} className={selectedClass?.id === item.id ? styles.selectedRow : ""} onClick={() => inspectClass(item)}><td>{item.class_code}</td><td><strong>{item.course_name}</strong><small>{item.course_code}</small></td><td>{item.sessions.map((session) => `T${session.weekday} · ${session.start_period}–${session.end_period}`).join(" · ")}</td><td>{item.lecturer ?? "—"}</td><td>{item.assignment_source ?? (item.lecturer ? "IMPORT" : "—")}</td><td>{item.locked_assignment ? <Lock size={16} aria-label="Đã khóa" /> : "—"}</td><td><span className={`${styles.statusPill} ${styles[`status${statusFor(item)}`]}`}>{statusFor(item)}</span></td></tr>)}</tbody></table>{!classes.length ? <div className={styles.emptyPanel}><Users size={24} /><strong>Chưa có TeachingGroup</strong><span>Hãy hoàn tất bước nhập dữ liệu trước.</span></div> : null}</div> : null}
        {tab === "calendar" ? <AppleCalendarView classes={classes} lecturers={lecturers} constraints={constraints} seminars={seminars} selectedLecturerId={selectedLecturerId} onSelectLecturerId={setSelectedLecturerId} onInspectClass={inspectClass} /> : null}
        {tab === "constraints" ? <><div className={styles.workspaceSectionTitle}><div><span>RÀNG BUỘC</span><h3>Lịch nguyện vọng giảng viên</h3></div><span>{constraints.length} quy tắc</span></div><PreferenceComposer lecturers={lecturers} constraints={constraints} busy={busy === "new-constraint"} onCreate={async (payload) => onCreate(payload)} onClose={() => undefined} /><WorkloadConstraintComposer lecturers={lecturers} busy={busy === "new-constraint"} onCreate={onCreate} /><CourseAssignmentConstraintComposer lecturers={lecturers} classes={classes} busy={busy === "new-constraint"} onCreate={onCreate} />{constraints.map((item) => <PreferenceRow key={item.id} item={item} lecturers={lecturers} busy={busy === `constraint-${item.id}`} onSave={onUpdateConstraint} onDelete={onDeleteConstraint} />)}</> : null}
        {tab === "seminars" ? <SeminarPanel lecturers={lecturers} seminars={seminars} semesterId={semesterId} /> : null}
        {tab === "merges" ? <MergePanel candidates={merges} onDecide={decideMerge} /> : null}
        {tab === "problems" ? <div className={styles.problemLog}><div className={styles.tableToolbar}><div><strong>Problem Log</strong><small>Thông báo từ backend; không suy diễn thêm ở giao diện.</small></div><div className={styles.problemFilters}>{(["all", "critical", "warning", "info"] as const).map((filter) => <button type="button" key={filter} aria-pressed={problemFilter === filter} onClick={() => setProblemFilter(filter)}>{filter === "all" ? "Tất cả" : filter}</button>)}</div></div>{filteredProblems.length ? filteredProblems.map((item) => <article className={`${styles.problemRow} ${styles[`problem${item.severity}`]}`} key={`${item.code}-${item.entity_type}-${item.entity_id}`}><AlertCircle size={18} /><div><strong>{item.code.replaceAll("_", " ")}</strong><p>{item.message}</p>{item.reasons.length ? <small>{item.reasons.map((reason) => String(reason.reason ?? "")).filter(Boolean).join(" · ")}</small> : null}{item.reasons.flatMap((reason) => Array.isArray(reason.class_ids) ? reason.class_ids : []).map((classId) => <button type="button" className={styles.textButton} key={String(classId)} onClick={() => { const found = classes.find((row) => row.id === Number(classId)); if (found) { inspectClass(found); setTab("assignments"); } }}>Mở lớp {classes.find((row) => row.id === Number(classId))?.class_code ?? classId}<ArrowRight size={14} /></button>)}</div>{item.entity_type === "class_section" ? <button type="button" className={styles.textButton} onClick={() => { const found = classes.find((row) => row.id === Number(item.entity_id)); if (found) { inspectClass(found); setTab("assignments"); } }}>Xem lớp<ArrowRight size={15} /></button> : null}</article>) : <div className={styles.emptyPanel}><CheckCircle2 size={24} /><strong>Không có vấn đề cần xử lý</strong><span>Backend chưa ghi nhận diagnostic cho kỳ học này.</span></div>}</div> : null}
        {tab === "runs" ? <RunDiffPanel status={metrics.optimization_status} diff={runDiff} /> : null}
        {tab === "export" ? <ExportReadiness metrics={metrics} problems={problems} semesterId={semesterId ?? undefined} finalReady={finalReady} onOpenPrivileged={() => setPrivilegedExportModal({ isOpen: true, reason: "", confirmedCheckbox: false })} /> : null}
      </div>
      {selectedClass ? (
        <aside className={styles.inspector} aria-label="Chi tiết TeachingGroup">
          <div className={styles.inspectorHeader}>
            <div>
              <span>TEACHINGGROUP</span>
              <strong>{selectedClass.class_code}</strong>
              <small>{selectedClass.course_name}</small>
            </div>
            <button type="button" className={styles.editIcon} onClick={() => setSelectedClass(null)} aria-label="Đóng inspector">
              <X size={16} />
            </button>
          </div>

          <div className={styles.inspectorCurrent}>
            <span>Giảng viên hiện tại</span>
            <strong>{selectedClass.lecturer ?? "Chưa phân công"}</strong>
            {selectedClass.locked_assignment ? (
              <span className={styles.lockedLabel}><Lock size={14} />Đã khóa</span>
            ) : null}
          </div>

          {selectedClass.locked_assignment ? (
            <button type="button" className={styles.secondaryButton} disabled={busy === `unlock-${selectedClass.id}`} onClick={() => onUnlock(selectedClass.id)}>
              Mở khóa
            </button>
          ) : null}

          {(() => {
            const diag = unassignedItems.find((u) => u.class_id === selectedClass.id);
            if (!diag) return null;
            return (
              <div className={styles.drawerSubHeader}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className={styles.eyebrow}>CHẨN ĐOÁN GỐC</span>
                  <span className={`${styles.rootCauseBadge} ${diag.root_cause_severity === "critical" ? styles.badgeCritical : styles.badgeWarning}`}>
                    {diag.root_cause_label}
                  </span>
                </div>
                <small>{diag.recommended_actions?.[0]?.description ?? "Cần rà soát năng lực và lịch của các giảng viên."}</small>
              </div>
            );
          })()}

          <div className={styles.candidateList}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: "4px" }}>
              <span>Ma trận 20 giảng viên</span>
              <small style={{ color: "var(--color-text-muted)", fontSize: "0.72rem" }}>
                {candidateAnalysisRows.filter((r) => r.is_eligible).length} khả dĩ
              </small>
            </div>

            {candidateAnalysisLoading ? (
              <div className={styles.candidateLoading}>
                <LoaderCircle size={16} className={styles.spin} /> Đang phân tích năng lực & lịch 20 giảng viên…
              </div>
            ) : (
              candidateAnalysisRows.map((candidate) => {
                const chosen = candidate.is_currently_assigned ?? (selectedClass.lecturer_id === candidate.lecturer_id);
                const badgeClass =
                  candidate.status_badge_variant === "success"
                    ? styles.badgeSuccess
                    : candidate.status_badge_variant === "danger"
                    ? styles.badgeCritical
                    : candidate.status_badge_variant === "warning"
                    ? styles.badgeWarning
                    : styles.badgeSecondary;

                return (
                  <div
                    key={candidate.lecturer_id}
                    className={`${styles.candidateRow} ${candidate.is_eligible ? styles.candidateEligible : ""} ${chosen ? styles.candidateSelected : ""}`}
                    style={{ display: "flex", flexDirection: "column", gap: "6px", alignItems: "stretch", cursor: "default" }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span>
                        <strong>{candidate.lecturer_name}</strong>
                        <span className={`${styles.rootCauseBadge} ${badgeClass}`} style={{ marginLeft: "8px" }}>
                          {candidate.status_label}
                        </span>
                      </span>
                      {candidate.is_eligible ? <CheckCircle2 size={16} color="#16a34a" /> : <AlertCircle size={16} color="#ef4444" />}
                    </div>

                    {candidate.preference_source ? (
                      <small style={{ color: "#991b1b", fontSize: "0.72rem", background: "#fef2f2", padding: "3px 6px", borderRadius: 4 }}>
                        📋 {candidate.preference_source.sheet}!{candidate.preference_source.cell}: {candidate.preference_source.raw_text}
                      </small>
                    ) : null}

                    {candidate.conflicting_classes && candidate.conflicting_classes.length ? (
                      <small style={{ color: "#991b1b", fontSize: "0.72rem", background: "#fef2f2", padding: "3px 6px", borderRadius: 4 }}>
                        ⚠️ {candidate.conflicting_classes.map((c) => `Trùng với ${c.class_code} (${c.course_name}) tuần [${c.overlapping_weeks.join(", ")}]`).join("; ")}
                      </small>
                    ) : null}

                    <div style={{ display: "flex", gap: "6px", marginTop: "2px", justifyContent: "flex-end" }}>
                      {candidate.is_eligible ? (
                        <>
                          <button
                            type="button"
                            className={styles.btnSm}
                            onClick={() => onManual(selectedClass.id, candidate.lecturer_id, false)}
                          >
                            Phân công
                          </button>
                          <button
                            type="button"
                            className={`${styles.btnSm} ${styles.btnSmPrimary}`}
                            onClick={() => onManual(selectedClass.id, candidate.lecturer_id, true)}
                          >
                            <Lock size={12} /> Phân & Khóa
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className={styles.btnSm}
                          style={{ color: "#b91c1c", borderColor: "#fca5a5" }}
                          onClick={() => {
                            const collisionDesc = candidate.conflicting_classes?.length
                              ? candidate.conflicting_classes.map((c) => `Trùng lớp ${c.class_code} (${c.course_name}) tuần [${c.overlapping_weeks.join(", ")}]`).join("; ")
                              : candidate.preference_source
                              ? `Bận cứng: ${candidate.preference_source.raw_text}`
                              : candidate.status_label;
                            setOverrideModal({
                              isOpen: true,
                              classItem: selectedClass,
                              lecturerId: candidate.lecturer_id,
                              lecturerName: candidate.lecturer_name,
                              collisionDetails: collisionDesc,
                              reason: "",
                              confirmedCheckbox: false,
                            });
                          }}
                        >
                          <Lock size={12} /> Ghi đè (HITL)
                        </button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </aside>
      ) : null}
    </div>

    {/* Human-in-the-Loop Lock Override Modal */}
    {overrideModal?.isOpen ? (
      <div className={styles.modalOverlay}>
        <div className={styles.modalBox}>
          <div className={styles.modalHeader}>
            <h3 style={{ display: "flex", alignItems: "center", gap: 8, color: "#b91c1c" }}>
              <AlertTriangle size={20} /> Xác nhận ghi đè phân công (Human-in-the-Loop)
            </h3>
            <button type="button" className={styles.editIcon} onClick={() => setOverrideModal(null)}>
              <X size={18} />
            </button>
          </div>
          <div className={styles.modalBody}>
            <div className={styles.hitlLockCallout}>
              <strong><ShieldCheck size={16} /> Chính sách kiểm soát nghiêm ngặt:</strong>
              <p>
                Hệ thống và bộ giải <strong>KHÔNG</strong> bao giờ tự động phá khóa hoặc ép vi phạm ràng buộc.
                Thao tác này là quyết định can thiệp trực tiếp của con người (Human-in-the-Loop) và sẽ được ghi vào
                nhật ký kiểm toán (Audit Trail) với đầy đủ thông tin định danh và lý do.
              </p>
            </div>

            <div>
              <p style={{ margin: "0 0 6px 0", fontSize: "0.85rem" }}>
                Lớp học phần: <strong>{overrideModal.classItem.class_code}</strong> — {overrideModal.classItem.course_name}
              </p>
              <p style={{ margin: "0 0 6px 0", fontSize: "0.85rem" }}>
                Giảng viên chỉ định: <strong>{overrideModal.lecturerName}</strong>
              </p>
              {overrideModal.collisionDetails ? (
                <div style={{ padding: "8px 12px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, fontSize: "0.78rem", color: "#991b1b" }}>
                  <strong>Chi tiết vi phạm / xung đột:</strong> {overrideModal.collisionDetails}
                </div>
              ) : null}
            </div>

            <label className={styles.field}>
              <span>Lý do ghi đè bắt buộc <small style={{ color: "#ef4444" }}>*</small></span>
              <textarea
                style={{ width: "100%", padding: "8px", borderRadius: 6, border: "1px solid var(--color-border)", minHeight: 70, fontSize: "0.82rem" }}
                placeholder="Nhập lý do Trưởng bộ môn chỉ định ngoại lệ hoặc điều chỉnh giảng viên..."
                value={overrideModal.reason}
                onChange={(e) => setOverrideModal({ ...overrideModal, reason: e.target.value })}
              />
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={overrideModal.confirmedCheckbox}
                onChange={(e) => setOverrideModal({ ...overrideModal, confirmedCheckbox: e.target.checked })}
              />
              <span>Tôi đã đối chiếu thời khóa biểu và chịu trách nhiệm về quyết định ghi đè này.</span>
            </label>
          </div>
          <div className={styles.modalFooter}>
            <button type="button" className={styles.secondaryButton} onClick={() => setOverrideModal(null)}>
              Hủy bỏ
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              style={{ background: "#dc2626", borderColor: "#dc2626" }}
              disabled={!overrideModal.confirmedCheckbox || overrideModal.reason.trim().length < 5}
              onClick={() => {
                if (onOverrideLock) {
                  onOverrideLock(overrideModal.classItem.id, overrideModal.lecturerId, overrideModal.reason, true);
                } else {
                  onManual(overrideModal.classItem.id, overrideModal.lecturerId, true, true, overrideModal.reason);
                }
                setOverrideModal(null);
              }}
            >
              <Lock size={15} /> Tôi chịu trách nhiệm, Mở khóa & Ghi đè phân công
            </button>
          </div>
        </div>
      </div>
    ) : null}

    {/* Privileged Final Export Modal */}
    {privilegedExportModal?.isOpen ? (
      <div className={styles.modalOverlay}>
        <div className={styles.modalBox}>
          <div className={styles.modalHeader}>
            <h3 style={{ display: "flex", alignItems: "center", gap: 8, color: "#b91c1c" }}>
              <ShieldCheck size={20} /> Xuất Final với quyền Trưởng bộ môn (Ghi đè)
            </h3>
            <button type="button" className={styles.editIcon} onClick={() => setPrivilegedExportModal(null)}>
              <X size={18} />
            </button>
          </div>
          <div className={styles.modalBody}>
            <div className={styles.hitlLockCallout}>
              <strong>Cảnh báo xuất file chính thức chưa hoàn tất 100%:</strong>
              <p>
                Hiện tại vẫn còn <strong>{metrics.unassigned_classes} TeachingGroup chưa được phân công</strong>.
                Theo quy định thông thường, file Final yêu cầu 100% lớp học phần phải có giảng viên.
                Bạn đang sử dụng quyền Trưởng bộ môn để phê duyệt xuất phương án đặc cách.
              </p>
            </div>
            <label className={styles.field}>
              <span>Lý do phê duyệt xuất đặc cách <small style={{ color: "#ef4444" }}>*</small></span>
              <textarea
                style={{ width: "100%", padding: "8px", borderRadius: 6, border: "1px solid var(--color-border)", minHeight: 70, fontSize: "0.82rem" }}
                placeholder="Ví dụ: Các lớp chưa phân sẽ được Nhà trường ghép lớp bổ sung hoặc mời thỉnh giảng sau..."
                value={privilegedExportModal.reason}
                onChange={(e) => setPrivilegedExportModal({ ...privilegedExportModal, reason: e.target.value })}
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={privilegedExportModal.confirmedCheckbox}
                onChange={(e) => setPrivilegedExportModal({ ...privilegedExportModal, confirmedCheckbox: e.target.checked })}
              />
              <span>Xác nhận chịu trách nhiệm xuất file với các lớp chưa phân công.</span>
            </label>
          </div>
          <div className={styles.modalFooter}>
            <button type="button" className={styles.secondaryButton} onClick={() => setPrivilegedExportModal(null)}>
              Hủy bỏ
            </button>
            <a
              className={styles.primaryButton}
              style={{ background: "#dc2626", borderColor: "#dc2626", pointerEvents: (!privilegedExportModal.confirmedCheckbox || privilegedExportModal.reason.trim().length < 5) ? "none" : "auto", opacity: (!privilegedExportModal.confirmedCheckbox || privilegedExportModal.reason.trim().length < 5) ? 0.5 : 1 }}
              href={api.exportUrl("final", semesterId ?? undefined, "detailed", true, privilegedExportModal.reason)}
              onClick={() => setPrivilegedExportModal(null)}
            >
              <Download size={16} /> Xác nhận & Xuất Final Excel
            </a>
          </div>
        </div>
      </div>
    ) : null}

    <div className={styles.stickyContinue}><span>Các thay đổi thủ công được kiểm tra với backend trước khi lưu.</span><button type="button" className={styles.primaryButton} onClick={onNext}>Rà soát để xuất<ArrowRight size={16} /></button></div>
  </section>;
}

function ExportReadiness({
  metrics,
  problems,
  semesterId,
  finalReady,
  onOpenPrivileged,
}: {
  metrics: DashboardMetrics;
  problems: Problem[];
  semesterId?: number;
  finalReady: boolean;
  onOpenPrivileged?: () => void;
}) {
  const critical = problems.filter((item) => item.severity === "critical");
  return (
    <div className={styles.exportReadiness}>
      <div className={styles.flatPanel}>
        <span className={styles.eyebrow}>DRAFT EXPORT</span>
        <strong>Luôn giữ nguyên cấu trúc file nguồn</strong>
        <p>Chỉ cập nhật ô giảng viên trong bản copy; các ô và thứ tự dòng khác được bảo toàn. Các lớp chưa phân được ghi rõ nhãn &ldquo;Chưa phân công&rdquo;.</p>
        <a className={styles.primaryButton} href={api.exportUrl("draft", semesterId)}>
          <FileSpreadsheet size={17} />
          Xuất Draft Excel
        </a>
      </div>
      <div className={styles.flatPanel}>
        <span className={styles.eyebrow}>FINAL EXPORT</span>
        <strong>{finalReady ? "Sẵn sàng xuất Final" : "Final export chưa sẵn sàng"}</strong>
        <p>
          {finalReady
            ? "Không còn điều kiện blocking theo dữ liệu backend."
            : `${critical.length} vấn đề nghiêm trọng · ${metrics.unassigned_classes} TeachingGroup chưa phân.`}
        </p>
        {!finalReady && critical.length ? (
          <ul>
            {critical.map((item) => (
              <li key={`${item.code}-${item.entity_id}`}>{item.message}</li>
            ))}
          </ul>
        ) : null}
        {finalReady ? (
          <a className={styles.primaryButton} href={api.exportUrl("final", semesterId)}>
            <Download size={17} />
            Xuất Final Excel
          </a>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: "flex-start" }}>
            <button type="button" className={styles.secondaryButton} disabled>
              <Lock size={16} />
              Cần xử lý trước khi xuất
            </button>
            {metrics.unassigned_classes > 0 && onOpenPrivileged ? (
              <button
                type="button"
                className={styles.secondaryButton}
                style={{ color: "#dc2626", borderColor: "#fca5a5" }}
                onClick={onOpenPrivileged}
              >
                <ShieldCheck size={16} /> Xuất Final quyền Trưởng bộ môn (Ghi đè)
              </button>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function ReadinessPanel({ readiness, lecturers, issues, semesterId, onProblems, onResolved }: { readiness: Readiness | null; lecturers: Lecturer[]; issues: ValidationIssue[]; semesterId: number | null; onProblems: () => void; onResolved: () => Promise<void> }) {
  const [alias, setAlias] = useState("");
  const [lecturerId, setLecturerId] = useState("");
  const [resolved, setResolved] = useState(false);
  const [capReadiness, setCapReadiness] = useState<CapabilityReadiness | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const histInputRef = useRef<HTMLInputElement>(null);
  const matrixInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!semesterId) return;
    void api.capabilityReadiness(semesterId).then(setCapReadiness).catch(() => setCapReadiness(null));
  }, [semesterId]);

  const handleUploadHistory = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !semesterId) return;
    setUploading("history");
    setUploadMsg(null);
    try {
      const res = await api.learnHistoricalCapabilities(semesterId, file);
      setUploadMsg(`Đã học ${res.capabilities_learned || res.learned_capabilities || 0} năng lực từ file lịch sử.`);
      const updated = await api.capabilityReadiness(semesterId);
      setCapReadiness(updated);
      await onResolved();
    } catch (err: unknown) {
      setUploadMsg(`Lỗi: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(null);
      if (histInputRef.current) histInputRef.current.value = "";
    }
  };

  const handleUploadMatrix = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !semesterId) return;
    setUploading("matrix");
    setUploadMsg(null);
    try {
      const res = await api.importCapabilityMatrix(semesterId, file, true);
      setUploadMsg(`Đã nạp ${res.capabilities_created || 0} năng lực mới, cập nhật ${res.capabilities_updated || 0}.`);
      const updated = await api.capabilityReadiness(semesterId);
      setCapReadiness(updated);
      await onResolved();
    } catch (err: unknown) {
      setUploadMsg(`Lỗi: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(null);
      if (matrixInputRef.current) matrixInputRef.current.value = "";
    }
  };

  if (!readiness) return <div className={styles.emptyPanel}><LoaderCircle size={20} className={styles.spin} />Đang kiểm tra dữ liệu…</div>;
  const ambiguous = issues.filter((item) => item.code === "LECTURER_IDENTITY_AMBIGUOUS");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <div className={styles.flatPanel}>
        <span className={styles.eyebrow}>READY TO SOLVE</span>
        <strong>{readiness.ready ? "Dữ liệu sẵn sàng chạy solver" : "Cần rà soát dữ liệu trước khi chạy solver"}</strong>
        <div className={styles.metricGrid}>
          <Metric label="Giảng viên" value={String(readiness.lecturers.total)} detail={`${readiness.lecturers.resolved} đã xác thực · ${readiness.lecturers.need_review} cần rà soát`} tone={readiness.lecturers.need_review ? "red" : "green"} />
          <Metric label="TeachingGroups" value={String(readiness.teaching_groups)} detail={`${readiness.meetings} meetings`} tone="blue" />
          <Metric label="Capability" value={String(readiness.groups_without_capability)} detail="lớp chưa có capability" tone={readiness.groups_without_capability ? "red" : "green"} />
        </div>
        {readiness.warnings.length ? <ul>{readiness.warnings.map((item) => <li key={`${item.code}-${item.message}`}><strong>{item.code}</strong> · {item.message}</li>)}</ul> : <p>✓ Lecturer identity, meeting và capability hiện không có cảnh báo blocking.</p>}
        {ambiguous.length ? (
          <div className={styles.composerGrid}>
            <label className={styles.field}><span>Alias cần map</span><select value={alias} onChange={(event) => setAlias(event.target.value)}><option value="">Chọn alias…</option>{ambiguous.map((item) => <option key={item.id} value={item.raw_value ?? ""}>{item.raw_value ?? item.message}</option>)}</select></label>
            <label className={styles.field}><span>Giảng viên chuẩn</span><select value={lecturerId} onChange={(event) => setLecturerId(event.target.value)}><option value="">Chọn giảng viên…</option>{lecturers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <button type="button" className={styles.secondaryButton} disabled={!alias || !lecturerId || !semesterId} onClick={() => semesterId && void api.resolveAlias(Number(lecturerId), alias, semesterId).then(async () => { await onResolved(); setResolved(true); })}>Xác nhận alias</button>
            {resolved ? <small>Đã lưu mapping alias và cập nhật readiness.</small> : null}
          </div>
        ) : null}
        <button type="button" className={styles.secondaryButton} onClick={onProblems}>Review Problems<ArrowRight size={16} /></button>
      </div>

      <div className={styles.flatPanel} style={{ borderLeft: capReadiness?.zero_candidate_groups ? "4px solid #ef4444" : "4px solid #10b981" }}>
        <span className={styles.eyebrow}>CAPABILITY READINESS (ĐỘ PHỦ NĂNG LỰC BỘ MÔN)</span>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <strong>
            {capReadiness?.department_name ? `${capReadiness.department_name} — ` : ""}
            {capReadiness?.ready ? "Đủ năng lực cho toàn bộ TeachingGroups" : "Chưa đủ dữ liệu năng lực giảng dạy"}
          </strong>
          <span className={`${styles.statusPill} ${capReadiness?.ready ? styles.statusconfirmed : styles.statusrejected}`}>
            {capReadiness?.status ?? "ĐANG TẢI…"}
          </span>
        </div>

        <div className={styles.metricGrid}>
          <Metric
            label="Confirmed"
            value={`${capReadiness?.confirmed_coverage_pct ?? 0}%`}
            detail={`${capReadiness?.confirmed_groups ?? 0} lớp (Chính thức)`}
            tone="green"
          />
          <Metric
            label="Historical"
            value={`${capReadiness?.historical_coverage_pct ?? 0}%`}
            detail={`${capReadiness?.historical_groups ?? 0} lớp (Lịch sử)`}
            tone="blue"
          />
          <Metric
            label="Provisional"
            value={`${capReadiness?.provisional_coverage_pct ?? 0}%`}
            detail={`${capReadiness?.provisional_groups ?? 0} lớp (Tạm thời)`}
            tone="violet"
          />
          <Metric
            label="Unknown (Thiếu)"
            value={`${capReadiness?.unknown_coverage_pct ?? 0}%`}
            detail={`${capReadiness?.zero_candidate_groups ?? 0} lớp (0 ứng viên)`}
            tone={capReadiness?.zero_candidate_groups ? "red" : "green"}
          />
        </div>

        {capReadiness && capReadiness.unknown_coverage_pct === 100 ? (
          <div style={{ padding: "12px 16px", background: "#7f1d1d", color: "#ffffff", borderRadius: "6px", margin: "12px 0", fontWeight: 600 }}>
            🚨 SOLVER BỊ CHẶN: 100% lớp học chưa có giảng viên có năng lực (0% coverage). Cần nạp ma trận năng lực hoặc file phân công lịch sử trước khi giải.
          </div>
        ) : null}

        {capReadiness?.zero_candidate_groups && capReadiness.unknown_coverage_pct !== 100 ? (
          <div style={{ padding: "10px 14px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", color: "#991b1b", margin: "12px 0", fontSize: "0.86rem" }}>
            <strong>Cảnh báo thiếu dữ liệu:</strong> Có {capReadiness.zero_candidate_groups} TeachingGroup không có giảng viên nào đủ năng lực. Hãy nạp file phân công lịch sử hoặc ma trận năng lực trước khi chạy solver.
          </div>
        ) : null}

        {capReadiness?.courses_without_capability?.length ? (
          <div style={{ margin: "10px 0", padding: "8px 12px", background: "rgba(239, 68, 68, 0.08)", borderRadius: "6px", fontSize: "0.85rem" }}>
            <strong style={{ color: "#b91c1c" }}>Các môn chưa có giảng viên đủ năng lực ({capReadiness.courses_without_capability.length}):</strong>
            <ul style={{ margin: "6px 0", paddingLeft: "20px" }}>
              {capReadiness.courses_without_capability.slice(0, 10).map((c) => (
                <li key={c.course_id}>{c.course_code} - {c.course_name} ({c.affected_groups} lớp)</li>
              ))}
              {capReadiness.courses_without_capability.length > 10 ? <li>... và {capReadiness.courses_without_capability.length - 10} môn khác</li> : null}
            </ul>
          </div>
        ) : null}

        <div style={{ display: "flex", gap: "12px", marginTop: "12px", alignItems: "center", flexWrap: "wrap" }}>
          <input type="file" ref={histInputRef} style={{ display: "none" }} accept=".xlsx,.xls,.csv" onChange={handleUploadHistory} />
          <input type="file" ref={matrixInputRef} style={{ display: "none" }} accept=".xlsx,.xls,.csv" onChange={handleUploadMatrix} />
          
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={uploading !== null || !semesterId}
            onClick={() => histInputRef.current?.click()}
          >
            {uploading === "history" ? <LoaderCircle size={15} className={styles.spin} /> : <FileSpreadsheet size={15} />}
            Nạp phân công lịch sử
          </button>

          <button
            type="button"
            className={styles.secondaryButton}
            disabled={uploading !== null || !semesterId}
            onClick={() => matrixInputRef.current?.click()}
          >
            {uploading === "matrix" ? <LoaderCircle size={15} className={styles.spin} /> : <Table size={15} />}
            Nạp ma trận năng lực
          </button>
        </div>
        {uploadMsg ? <small style={{ display: "block", marginTop: "8px", color: uploadMsg.startsWith("Lỗi") ? "#ef4444" : "#10b981" }}>{uploadMsg}</small> : null}
      </div>
    </div>
  );
}

function WorkloadPanel({ workload }: { workload: Workload[] }) {
  const [descending, setDescending] = useState(true);
  const rows = [...workload].sort((left, right) => descending ? right.periods - left.periods : left.periods - right.periods);
  const average = rows.length ? rows.reduce((sum, item) => sum + item.periods, 0) / rows.length : 0;
  return <div className={styles.flatPanel}><div className={styles.panelHeader}><div><span>WORKLOAD</span><strong>Tải giảng dạy theo giảng viên</strong></div><button type="button" className={styles.secondaryButton} onClick={() => setDescending(!descending)}>{descending ? "Nhiều → ít" : "Ít → nhiều"}</button></div><table className={styles.assignmentTable}><thead><tr><th>Giảng viên</th><th>Groups</th><th>Meetings</th><th>Periods</th><th>Credits</th><th>Trạng thái</th></tr></thead><tbody>{rows.map((item) => <tr key={item.lecturer_id}><td>{item.lecturer}</td><td>{item.teaching_groups}</td><td>{item.meetings}</td><td>{item.periods}</td><td>{item.credits}</td><td>{item.periods > average * 1.4 ? "HIGH LOAD" : item.periods < average * 0.6 ? "LOW LOAD" : "Cân bằng"}</td></tr>)}</tbody></table></div>;
}

function MergePanel({ candidates, onDecide }: { candidates: MergeCandidate[]; onDecide: (candidate: MergeCandidate, confirmed: boolean) => void }) {
  return <div className={styles.flatPanel}><span className={styles.eyebrow}>MERGE REVIEW</span><strong>Chỉ ghép khi cùng môn, toàn bộ lịch tương ứng và cùng phòng.</strong>{candidates.length ? <table className={styles.assignmentTable}><thead><tr><th>Loại</th><th>Lớp</th><th>Trùng</th><th>Khác</th><th>Trạng thái</th></tr></thead><tbody>{candidates.map((item) => <tr key={item.id}><td>{item.kind === "PARTIAL" ? "PARTIAL · Review-only" : "FULL"}</td><td>{item.classes.map((row) => row.class_code).join(" ↔ ")}</td><td>{item.matched_meetings} meetings</td><td>{item.different_meetings} meetings</td><td>{item.status}{item.kind === "FULL" && item.status === "candidate" ? <span className={styles.inlineFields}><button type="button" className={styles.secondaryButton} onClick={() => onDecide(item, true)}>Xác nhận ghép</button><button type="button" className={styles.secondaryButton} onClick={() => onDecide(item, false)}>Không ghép</button></span> : null}</td></tr>)}</tbody></table> : <p>Không có merge candidate.</p>}<small>Partial merge chỉ được phát hiện, hiển thị số meeting trùng/khác và yêu cầu review; chưa tự thay đổi solver ở cấp Meeting.</small></div>;
}

function SeminarPanel({ lecturers, seminars, semesterId }: { lecturers: Lecturer[]; seminars: Seminar[]; semesterId: number | null }) {
  const [name, setName] = useState(""); const [members, setMembers] = useState<number[]>([]); const [hardness, setHardness] = useState<"hard" | "soft">("soft"); const [weight, setWeight] = useState(0.8); const [slots, setSlots] = useState(""); const [saved, setSaved] = useState(false);
  const save = async () => { if (!semesterId || !name.trim() || !members.length) return; const [weekday, range] = slots.split(":"); const [start, end] = range.split("-").map(Number); await api.createSeminar({ name, members, hardness, weight, alternatives: [{ weekday: Number(weekday), periods: Array.from({ length: end - start + 1 }, (_, index) => start + index) }] }, semesterId); setSaved(true); setName(""); setMembers([]); };
  return <div className={styles.flatPanel}><span className={styles.eyebrow}>SHARED SEMINAR EVENT</span><strong>Một event chung, nhiều người tham gia — không tạo constraint seminar lặp lại.</strong><div className={styles.composerGrid}><label className={styles.field}><span>Tên seminar</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label className={styles.field}><span>Khung cho phép</span><select value={slots} onChange={(event) => setSlots(event.target.value)}><option value="">Chọn khung seminar…</option>{["2:4-6", "3:4-6", "4:4-6", "5:4-6", "6:4-6", "2:10-12", "3:10-12", "4:10-12", "5:10-12", "6:10-12"].map((item) => <option key={item} value={item}>T{item.replace(":", " · ")}</option>)}</select></label></div><div className={styles.candidateList}><span>Giảng viên tham gia</span>{lecturers.map((item) => <label key={item.id} className={styles.switchLabel}><input type="checkbox" checked={members.includes(item.id)} onChange={() => setMembers((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])} />{item.name}</label>)}</div><div className={styles.inlineFields}><label className={styles.field}><span>Loại</span><select value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}><option value="soft">SOFT</option><option value="hard">HARD</option></select></label><label className={styles.field}><span>Weight (SOFT)</span><input type="number" min="0" max="1" step="0.1" disabled={hardness === "hard"} value={Number.isNaN(weight) ? "" : weight} onChange={(event) => setWeight(event.target.value === "" ? NaN : Number(event.target.value))} /></label></div><button type="button" className={styles.primaryButton} onClick={() => void save()} disabled={!name.trim() || !members.length || !slots || !Number.isFinite(weight)}>Lưu seminar chung</button>{saved ? <small>Đã lưu shared seminar. Chạy lại solver để áp dụng.</small> : null}<div className={styles.problemLog}>{seminars.map((item) => <p key={item.id}><strong>{item.name}</strong> · {item.members.length} participants · {item.hardness.toUpperCase()} {item.hardness === "soft" ? `— ${item.weight.toFixed(1)}` : "— không được vi phạm"}</p>)}</div></div>;
}

function RunDiffPanel({ status, diff }: { status: string; diff: RunDiff | null }) {
  return <div className={styles.flatPanel}><span className={styles.eyebrow}>RE-SOLVE RESULT</span><strong className={styles.runStatus}>{status}</strong>{diff ? <><p>Assigned: {diff.assigned} · Unassigned: {diff.unassigned} · Changed: {diff.changed_assignments} · New problems: {diff.new_problems} · Resolved: {diff.resolved_problems}</p>{diff.changes.length ? <table className={styles.assignmentTable}><thead><tr><th>TeachingGroup</th><th>Before</th><th>After</th><th>Source</th><th>Lock</th></tr></thead><tbody>{diff.changes.map((item) => <tr key={item.class_id}><td>{item.class_code}</td><td>{item.before_lecturer ?? "—"}</td><td>{item.after_lecturer ?? "—"}</td><td>{item.source ?? "—"}</td><td>{item.locked ? "Locked" : "—"}</td></tr>)}</tbody></table> : <p>Không có thay đổi so với phiên trước.</p>}</> : <p>Chưa có diff vì chưa có hai phiên solver liên tiếp.</p>}</div>;
}

// Retained only as a compatibility view while the scheduling workspace is
// being rolled out; the primary route uses SchedulingWorkspace above.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function AssignmentWorkspace({ metrics, classes, constraints, issues, busy, onRun, onCreate, onNext }: { metrics: DashboardMetrics; classes: ClassItem[]; constraints: Constraint[]; issues: ValidationIssue[]; busy: string | null; onRun: () => void; onCreate: (payload: Record<string, unknown>) => void; onNext: () => void }) {
  const lecturers = useMemo(() => Array.from(new Set(classes.map((item) => item.lecturer).filter((name): name is string => Boolean(name)))).sort(), [classes]);
  const lecturerOptions = useMemo(() => Array.from(new Map(classes.filter((item) => item.lecturer_id && item.lecturer).map((item) => [item.lecturer_id, { id: item.lecturer_id as number, name: item.lecturer as string }])).values()).sort((left, right) => left.name.localeCompare(right.name, "vi")), [classes]);
  const [selectedLecturer, setSelectedLecturer] = useState(lecturers[0] ?? "");
  const [draftName, setDraftName] = useState("Không xếp lịch vào khung giờ này");
  const [draftHardness, setDraftHardness] = useState<"hard" | "soft">("soft");
  const [draftWeight, setDraftWeight] = useState(0.8);
  const [draftLecturerId, setDraftLecturerId] = useState("");
  const [draftWeekday, setDraftWeekday] = useState("2");
  const [draftBlock, setDraftBlock] = useState("1-3");
  const events = classes.filter((item) => !selectedLecturer || item.lecturer === selectedLecturer);
  const assigned = metrics.classes - metrics.unassigned_classes;
  const [draftStart, draftEnd] = draftBlock.split("-").map(Number);
  const affectedClasses = classes.filter((item) => item.lecturer_id === Number(draftLecturerId) && item.sessions.some((session) => session.weekday === Number(draftWeekday) && session.start_period <= draftEnd && session.end_period >= draftStart));
  return <section className={styles.viewEnter}>
    <PageHeading eyebrow="BƯỚC 05" title="Bàn phân công giảng dạy" text="Theo dõi toàn cục ở phía trên; chỉnh ràng buộc và xem lịch phản hồi ngay bên dưới." action={<button type="button" className={styles.primaryButton} disabled={busy === "optimize" || metrics.validation_errors > 0} onClick={onRun}>{busy === "optimize" ? <LoaderCircle size={17} className={styles.spin} /> : <Play size={17} />}Chạy tối ưu</button>} />
    <div className={styles.metricGrid}><Metric label="Lớp đã phân" value={`${assigned}/${metrics.classes}`} detail={`${metrics.locked_classes} lớp đã khóa`} tone="blue" /><Metric label="Nhóm lớp ghép" value={String(metrics.merged_suggestions)} detail="Chờ xác nhận theo nhóm" tone="violet" /><Metric label="Nguyện vọng" value={String(constraints.length)} detail={`${constraints.filter((item) => !item.confirmed).length} cần duyệt`} tone="green" /><Metric label="Không thể thực hiện" value={String(metrics.validation_errors)} detail="Xem log để xử lý" tone={metrics.validation_errors ? "red" : "green"} /></div>
    <div className={styles.dashboardGrid}><div className={styles.progressCard}><div><span>TIẾN ĐỘ PHÂN CÔNG</span><strong>{metrics.classes ? Math.round((assigned / metrics.classes) * 100) : 0}%</strong></div><div className={styles.progressTrack}><span style={{ width: `${metrics.classes ? Math.round((assigned / metrics.classes) * 100) : 0}%` }} /></div><p>Trạng thái bộ giải: <strong>{metrics.optimization_status === "not_run" ? "Chưa chạy" : metrics.optimization_status}</strong></p></div><div className={styles.logCard}><div className={styles.logHeader}><span>NHẬT KÝ KIỂM TRA</span><strong>{issues.length} mục</strong></div>{issues.length ? issues.slice(0, 3).map((issue) => <div className={styles.logRow} key={issue.id}><AlertCircle size={15} /><span><strong>{issue.message}</strong><small>{issue.source_file} · dòng {issue.source_row ?? "—"}</small></span></div>) : <div className={styles.cleanLog}><CheckCircle2 size={18} />Không có lỗi nghiêm trọng.</div>}</div></div>
    <div className={styles.workspaceGrid}><div className={styles.calendarPanel}><div className={styles.panelHeader}><div><span>XEM TRƯỚC KẾT QUẢ</span><strong>Thời khóa biểu theo giảng viên</strong></div><select value={selectedLecturer} onChange={(event) => setSelectedLecturer(event.target.value)}><option value="">Toàn bộ giảng viên</option>{lecturers.map((name) => <option key={name}>{name}</option>)}</select></div><CalendarPreview classes={events} /></div><aside className={styles.constraintEditor}><div className={styles.panelHeader}><div><span>RÀNG BUỘC MỚI</span><strong>Chỉnh và xem trước</strong></div><Settings2 size={18} /></div><label className={styles.field}><span>Tên ràng buộc</span><input value={draftName} onChange={(event) => setDraftName(event.target.value)} /></label><label className={styles.field}><span>Giảng viên</span><select value={draftLecturerId} onChange={(event) => setDraftLecturerId(event.target.value)}><option value="">Chọn giảng viên…</option>{lecturerOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><div className={styles.inlineFields}><label className={styles.field}><span>Ngày</span><select value={draftWeekday} onChange={(event) => setDraftWeekday(event.target.value)}>{[2, 3, 4, 5, 6, 7, 8].map((day) => <option key={day} value={day}>{day === 8 ? "Chủ Nhật" : `Thứ ${day}`}</option>)}</select></label><label className={styles.field}><span>Khung tiết</span><select value={draftBlock} onChange={(event) => setDraftBlock(event.target.value)}>{["1-3", "4-6", "7-9", "10-12", "13-15"].map((block) => <option key={block}>{block}</option>)}</select></label></div><div className={styles.inlineFields}><label className={styles.field}><span>Mức độ</span><select value={draftHardness} onChange={(event) => setDraftHardness(event.target.value as "hard" | "soft")}><option value="soft">Ưu tiên mềm</option><option value="hard">Bắt buộc</option></select></label><label className={styles.field}><span>Trọng số</span><input type="number" min="0" max="1" step="0.1" disabled={draftHardness === "hard"} value={draftHardness === "hard" ? 1 : draftWeight} onChange={(event) => setDraftWeight(Number(event.target.value))} /></label></div><div className={styles.livePreview}><span>XEM TRƯỚC REALTIME</span><strong>{draftName || "Ràng buộc chưa có tên"}</strong><p>{draftLecturerId ? `${affectedClasses.length} lớp hiện tại chạm khung Thứ ${draftWeekday}, tiết ${draftBlock}. ` : "Chọn giảng viên để xem lớp bị tác động. "}{draftHardness === "hard" ? "Solver bắt buộc tránh khung này." : `Solver ưu tiên tránh với trọng số ${draftWeight.toFixed(1)}.`}</p></div><button type="button" className={styles.secondaryButton} disabled={!draftName.trim() || !draftLecturerId || busy === "new-constraint"} onClick={() => onCreate({ name: draftName, raw_text: `${draftName} · Thứ ${draftWeekday}, tiết ${draftBlock}`, constraint_type: "unavailable", lecturer_id: Number(draftLecturerId), hardness: draftHardness, weight: draftHardness === "hard" ? 1 : draftWeight, target: { weekday: Number(draftWeekday), periods: Array.from({ length: draftEnd - draftStart + 1 }, (_, index) => draftStart + index) }, confirmed: true })}><Plus size={16} />Thêm vào phương án</button></aside></div>
    <div className={styles.stickyContinue}><span>Mỗi lần chạy tạo một phương án mới; các phân công đã khóa được giữ nguyên.</span><button type="button" className={styles.primaryButton} disabled={!assigned} onClick={onNext}>Rà soát để xuất<ArrowRight size={16} /></button></div>
  </section>;
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: "blue" | "violet" | "green" | "red" }) {
  return <div className={styles.metric}><span className={`${styles.metricMark} ${styles[tone]}`} /><div><small>{label}</small><strong>{value}</strong><span>{detail}</span></div></div>;
}

function CalendarPreview({ classes }: { classes: ClassItem[] }) {
  return <AppleCalendarView classes={classes} />;
}

function PublishView({ metrics, problems, semesterId }: { metrics: DashboardMetrics; problems: Problem[]; semesterId?: number }) {
  const [privilegedModal, setPrivilegedModal] = useState<{
    isOpen: boolean;
    reason: string;
    confirmedCheckbox: boolean;
  } | null>(null);

  const critical = problems.filter((item) => item.severity === "critical");
  const ready = metrics.classes > 0 && metrics.unassigned_classes === 0 && critical.length === 0 && ["optimal", "feasible"].includes(metrics.optimization_status);

  return (
    <section className={styles.viewEnter}>
      <PageHeading eyebrow="BƯỚC 06" title="Chốt và xuất kết quả" text="Một bản phát hành giữ nguyên dữ liệu nguồn, ràng buộc và phương án đã được trưởng bộ môn phê duyệt." />
      <div className={styles.publishCard}>
        <span className={`${styles.publishSeal} ${ready ? styles.sealReady : ""}`}>
          {ready ? <CheckCircle2 size={28} /> : <AlertCircle size={28} />}
        </span>
        <div>
          <strong>{ready ? "Phương án đã sẵn sàng công bố" : "Final export chưa sẵn sàng"}</strong>
          <p>
            {ready
              ? "Không còn lớp chưa phân và không có vấn đề blocking."
              : `${critical.length} vấn đề nghiêm trọng · ${metrics.unassigned_classes} lớp chưa phân. Hãy quay lại Problem Log hoặc tab Chưa phân công để xử lý.`}
          </p>
        </div>
      </div>
      <div className={styles.exportGrid}>
        <a className={styles.exportCard} href={api.exportUrl("draft", semesterId, "detailed")}>
          <FileSpreadsheet size={22} />
          <span>
            <strong>Bảng phân công chi tiết (Portal)</strong>
            <small>Từng lớp học phần, phòng, tuần học (XLSX tương thích chuẩn)</small>
          </span>
          <Download size={17} />
        </a>
        <a className={styles.exportCard} href={api.matrixExportUrl("draft", semesterId)}>
          <FileSpreadsheet size={22} />
          <span>
            <strong>Thời khóa biểu bộ môn (Ma trận)</strong>
            <small>Lưới giảng viên × thứ, bao gồm seminar và ca tối (13–15)</small>
          </span>
          <Download size={17} />
        </a>
        {ready ? (
          <a className={styles.exportCard} href={api.exportUrl("final", semesterId, "detailed")}>
            <CheckCircle2 size={22} />
            <span>
              <strong>Bản chính thức (Final Portal)</strong>
              <small>Phương án đã qua kiểm tra readiness</small>
            </span>
            <Download size={17} />
          </a>
        ) : (
          <button
            type="button"
            className={styles.exportCard}
            style={{ cursor: "pointer", border: "1px dashed #f87171", background: "#fff5f5" }}
            onClick={() => setPrivilegedModal({ isOpen: true, reason: "", confirmedCheckbox: false })}
          >
            <ShieldCheck size={22} color="#dc2626" />
            <span>
              <strong style={{ color: "#991b1b" }}>Xuất Final quyền Trưởng bộ môn</strong>
              <small style={{ color: "#b91c1c" }}>Đặc cách xuất khi còn {metrics.unassigned_classes} lớp chưa phân (Có kiểm toán)</small>
            </span>
            <Download size={17} color="#dc2626" />
          </button>
        )}
      </div>

      {privilegedModal?.isOpen ? (
        <div className={styles.modalOverlay}>
          <div className={styles.modalBox}>
            <div className={styles.modalHeader}>
              <h3 style={{ display: "flex", alignItems: "center", gap: 8, color: "#b91c1c" }}>
                <ShieldCheck size={20} /> Xuất Final với quyền Trưởng bộ môn (Ghi đè)
              </h3>
              <button type="button" className={styles.editIcon} onClick={() => setPrivilegedModal(null)}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.hitlLockCallout}>
                <strong>Cảnh báo xuất file chính thức chưa hoàn tất 100%:</strong>
                <p>
                  Hiện tại vẫn còn <strong>{metrics.unassigned_classes} TeachingGroup chưa được phân công</strong>.
                  Theo quy định thông thường, file Final yêu cầu 100% lớp học phần phải có giảng viên.
                  Bạn đang sử dụng quyền Trưởng bộ môn để phê duyệt xuất phương án đặc cách.
                </p>
              </div>
              <label className={styles.field}>
                <span>Lý do phê duyệt xuất đặc cách <small style={{ color: "#ef4444" }}>*</small></span>
                <textarea
                  style={{ width: "100%", padding: "8px", borderRadius: 6, border: "1px solid var(--color-border)", minHeight: 70, fontSize: "0.82rem" }}
                  placeholder="Ví dụ: Các lớp chưa phân sẽ được Nhà trường ghép lớp bổ sung hoặc mời thỉnh giảng sau..."
                  value={privilegedModal.reason}
                  onChange={(e) => setPrivilegedModal({ ...privilegedModal, reason: e.target.value })}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={privilegedModal.confirmedCheckbox}
                  onChange={(e) => setPrivilegedModal({ ...privilegedModal, confirmedCheckbox: e.target.checked })}
                />
                <span>Xác nhận chịu trách nhiệm xuất file với các lớp chưa phân công.</span>
              </label>
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.secondaryButton} onClick={() => setPrivilegedModal(null)}>
                Hủy bỏ
              </button>
              <a
                className={styles.primaryButton}
                style={{ background: "#dc2626", borderColor: "#dc2626", pointerEvents: (!privilegedModal.confirmedCheckbox || privilegedModal.reason.trim().length < 5) ? "none" : "auto", opacity: (!privilegedModal.confirmedCheckbox || privilegedModal.reason.trim().length < 5) ? 0.5 : 1 }}
                href={api.exportUrl("final", semesterId ?? undefined, "detailed", true, privilegedModal.reason)}
                onClick={() => setPrivilegedModal(null)}
              >
                <Download size={16} /> Xác nhận & Xuất Final Excel
              </a>
            </div>
          </div>
        </div>
      ) : null}

      <p style={{ marginTop: "1rem", color: "var(--color-text-muted)", fontSize: "0.82rem" }}>
        * Lưu ý: File xuất được tạo ở định dạng chuẩn .xlsx để bảo đảm an toàn kỹ thuật và tính toàn vẹn cấu trúc bảng biểu, không làm giả phần mở rộng .xls.
      </p>
    </section>
  );
}
