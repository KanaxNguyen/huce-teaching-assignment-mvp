"use client";

import {
  AlertCircle,
  ArrowRight,
  CalendarRange,
  Check,
  CheckCircle2,
  ChevronRight,
  Columns3,
  Download,
  FileCheck2,
  FileSpreadsheet,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  Lock,
  Menu,
  PencilLine,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
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
  Problem,
  Semester,
  TemplateDetection,
  ValidationIssue,
} from "@/src/types/api";

import styles from "./semester-workflow.module.css";

type View = "semester" | "template" | "inputs" | "preferences" | "workspace" | "publish";

const steps: { id: View; label: string; hint: string; icon: typeof CalendarRange }[] = [
  { id: "semester", label: "Kỳ học", hint: "Thông tin chung", icon: CalendarRange },
  { id: "template", label: "Mẫu đầu ra", hint: "Học từ kỳ trước", icon: Columns3 },
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
  weekday: "Thứ",
  periods: "Tiết học",
  room: "Phòng học",
  weeks: "Tuần học",
};

export function SemesterWorkflowApp() {
  const [view, setView] = useState<View>("semester");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [metrics, setMetrics] = useState(emptyMetrics);
  const [semesters, setSemesters] = useState<Semester[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [lecturers, setLecturers] = useState<Lecturer[]>([]);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [template, setTemplate] = useState<TemplateDetection | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
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
      setProblems(active ? await api.problems(active.id) : []);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể kết nối máy chủ.");
    } finally {
      setLoading(false);
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
      await loadAll();
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
              onUpload={(schedule, preference) => execute("inputs", () => api.uploadPair(schedule, preference), "Đã nhập và chuẩn hóa hai file đầu vào.")}
              onNext={() => setView("preferences")}
            />
          ) : null}
          {!loading && view === "preferences" ? (
            <PreferenceReview
              constraints={constraints}
              lecturers={lecturers}
              busy={busy}
              onSave={(item, payload) => execute(`constraint-${item.id}`, () => api.updateConstraint(item.id, payload), "Đã cập nhật quyết định của trưởng bộ môn.")}
              onDelete={(item) => execute(`delete-${item.id}`, () => api.deleteConstraint(item.id), "Đã loại ràng buộc khỏi phiên lập lịch.")}
              onCreate={(payload) => execute("new-preference", () => api.createConstraint(payload), "Đã thêm ràng buộc mới vào danh sách nguyện vọng.")}
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
              onManual={(classId, lecturerId, lock) => execute(`assignment-${classId}`, () => api.assign(classId, lecturerId, lock, activeSemester?.id ?? 0), lock ? "Đã phân công và khóa lớp học phần." : "Đã cập nhật phân công thủ công.")}
              onUnlock={(classId) => execute(`unlock-${classId}`, () => api.unlock(classId, activeSemester?.id ?? 0), "Đã mở khóa phân công.")}
              onNext={() => setView("publish")}
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
    const mappings = { ...template.mappings, [field]: { ...column, confidence: 0.7 } };
    const missingFields = template.missing_fields.filter((item) => item !== field);
    setTemplate({ ...template, mappings, missing_fields: missingFields, ready: missingFields.length === 0 });
  }
  return <section className={styles.viewEnter}>
    <PageHeading eyebrow="BƯỚC 02" title="Học cấu trúc đầu ra kỳ trước" text="Tải một file kết quả cũ để hệ thống nhận diện cột, thứ tự và cách đặt tên trong mẫu của bộ môn." />
    <div className={styles.uploadSingle}>
      <input ref={inputRef} hidden type="file" accept=".xls,.xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) onDetect(file); }} />
      <span className={styles.fileIcon}><FileSpreadsheet size={23} /></span>
      <div><strong>{template?.source_file ?? "Chưa chọn file mẫu"}</strong><span>{template ? `${template.source_sheet} · tiêu đề tại dòng ${template.header_row}` : "File phân công hoặc TKB đã xuất ở học kỳ trước"}</span></div>
      <button type="button" className={styles.secondaryButton} disabled={busy === "template" || !activeSemester} onClick={() => inputRef.current?.click()}>{busy === "template" ? <LoaderCircle size={17} className={styles.spin} /> : <UploadCloud size={17} />}Chọn file mẫu</button>
    </div>
    {template ? <div className={styles.mappingCard}>
      <div className={styles.mappingHeader}><div><strong>{template.layout_label}</strong><span>{template.ready ? "Cấu trúc mẫu đã sẵn sàng để tái tạo khi xuất." : `${template.missing_fields.length} trường cần trưởng bộ môn chọn lại.`}</span></div><span className={template.ready ? styles.readyBadge : styles.reviewBadge}>{template.ready ? "Sẵn sàng" : "Cần rà soát"}</span></div>
      {template.layout === "matrix" ? <div className={styles.matrixDetection}>
        <div className={styles.matrixDiagram}><span>GIẢNG VIÊN</span>{template.weekday_columns.map((column) => <span key={column.weekday}>{column.header.toUpperCase()}</span>)}</div>
        <div className={styles.matrixCopy}><CheckCircle2 size={20} /><div><strong>Đã hiểu mẫu lịch dạng ma trận</strong><p>Cột A chứa giảng viên; mỗi cột ngày chứa nhiều lớp với tên môn, mã lớp, tiết và khoảng ngày. Khi xuất, hệ thống sẽ gom kết quả về đúng cấu trúc này.</p></div></div>
        {template.preview.length ? <div className={styles.templatePreview}>{template.preview.slice(0, 3).map((row, index) => <span key={`${row.lecturer}-${index}`}><strong>{row.lecturer}</strong><small>{row.schedule_days || "Chưa có lịch"}</small></span>)}</div> : null}
      </div> : <div className={styles.mappingGrid}>
        {fields.map((field) => <label className={styles.mappingRow} key={field}><span><strong>{fieldLabels[field]}</strong><small>{template.mappings[field] ? `Nhận diện ${Math.round(template.mappings[field].confidence * 100)}%` : "Chưa nhận diện"}</small></span><select value={template.mappings[field]?.column_index ?? ""} onChange={(event) => mapField(field, Number(event.target.value))}><option value="">Chọn cột…</option>{template.available_columns.map((column) => <option key={column.column_index} value={column.column_index}>{column.column_letter} · {column.header}</option>)}</select></label>)}
      </div>}
      <div className={styles.cardFooter}><span>Thay đổi chỉ áp dụng cho mẫu đầu ra của kỳ đang chọn.</span><div><button type="button" className={styles.secondaryButton} disabled={busy === "mapping"} onClick={() => onSave(template)}>Lưu ánh xạ</button><button type="button" className={styles.primaryButton} disabled={!template.ready} onClick={onNext}>Dùng mẫu này<ArrowRight size={16} /></button></div></div>
    </div> : <div className={styles.emptyPanel}><Columns3 size={24} /><strong>Hệ thống sẽ tự tìm dòng tiêu đề và đối chiếu tên cột</strong><span>Các trường chưa chắc chắn sẽ được đánh dấu để bạn chọn lại, không tự động điền sai.</span></div>}
  </section>;
}

function InputView({ busy, metrics, onUpload, onNext }: { busy: string | null; metrics: DashboardMetrics; onUpload: (schedule: File, preference: File) => void; onNext: () => void }) {
  const scheduleRef = useRef<HTMLInputElement>(null);
  const preferenceRef = useRef<HTMLInputElement>(null);
  const [schedule, setSchedule] = useState<File | null>(null);
  const [preference, setPreference] = useState<File | null>(null);
  return <section className={styles.viewEnter}>
    <PageHeading eyebrow="BƯỚC 03" title="Nhập dữ liệu học kỳ" text="Hai file được đọc riêng, sau đó hợp nhất thành lớp học phần, giảng viên và danh sách nguyện vọng có cấu trúc." />
    <div className={styles.dualUpload}>
      <UploadCard number="01" title="Thời khóa biểu kỳ này" text="Lớp, môn, thứ, tiết, phòng và tuần học" file={schedule} inputRef={scheduleRef} onChange={setSchedule} />
      <UploadCard number="02" title="Nguyện vọng giảng viên" text="Ngày bận, ưu tiên, seminar và phân công mong muốn" file={preference} inputRef={preferenceRef} onChange={setPreference} />
    </div>
    <div className={styles.importBar}><span>{metrics.classes ? `${metrics.classes} lớp và ${metrics.lecturers} giảng viên đang có trong phiên.` : "Chọn đủ hai file để bắt đầu chuẩn hóa."}</span><div><button type="button" className={styles.primaryButton} disabled={!schedule || !preference || busy === "inputs"} onClick={() => schedule && preference ? onUpload(schedule, preference) : undefined}>{busy === "inputs" ? <LoaderCircle size={17} className={styles.spin} /> : <Sparkles size={17} />}Nộp và chuẩn hóa</button><button type="button" className={styles.textButton} disabled={!metrics.classes} onClick={onNext}>Duyệt kết quả<ArrowRight size={16} /></button></div></div>
    {metrics.classes ? <div className={styles.summaryStrip}><span><strong>{metrics.classes}</strong>Lớp học phần</span><span><strong>{metrics.locked_classes}</strong>Phân công đã khóa</span><span><strong>{metrics.merged_suggestions}</strong>Nhóm ghép đề xuất</span><span><strong>{metrics.validation_errors}</strong>Lỗi cần xử lý</span></div> : null}
  </section>;
}

function UploadCard({ number, title, text, file, inputRef, onChange }: { number: string; title: string; text: string; file: File | null; inputRef: React.RefObject<HTMLInputElement | null>; onChange: (file: File | null) => void }) {
  return <div className={`${styles.uploadCard} ${file ? styles.uploadReady : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const selected = Array.from(event.dataTransfer.files).find((item) => /\.xlsx?$/i.test(item.name) || /\.xls$/i.test(item.name)); if (selected) onChange(selected); }}>
    <input ref={inputRef} hidden type="file" accept=".xls,.xlsx" onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
    <div className={styles.uploadTitle}><span>{number}</span><div><strong>{title}</strong><small>{text}</small></div></div>
    <div className={styles.fileSelection}><FileSpreadsheet size={22} /><span><strong>{file?.name ?? "Chưa chọn file"}</strong><small>{file ? `${(file.size / 1024).toFixed(1)} KB · sẵn sàng` : "Kéo thả hoặc chọn từ máy"}</small></span>{file ? <button type="button" aria-label={`Bỏ ${title}`} onClick={() => onChange(null)}><X size={16} /></button> : <button type="button" onClick={() => inputRef.current?.click()}>Chọn file</button>}</div>
  </div>;
}

function PreferenceReview({ constraints, lecturers, busy, onSave, onDelete, onCreate, onNext }: { constraints: Constraint[]; lecturers: Lecturer[]; busy: string | null; onSave: (item: Constraint, payload: Partial<Constraint>) => void; onDelete: (item: Constraint) => void; onCreate: (payload: Record<string, unknown>) => Promise<void>; onNext: () => void }) {
  const pending = constraints.filter((item) => !item.confirmed);
  const [adding, setAdding] = useState(false);
  return <section className={styles.viewEnter}>
    <PageHeading eyebrow="BƯỚC 04" title="Duyệt nguyện vọng đã chuẩn hóa" text="Mỗi câu gốc được chuyển thành quy tắc theo ngày, tiết và loại ưu tiên. Trưởng bộ môn có thể chỉnh hoặc bổ sung trực tiếp." action={<div className={styles.reviewActions}><span className={pending.length ? styles.reviewBadge : styles.readyBadge}>{pending.length} cần xác nhận</span><button type="button" className={styles.secondaryButton} onClick={() => setAdding((value) => !value)}><Plus size={16} />Thêm ràng buộc</button></div>} />
    {adding ? <PreferenceComposer lecturers={lecturers} busy={busy === "new-preference"} onClose={() => setAdding(false)} onCreate={onCreate} /> : null}
    <div className={styles.preferenceList}>
      {constraints.length ? constraints.map((item) => <PreferenceRow key={`${item.id}-${item.hardness}-${item.weight}-${item.active}-${item.confirmed}`} item={item} lecturers={lecturers} busy={busy === `constraint-${item.id}` || busy === `delete-${item.id}`} onSave={onSave} onDelete={onDelete} />) : <div className={styles.emptyPanel}><FileCheck2 size={24} /><strong>Chưa có nguyện vọng</strong><span>Upload file nguyện vọng hoặc tự thêm một quy tắc mới.</span></div>}
    </div>
    <div className={styles.stickyContinue}><span>Chỉ các ràng buộc đã xác nhận và đang bật mới được đưa vào tối ưu.</span><button type="button" className={styles.primaryButton} disabled={!constraints.length} onClick={onNext}>Mở bàn phân công<ArrowRight size={16} /></button></div>
  </section>;
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

function ConstraintTypeSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <select value={value} onChange={(event) => onChange(event.target.value)}><option value="unavailable">Không xếp lịch</option><option value="available">Có thể dạy</option><option value="prefer_period">Ưu tiên khung giờ</option><option value="seminar">Seminar</option><option value="preferred_assignment">Đề nghị phân công</option><option value="compact_schedule">Ưu tiên lịch gọn</option><option value="raw_preference">Cần rà soát</option></select>; }
function WeekdaySelect({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <select value={value} onChange={(event) => onChange(event.target.value)}><option value="">Mọi ngày</option>{[2, 3, 4, 5, 6, 7, 8].map((day) => <option key={day} value={day}>{day === 8 ? "Chủ Nhật" : `Thứ ${day}`}</option>)}</select>; }
function periodLabel(target?: Record<string, unknown>) { const values = (target?.periods ?? target?.period_range ?? []) as number[]; return values.length ? `${Math.min(...values)}-${Math.max(...values)}` : ""; }
function makeTarget(weekday: string, periodText: string, existing?: Record<string, unknown>) { const values = Array.from(new Set((periodText.match(/\d+/g) ?? []).map(Number).filter((item) => item >= 1 && item <= 15))); const periods = values.length === 2 ? Array.from({ length: values[1] - values[0] + 1 }, (_, index) => values[0] + index) : values; return { ...existing, weekday: weekday ? Number(weekday) : null, periods, analysis: { source: "manual" } }; }
const timetableDays = [2, 3, 4, 5, 6, 7, 8];
const timetableBlocks = [
  { label: "Tiết 1–3", periods: [1, 2, 3] },
  { label: "Tiết 4–6", periods: [4, 5, 6] },
  { label: "Tiết 7–9", periods: [7, 8, 9] },
  { label: "Tiết 10–12", periods: [10, 11, 12] },
];

type PaintedSlot = { slot: string; type: string; draftId: string };
type ConstraintDraft = {
  id: string;
  slots: string[];
  type: string;
  name: string;
  hardness: "hard" | "soft";
  weight: number;
};

function paintClass(type: string) {
  return type === "unavailable" ? styles.slotUnavailable : type === "seminar" ? styles.slotSeminar : type === "available" ? styles.slotAvailable : type === "prefer_period" ? styles.slotPreferred : styles.slotOther;
}

function constraintTypeLabel(type: string) {
  return type === "unavailable" ? "Không thể dạy" : type === "available" ? "Có thể dạy" : type === "prefer_period" ? "Ưu tiên" : type === "seminar" ? "Seminar" : "Ràng buộc khác";
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
    <div className={styles.slotLegend} aria-label="Chú giải trạng thái"><span className={styles.legendAvailable}>Có thể dạy</span><span className={styles.legendPreferred}>Ưu tiên</span><span className={styles.legendUnavailable}>Không thể dạy</span><span className={styles.legendSeminar}>Seminar</span></div>
    <div className={styles.slotGrid}><div className={styles.slotCorner}>BLOCK</div>{timetableDays.map((day) => <div key={day} className={styles.slotDay}>{day === 8 ? "CN" : `T${day}`}</div>)}{timetableBlocks.flatMap((block) => [<div className={styles.slotLabel} key={block.label}>{block.label}</div>, ...timetableDays.map((day) => { const slot = `${day}:${block.periods[0]}-${block.periods.at(-1)}`; const active = selected.includes(slot); const paintedType = paintedBySlot.get(slot)?.type; return <button type="button" key={slot} disabled={disabled} aria-pressed={active} aria-label={`${active ? "Bỏ chọn" : "Chọn"} ${day === 8 ? "Chủ Nhật" : `Thứ ${day}`}, ${block.label}${paintedType ? `, hiện là ${constraintTypeLabel(paintedType)}` : ""}`} className={`${styles.slotCell} ${paintedType ? paintClass(paintedType) : ""} ${active ? styles.slotCellActive : ""}`} onClick={() => toggle(slot)}>{active ? <Check size={15} /> : paintedType ? <span className={styles.slotStateDot} /> : null}</button>; })])}</div>
  </div>;
}

function slotsTarget(selected: string[]) {
  return {
    slots: selected.map((slot) => {
      const [day, periodRange] = slot.split(":");
      const [start, end] = periodRange.split("-").map(Number);
      return { weekday: Number(day), periods: Array.from({ length: end - start + 1 }, (_, index) => start + index) };
    }),
    analysis: { source: "visual_timetable" },
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
  const paintedSlots = [
    ...constraints.filter((item) => item.active && item.lecturer_id === Number(lecturerId)).flatMap((item) => preferenceSlots(item).map((slot) => ({ slot, type: item.constraint_type, draftId: `saved-${item.id}` }))),
    ...drafts.flatMap((draft) => draft.slots.map((slot) => ({ slot, type: draft.type, draftId: draft.id }))),
  ];
  const mergeDraft = (current: ConstraintDraft[]) => {
    const remaining = current.map((draft) => ({ ...draft, slots: draft.slots.filter((slot) => !selectedSlots.includes(slot)) })).filter((draft) => draft.slots.length);
    return [...remaining, { id: globalThis.crypto.randomUUID(), slots: selectedSlots, type, name, hardness, weight: hardness === "hard" ? 1 : weight }];
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
  };
  const finishPainting = async () => {
    const finalDrafts = selectedSlots.length ? mergeDraft(drafts) : drafts;
    for (const draft of finalDrafts) {
      await onCreate({ name: draft.name, lecturer_id: Number(lecturerId), constraint_type: draft.type, hardness: draft.hardness, weight: draft.weight, target: slotsTarget(draft.slots), raw_text: "Ràng buộc do trưởng bộ môn chỉnh trực tiếp trên thời khoá biểu", confirmed: true });
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
        {[{ value: "available", label: "Có thể dạy" }, { value: "prefer_period", label: "Ưu tiên" }, { value: "unavailable", label: "Không thể dạy" }, { value: "seminar", label: "Seminar" }].map((choice) => <button type="button" key={choice.value} disabled={!selectedSlots.length} aria-pressed={type === choice.value} className={`${styles.constraintChoice} ${paintClass(choice.value)} ${type === choice.value ? styles.constraintChoiceActive : ""}`} onClick={() => setType(choice.value)}>{choice.label}</button>)}
      </div>
      <div className={styles.cellEditorSettings}><label className={styles.field}><span>Mức độ</span><select disabled={!selectedSlots.length} value={hardness} onChange={(event) => setHardness(event.target.value as "hard" | "soft")}><option value="soft">Ưu tiên mềm</option><option value="hard">Bắt buộc</option></select></label><label className={styles.switchLabel}><span>Trọng số {hardness === "hard" ? "1.0" : weight.toFixed(1)}</span><input type="range" min="0" max="1" step="0.1" disabled={!selectedSlots.length || hardness === "hard"} value={hardness === "hard" ? 1 : weight} onChange={(event) => setWeight(Number(event.target.value))} /></label><button type="button" className={styles.secondaryButton} disabled={!selectedSlots.length} onClick={() => setSelectedSlots([])}>Bỏ chọn</button><button type="button" className={styles.primaryButton} disabled={!name.trim() || !lecturerId || !selectedSlots.length} onClick={recordRegion}><Check size={16} />Ghi vào lịch</button></div>
    </div>
    <div className={styles.composerFooter}><span className={styles.currentPaintType}>{drafts.length ? <><strong>{drafts.length}</strong> vùng đã ghi tạm</> : "Chưa có vùng nào được ghi"}</span><div><button type="button" className={styles.ghostButton} onClick={onClose}>Hủy</button><button type="button" className={styles.primaryButton} disabled={!lecturerId || (!selectedSlots.length && !drafts.length) || busy} onClick={() => void finishPainting()}>{busy ? <LoaderCircle size={16} className={styles.spin} /> : <Check size={16} />}Chốt tất cả</button></div></div>
    <small className={styles.paintHint}>Các vùng chỉ được gửi vào bộ tối ưu khi bấm “Chốt tất cả”. Trước đó, bấm lại ô đã tô để sửa trạng thái ngay trong bảng.</small>
  </div>;
}

type WorkspaceTab = "overview" | "assignments" | "calendar" | "constraints" | "problems" | "runs" | "export";

const workspaceItems: Array<{ id: WorkspaceTab; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Tổng quan", icon: LayoutDashboard },
  { id: "assignments", label: "Phân công", icon: Users },
  { id: "calendar", label: "Lịch", icon: CalendarRange },
  { id: "constraints", label: "Ràng buộc", icon: Settings2 },
  { id: "problems", label: "Vấn đề", icon: AlertCircle },
  { id: "runs", label: "Phiên bản", icon: RefreshCw },
  { id: "export", label: "Xuất file", icon: Download },
];

function statusFor(item: ClassItem) {
  if (item.locked_assignment) return "Locked";
  if (item.assignment_source === "MANUAL") return "Manual";
  return item.lecturer ? "Assigned" : "Unassigned";
}

function candidateReason(status: string) {
  const labels: Record<string, string> = {
    ELIGIBLE: "Có thể phân công", COURSE_CAPABILITY_MISSING: "Không có capability môn học",
    TIMETABLE_CONFLICT: "Trùng thời khóa biểu", HARD_AVAILABILITY_CONFLICT: "Không khả dụng",
    FORBIDDEN_ASSIGNMENT: "Bị cấm phân công", NO_COURSE_CAPABILITY: "Không có capability môn học",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function SchedulingWorkspace({ metrics, classes, constraints, lecturers, issues, problems, semesterId, busy, onRun, onCreate, onUpdateConstraint, onDeleteConstraint, onManual, onUnlock, onNext }: {
  metrics: DashboardMetrics; classes: ClassItem[]; constraints: Constraint[]; lecturers: Lecturer[]; issues: ValidationIssue[]; problems: Problem[]; semesterId: number | null; busy: string | null;
  onRun: () => void; onCreate: (payload: Record<string, unknown>) => void; onUpdateConstraint: (item: Constraint, payload: Partial<Constraint>) => void; onDeleteConstraint: (item: Constraint) => void;
  onManual: (classId: number, lecturerId: number, lock: boolean) => void; onUnlock: (classId: number) => void; onNext: () => void;
}) {
  void issues;
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [selectedClass, setSelectedClass] = useState<ClassItem | null>(null);
  const [selectedLecturerId, setSelectedLecturerId] = useState<number | null>(null);
  const [candidateRows, setCandidateRows] = useState<Array<{ lecturer_id: number; status: string }>>([]);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateCheck, setCandidateCheck] = useState<{ lecturerId: number; valid: boolean; blocking_reasons: string[] } | null>(null);
  const [problemFilter, setProblemFilter] = useState<"all" | "critical" | "warning" | "info">("all");
  const assigned = classes.filter((item) => Boolean(item.lecturer)).length;
  const hardProblems = problems.filter((item) => item.severity === "critical").length;
  const finalReady = metrics.unassigned_classes === 0 && hardProblems === 0 && ["optimal", "feasible"].includes(metrics.optimization_status);
  const selectedLecturer = lecturers.find((item) => item.id === selectedLecturerId) ?? null;

  useEffect(() => {
    if (!selectedClass || !semesterId) { setCandidateRows([]); return; }
    setCandidateLoading(true); setCandidateCheck(null);
    void api.candidates(selectedClass.id, semesterId).then(setCandidateRows).catch(() => setCandidateRows([])).finally(() => setCandidateLoading(false));
  }, [selectedClass, semesterId]);

  // A reload after a mutation replaces the selected row with the canonical
  // backend record; the inspector never keeps a stale local assignment.
  useEffect(() => {
    setSelectedClass((current) => current ? classes.find((item) => item.id === current.id) ?? null : null);
  }, [classes]);

  const inspectClass = (item: ClassItem) => { setSelectedClass(item); setSelectedLecturerId(null); };
  const filteredProblems = problems.filter((item) => problemFilter === "all" || item.severity === problemFilter);

  return <section className={styles.schedulingShell}>
    <header className={styles.workspaceHeading}>
      <div><span className={styles.eyebrow}>BƯỚC 05 · WORKSPACE</span><h2>Phân công giảng dạy</h2><p>Rà soát dữ liệu, chỉnh phân công và xử lý vấn đề trên một không gian làm việc.</p></div>
      <button type="button" className={styles.primaryButton} disabled={busy === "optimize" || !classes.length} onClick={onRun}>{busy === "optimize" ? <LoaderCircle size={17} className={styles.spin} /> : <Play size={17} />}Chạy lại phân công</button>
    </header>
    <div className={styles.workspaceLayout}>
      <nav className={styles.workspaceNav} aria-label="Không gian phân công">
        {workspaceItems.filter((item) => item.id !== "runs" || metrics.optimization_status !== "not_run").map((item) => { const Icon = item.icon; return <button type="button" key={item.id} className={tab === item.id ? styles.workspaceNavActive : ""} onClick={() => setTab(item.id)}><Icon size={17} />{item.label}{item.id === "problems" && problems.length ? <small>{problems.length}</small> : null}</button>; })}
      </nav>
      <div className={styles.workspaceCenter}>
        {tab === "overview" ? <>
          <div className={styles.metricGrid}><Metric label="TeachingGroups" value={String(metrics.classes)} detail="Tổng số lớp học phần" tone="blue" /><Metric label="Đã phân" value={String(assigned)} detail="Theo dữ liệu hiện tại" tone="green" /><Metric label="Chưa phân" value={String(metrics.unassigned_classes)} detail="Cần solver hoặc xử lý" tone="violet" /><Metric label="Đã khóa" value={String(metrics.locked_classes)} detail="Solver không thay đổi" tone="blue" /><Metric label="Hard problems" value={String(hardProblems)} detail="Cần trưởng bộ môn xử lý" tone={hardProblems ? "red" : "green"} /></div>
          <div className={styles.readinessPanel}><div><span className={styles.eyebrow}>READINESS</span><strong>Draft: sẵn sàng · Final: {finalReady ? "sẵn sàng" : "chưa sẵn sàng"}</strong><p>{finalReady ? "Có thể xuất file Final." : `Cần xử lý ${hardProblems} vấn đề nghiêm trọng và ${metrics.unassigned_classes} TeachingGroup chưa phân trước khi xuất Final.`}</p></div><button type="button" className={styles.secondaryButton} onClick={() => setTab("export")}>Xem điều kiện xuất<ArrowRight size={16} /></button></div>
          <div className={styles.overviewSplit}><div className={styles.flatPanel}><div className={styles.panelHeader}><div><span>PHIÊN GẦN NHẤT</span><strong>{metrics.optimization_status === "not_run" ? "Chưa chạy solver" : metrics.optimization_status}</strong></div><ShieldCheck size={19} /></div><p>{metrics.optimization_status === "blocked" ? "Không thể tạo phương án mới vì có xung đột giữa các phân công đã khóa." : "Mỗi lần chạy tạo một snapshot độc lập; các phân công đã khóa được giữ nguyên."}</p></div><div className={styles.flatPanel}><div className={styles.panelHeader}><div><span>VẤN ĐỀ</span><strong>{problems.length} mục cần theo dõi</strong></div><ListChecks size={19} /></div>{problems.slice(0, 2).map((item) => <button type="button" key={`${item.code}-${item.entity_id}`} className={styles.problemPreview} onClick={() => { setTab("problems"); if (item.entity_type === "class_section") { const found = classes.find((row) => row.id === Number(item.entity_id)); if (found) inspectClass(found); } }}><AlertCircle size={16} /><span>{item.message}</span></button>)}</div></div>
        </> : null}
        {tab === "assignments" ? <div className={styles.assignmentTableWrap}><div className={styles.tableToolbar}><div><strong>Danh sách TeachingGroup</strong><small>Bấm một dòng để xem candidate và chỉnh phân công.</small></div><span>{classes.length} lớp</span></div><table className={styles.assignmentTable}><thead><tr><th>Mã lớp</th><th>Môn</th><th>Lịch</th><th>Giảng viên</th><th>Source</th><th>Lock</th><th>Status</th></tr></thead><tbody>{classes.map((item) => <tr key={item.id} className={selectedClass?.id === item.id ? styles.selectedRow : ""} onClick={() => inspectClass(item)}><td>{item.class_code}</td><td><strong>{item.course_name}</strong><small>{item.course_code}</small></td><td>{item.sessions.map((session) => `T${session.weekday} · ${session.start_period}–${session.end_period}`).join(" · ")}</td><td>{item.lecturer ?? "—"}</td><td>{item.assignment_source ?? (item.lecturer ? "IMPORT" : "—")}</td><td>{item.locked_assignment ? <Lock size={16} aria-label="Đã khóa" /> : "—"}</td><td><span className={`${styles.statusPill} ${styles[`status${statusFor(item)}`]}`}>{statusFor(item)}</span></td></tr>)}</tbody></table>{!classes.length ? <div className={styles.emptyPanel}><Users size={24} /><strong>Chưa có TeachingGroup</strong><span>Hãy hoàn tất bước nhập dữ liệu trước.</span></div> : null}</div> : null}
        {tab === "calendar" ? <div className={styles.flatPanel}><div className={styles.panelHeader}><div><span>LỊCH GIẢNG DẠY</span><strong>Thời khóa biểu theo giảng viên</strong></div><select value={selectedLecturerId ?? ""} onChange={(event) => setSelectedLecturerId(event.target.value ? Number(event.target.value) : null)}><option value="">Tất cả giảng viên</option>{lecturers.map((lecturer) => <option key={lecturer.id} value={lecturer.id}>{lecturer.name}</option>)}</select></div><CalendarPreview classes={selectedLecturer ? classes.filter((item) => item.lecturer_id === selectedLecturer.id) : classes} /></div> : null}
        {tab === "constraints" ? <><div className={styles.workspaceSectionTitle}><div><span>RÀNG BUỘC</span><h3>Lịch nguyện vọng giảng viên</h3></div><span>{constraints.length} quy tắc</span></div><PreferenceComposer lecturers={lecturers} constraints={constraints} busy={busy === "new-constraint"} onCreate={async (payload) => onCreate(payload)} onClose={() => undefined} />{constraints.map((item) => <PreferenceRow key={item.id} item={item} lecturers={lecturers} busy={busy === `constraint-${item.id}`} onSave={onUpdateConstraint} onDelete={onDeleteConstraint} />)}</> : null}
        {tab === "problems" ? <div className={styles.problemLog}><div className={styles.tableToolbar}><div><strong>Problem Log</strong><small>Thông báo từ backend; không suy diễn thêm ở giao diện.</small></div><div className={styles.problemFilters}>{(["all", "critical", "warning", "info"] as const).map((filter) => <button type="button" key={filter} aria-pressed={problemFilter === filter} onClick={() => setProblemFilter(filter)}>{filter === "all" ? "Tất cả" : filter}</button>)}</div></div>{filteredProblems.length ? filteredProblems.map((item) => <article className={`${styles.problemRow} ${styles[`problem${item.severity}`]}`} key={`${item.code}-${item.entity_type}-${item.entity_id}`}><AlertCircle size={18} /><div><strong>{item.code.replaceAll("_", " ")}</strong><p>{item.message}</p>{item.reasons.length ? <small>{item.reasons.map((reason) => String(reason.reason ?? "")).filter(Boolean).join(" · ")}</small> : null}</div>{item.entity_type === "class_section" ? <button type="button" className={styles.textButton} onClick={() => { const found = classes.find((row) => row.id === Number(item.entity_id)); if (found) { inspectClass(found); setTab("assignments"); } }}>Xem lớp<ArrowRight size={15} /></button> : null}</article>) : <div className={styles.emptyPanel}><CheckCircle2 size={24} /><strong>Không có vấn đề cần xử lý</strong><span>Backend chưa ghi nhận diagnostic cho kỳ học này.</span></div>}</div> : null}
        {tab === "runs" ? <div className={styles.flatPanel}><span className={styles.eyebrow}>PHIÊN BẢN GẦN NHẤT</span><strong className={styles.runStatus}>{metrics.optimization_status}</strong><p>Mỗi lần chạy lưu một snapshot độc lập. Trạng thái và kết quả chính thức được lấy từ backend.</p></div> : null}
        {tab === "export" ? <ExportReadiness metrics={metrics} problems={problems} semesterId={semesterId ?? undefined} finalReady={finalReady} /> : null}
      </div>
      {selectedClass ? <aside className={styles.inspector} aria-label="Chi tiết TeachingGroup"><div className={styles.inspectorHeader}><div><span>TEACHINGGROUP</span><strong>{selectedClass.class_code}</strong><small>{selectedClass.course_name}</small></div><button type="button" className={styles.editIcon} onClick={() => setSelectedClass(null)} aria-label="Đóng inspector"><X size={16} /></button></div><div className={styles.inspectorCurrent}><span>Giảng viên hiện tại</span><strong>{selectedClass.lecturer ?? "Chưa phân công"}</strong>{selectedClass.locked_assignment ? <span className={styles.lockedLabel}><Lock size={14} />Đã khóa</span> : null}</div>{selectedClass.locked_assignment ? <button type="button" className={styles.secondaryButton} disabled={busy === `unlock-${selectedClass.id}`} onClick={() => onUnlock(selectedClass.id)}>Mở khóa</button> : null}<div className={styles.candidateList}><span>Ứng viên</span>{candidateLoading ? <div className={styles.candidateLoading}><LoaderCircle size={16} className={styles.spin} />Đang kiểm tra…</div> : candidateRows.map((candidate) => { const lecturer = lecturers.find((item) => item.id === candidate.lecturer_id); const chosen = candidateCheck?.lecturerId === candidate.lecturer_id; return <button type="button" key={candidate.lecturer_id} className={`${styles.candidateRow} ${candidate.status === "ELIGIBLE" ? styles.candidateEligible : ""} ${chosen ? styles.candidateSelected : ""}`} onClick={() => semesterId && void api.checkAssignment(selectedClass.id, candidate.lecturer_id, semesterId).then((result) => setCandidateCheck({ lecturerId: candidate.lecturer_id, valid: result.valid, blocking_reasons: result.blocking_reasons })).catch(() => setCandidateCheck({ lecturerId: candidate.lecturer_id, valid: false, blocking_reasons: ["Không thể kiểm tra candidate"] }))}><span><strong>{lecturer?.name ?? `Giảng viên #${candidate.lecturer_id}`}</strong><small>{candidateReason(candidate.status)}</small></span><span>{candidate.status === "ELIGIBLE" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}</span></button>; })}</div>{candidateCheck ? <div className={candidateCheck.valid ? styles.assignmentCheckOk : styles.assignmentCheckError}>{candidateCheck.valid ? <><CheckCircle2 size={16} />Có thể phân công.</> : <><AlertCircle size={16} />{candidateCheck.blocking_reasons.map(candidateReason).join(" · ")}</>} {candidateCheck.valid ? <div><button type="button" className={styles.secondaryButton} onClick={() => onManual(selectedClass.id, candidateCheck.lecturerId, false)}>Phân công</button><button type="button" className={styles.primaryButton} onClick={() => onManual(selectedClass.id, candidateCheck.lecturerId, true)}>Phân công & khóa</button></div> : null}</div> : null}</aside> : null}
    </div>
    <div className={styles.stickyContinue}><span>Các thay đổi thủ công được kiểm tra với backend trước khi lưu.</span><button type="button" className={styles.primaryButton} onClick={onNext}>Rà soát để xuất<ArrowRight size={16} /></button></div>
  </section>;
}

function ExportReadiness({ metrics, problems, semesterId, finalReady }: { metrics: DashboardMetrics; problems: Problem[]; semesterId?: number; finalReady: boolean }) {
  const critical = problems.filter((item) => item.severity === "critical");
  return <div className={styles.exportReadiness}><div className={styles.flatPanel}><span className={styles.eyebrow}>DRAFT EXPORT</span><strong>Luôn giữ nguyên cấu trúc file nguồn</strong><p>Chỉ cập nhật ô giảng viên trong bản copy; các ô và thứ tự dòng khác được bảo toàn.</p><a className={styles.primaryButton} href={api.exportUrl("draft", semesterId)}><FileSpreadsheet size={17} />Xuất Draft Excel</a></div><div className={styles.flatPanel}><span className={styles.eyebrow}>FINAL EXPORT</span><strong>{finalReady ? "Sẵn sàng xuất Final" : "Final export chưa sẵn sàng"}</strong><p>{finalReady ? "Không còn điều kiện blocking theo dữ liệu backend." : `${critical.length} vấn đề nghiêm trọng · ${metrics.unassigned_classes} TeachingGroup chưa phân.`}</p>{!finalReady && critical.length ? <ul>{critical.map((item) => <li key={`${item.code}-${item.entity_id}`}>{item.message}</li>)}</ul> : null}{finalReady ? <a className={styles.primaryButton} href={api.exportUrl("final", semesterId)}><Download size={17} />Xuất Final Excel</a> : <button type="button" className={styles.secondaryButton} disabled><Lock size={16} />Cần xử lý trước khi xuất</button>}</div></div>;
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
    <div className={styles.workspaceGrid}><div className={styles.calendarPanel}><div className={styles.panelHeader}><div><span>XEM TRƯỚC KẾT QUẢ</span><strong>Thời khóa biểu theo giảng viên</strong></div><select value={selectedLecturer} onChange={(event) => setSelectedLecturer(event.target.value)}><option value="">Toàn bộ giảng viên</option>{lecturers.map((name) => <option key={name}>{name}</option>)}</select></div><CalendarPreview classes={events} /></div><aside className={styles.constraintEditor}><div className={styles.panelHeader}><div><span>RÀNG BUỘC MỚI</span><strong>Chỉnh và xem trước</strong></div><Settings2 size={18} /></div><label className={styles.field}><span>Tên ràng buộc</span><input value={draftName} onChange={(event) => setDraftName(event.target.value)} /></label><label className={styles.field}><span>Giảng viên</span><select value={draftLecturerId} onChange={(event) => setDraftLecturerId(event.target.value)}><option value="">Chọn giảng viên…</option>{lecturerOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><div className={styles.inlineFields}><label className={styles.field}><span>Ngày</span><select value={draftWeekday} onChange={(event) => setDraftWeekday(event.target.value)}>{[2, 3, 4, 5, 6, 7, 8].map((day) => <option key={day} value={day}>{day === 8 ? "Chủ Nhật" : `Thứ ${day}`}</option>)}</select></label><label className={styles.field}><span>Khung tiết</span><select value={draftBlock} onChange={(event) => setDraftBlock(event.target.value)}>{["1-3", "4-6", "7-9", "10-12"].map((block) => <option key={block}>{block}</option>)}</select></label></div><div className={styles.inlineFields}><label className={styles.field}><span>Mức độ</span><select value={draftHardness} onChange={(event) => setDraftHardness(event.target.value as "hard" | "soft")}><option value="soft">Ưu tiên mềm</option><option value="hard">Bắt buộc</option></select></label><label className={styles.field}><span>Trọng số</span><input type="number" min="0" max="1" step="0.1" disabled={draftHardness === "hard"} value={draftHardness === "hard" ? 1 : draftWeight} onChange={(event) => setDraftWeight(Number(event.target.value))} /></label></div><div className={styles.livePreview}><span>XEM TRƯỚC REALTIME</span><strong>{draftName || "Ràng buộc chưa có tên"}</strong><p>{draftLecturerId ? `${affectedClasses.length} lớp hiện tại chạm khung Thứ ${draftWeekday}, tiết ${draftBlock}. ` : "Chọn giảng viên để xem lớp bị tác động. "}{draftHardness === "hard" ? "Solver bắt buộc tránh khung này." : `Solver ưu tiên tránh với trọng số ${draftWeight.toFixed(1)}.`}</p></div><button type="button" className={styles.secondaryButton} disabled={!draftName.trim() || !draftLecturerId || busy === "new-constraint"} onClick={() => onCreate({ name: draftName, raw_text: `${draftName} · Thứ ${draftWeekday}, tiết ${draftBlock}`, constraint_type: "unavailable", lecturer_id: Number(draftLecturerId), hardness: draftHardness, weight: draftHardness === "hard" ? 1 : draftWeight, target: { weekday: Number(draftWeekday), periods: Array.from({ length: draftEnd - draftStart + 1 }, (_, index) => draftStart + index) }, confirmed: true })}><Plus size={16} />Thêm vào phương án</button></aside></div>
    <div className={styles.stickyContinue}><span>Mỗi lần chạy tạo một phương án mới; các phân công đã khóa được giữ nguyên.</span><button type="button" className={styles.primaryButton} disabled={!assigned} onClick={onNext}>Rà soát để xuất<ArrowRight size={16} /></button></div>
  </section>;
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: "blue" | "violet" | "green" | "red" }) {
  return <div className={styles.metric}><span className={`${styles.metricMark} ${styles[tone]}`} /><div><small>{label}</small><strong>{value}</strong><span>{detail}</span></div></div>;
}

function CalendarPreview({ classes }: { classes: ClassItem[] }) {
  const days = [2, 3, 4, 5, 6, 7];
  const blocks = [[1, 3], [4, 6], [7, 9], [10, 12]];
  return <div className={styles.calendarWrap}><div className={styles.calendarGrid}><div className={styles.calendarCorner}>BLOCK</div>{days.map((day) => <div className={styles.calendarDay} key={day}>THỨ {day}</div>)}{blocks.flatMap(([start, end]) => [<div className={styles.calendarTime} key={`time-${start}`}>Tiết {start}–{end}</div>, ...days.map((day) => { const item = classes.find((candidate) => candidate.sessions.some((session) => session.weekday === day && session.start_period <= end && session.end_period >= start)); return <div className={styles.calendarCell} key={`${day}-${start}`}>{item ? <article><strong>{item.course_name}</strong><span>{item.class_code}</span><small>{item.lecturer ?? "Chưa phân công"}</small></article> : null}</div>; })])}</div></div>;
}

function PublishView({ metrics, problems, semesterId }: { metrics: DashboardMetrics; problems: Problem[]; semesterId?: number }) {
  const critical = problems.filter((item) => item.severity === "critical");
  const ready = metrics.classes > 0 && metrics.unassigned_classes === 0 && critical.length === 0 && ["optimal", "feasible"].includes(metrics.optimization_status);
  return <section className={styles.viewEnter}>
    <PageHeading eyebrow="BƯỚC 06" title="Chốt và xuất kết quả" text="Một bản phát hành giữ nguyên dữ liệu nguồn, ràng buộc và phương án đã được trưởng bộ môn phê duyệt." />
    <div className={styles.publishCard}><span className={`${styles.publishSeal} ${ready ? styles.sealReady : ""}`}>{ready ? <CheckCircle2 size={28} /> : <AlertCircle size={28} />}</span><div><strong>{ready ? "Phương án đã sẵn sàng công bố" : "Final export chưa sẵn sàng"}</strong><p>{ready ? "Không còn lớp chưa phân và không có vấn đề blocking." : `${critical.length} vấn đề nghiêm trọng · ${metrics.unassigned_classes} lớp chưa phân. Hãy quay lại Problem Log để xử lý.`}</p></div></div>
    <div className={styles.exportGrid}><a className={styles.exportCard} href={api.exportUrl("draft", semesterId)}><FileSpreadsheet size={22} /><span><strong>Draft Excel</strong><small>Bản copy để đối soát, cho phép còn lớp chưa phân</small></span><Download size={17} /></a>{ready ? <a className={styles.exportCard} href={api.exportUrl("final", semesterId)}><CheckCircle2 size={22} /><span><strong>Final Excel</strong><small>Phương án đã qua readiness check</small></span><Download size={17} /></a> : <button type="button" className={styles.exportCard} disabled><Lock size={22} /><span><strong>Final Excel bị khóa</strong><small>Giải quyết các vấn đề blocking trước</small></span><Lock size={17} /></button>}</div>
  </section>;
}
