"use client";

import {
  AlertTriangle,
  BarChart3,
  BookOpenCheck,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Database,
  Download,
  FileSpreadsheet,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { HuceWordmark } from "@/src/components/brand/huce-wordmark";
import { api } from "@/src/services/api";
import type { ClassItem, Constraint, DashboardMetrics, ValidationIssue } from "@/src/types/api";

import styles from "./dashboard.module.css";

type View = "overview" | "data" | "constraints" | "optimize" | "results" | "calendar" | "conflicts";

const navigation: { id: View; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Tổng quan", icon: LayoutDashboard },
  { id: "data", label: "Dữ liệu đầu vào", icon: Database },
  { id: "constraints", label: "Ràng buộc", icon: Settings2 },
  { id: "optimize", label: "Tự động phân công", icon: Sparkles },
  { id: "results", label: "Kết quả phân công", icon: BookOpenCheck },
  { id: "calendar", label: "Thời khóa biểu", icon: CalendarDays },
  { id: "conflicts", label: "Xung đột", icon: AlertTriangle },
];

const defaultMetrics: DashboardMetrics = {
  classes: 0,
  locked_classes: 0,
  unassigned_classes: 0,
  merged_suggestions: 0,
  lecturers: 0,
  validation_errors: 0,
  optimization_status: "not_run",
  optimization_score: null,
};

function StatusBadge({ tone, children }: { tone: "success" | "warning" | "danger" | "neutral"; children: React.ReactNode }) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className={styles.emptyState}>
      <span className={styles.emptyIcon}><FileSpreadsheet size={24} /></span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

export function DashboardApp() {
  const [view, setView] = useState<View>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [metrics, setMetrics] = useState(defaultMetrics);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [constraintOpen, setConstraintOpen] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashboard, classRows, constraintRows, issueRows] = await Promise.all([
        api.dashboard(),
        api.classes(),
        api.constraints(),
        api.conflicts(),
      ]);
      setMetrics(dashboard);
      setClasses(classRows);
      setConstraints(constraintRows);
      setIssues(issueRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể tải dữ liệu.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function runAction(name: string, action: () => Promise<unknown>, success: string) {
    setBusy(name);
    setError(null);
    try {
      await action();
      setNotice(success);
      await loadAll();
      window.setTimeout(() => setNotice(null), 3500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Thao tác thất bại.");
    } finally {
      setBusy(null);
    }
  }

  const currentLabel = navigation.find((item) => item.id === view)?.label ?? "Tổng quan";

  return (
    <div className={`${styles.app} ${collapsed ? styles.isCollapsed : ""}`}>
      <aside className={`${styles.sidebar} ${drawerOpen ? styles.drawerOpen : ""}`}>
        <div className={styles.brandRow}>
          <HuceWordmark compact={collapsed} />
          <button className={styles.iconButtonDesktop} onClick={() => setCollapsed((value) => !value)} aria-label="Thu gọn sidebar">
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
          <button className={styles.drawerClose} onClick={() => setDrawerOpen(false)} aria-label="Đóng menu"><X size={20} /></button>
        </div>
        <nav className={styles.navigation} aria-label="Điều hướng chính">
          <span className={styles.navEyebrow}>{collapsed ? "•••" : "Không gian làm việc"}</span>
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`${styles.navItem} ${view === item.id ? styles.navActive : ""}`}
                title={collapsed ? item.label : undefined}
                onClick={() => {
                  setView(item.id);
                  setDrawerOpen(false);
                }}
              >
                <Icon size={19} strokeWidth={1.8} />
                {!collapsed && <span>{item.label}</span>}
                {!collapsed && item.id === "conflicts" && metrics.validation_errors > 0 && (
                  <span className={styles.navCount}>{metrics.validation_errors}</span>
                )}
              </button>
            );
          })}
        </nav>
        <div className={styles.sidebarFooter}>
          <div className={styles.semesterPill}>
            <span className={styles.liveDot} />
            {!collapsed && <span><small>Học kỳ hiện tại</small><strong>HK1 · 2026–2027</strong></span>}
          </div>
          {!collapsed && <p>Dữ liệu được lưu cục bộ và không đưa lên Git.</p>}
        </div>
      </aside>
      {drawerOpen && <button className={styles.scrim} aria-label="Đóng menu" onClick={() => setDrawerOpen(false)} />}

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.topbarTitle}>
            <button className={styles.mobileMenu} onClick={() => setDrawerOpen(true)} aria-label="Mở menu"><Menu size={21} /></button>
            <div>
              <span className={styles.breadcrumb}>HUCE / Bộ môn Toán học</span>
              <h1>{currentLabel}</h1>
            </div>
          </div>
          <div className={styles.topbarActions}>
            <button className={styles.iconButton} onClick={() => void loadAll()} aria-label="Làm mới dữ liệu">
              <RefreshCw size={18} className={loading ? styles.spin : ""} />
            </button>
            <a className={styles.secondaryButton} href={api.exportUrl}>
              <Download size={17} /> <span>Xuất Excel</span>
            </a>
            <div className={styles.avatar} title="Quản trị viên">GK</div>
          </div>
        </header>

        <div className={styles.content}>
          {notice && <div className={styles.notice}><CircleCheck size={18} />{notice}</div>}
          {error && (
            <div className={styles.errorBanner}>
              <AlertTriangle size={19} />
              <span><strong>Chưa thể hoàn tất.</strong>{error}</span>
              <button onClick={() => setError(null)}><X size={17} /></button>
            </div>
          )}
          {loading ? (
            <div className={styles.loadingState}><LoaderCircle className={styles.spin} /><span>Đang đồng bộ dữ liệu…</span></div>
          ) : (
            <>
              {view === "overview" && <Overview metrics={metrics} classes={classes} issues={issues} onNavigate={setView} />}
              {view === "data" && (
                <DataView
                  classes={classes}
                  query={query}
                  setQuery={setQuery}
                  busy={busy}
                  onImportLocal={() => runAction("import", api.importLocal, "Đã nhập và chuẩn hóa dữ liệu Excel.")}
                  onUpload={(files) => runAction("upload", () => api.upload(files), "Đã upload và chuẩn hóa workbook.")}
                />
              )}
              {view === "constraints" && (
                <ConstraintsView constraints={constraints} onCreate={() => setConstraintOpen(true)} />
              )}
              {view === "optimize" && (
                <OptimizeView
                  metrics={metrics}
                  busy={busy}
                  onRun={(merged) => runAction("optimize", () => api.optimize(merged), "Đã tạo phương án phân công mới.")}
                />
              )}
              {view === "results" && <ResultsView classes={classes} query={query} setQuery={setQuery} />}
              {view === "calendar" && <CalendarView classes={classes} />}
              {view === "conflicts" && <ConflictsView issues={issues} />}
            </>
          )}
        </div>
      </main>

      {constraintOpen && (
        <ConstraintDialog
          busy={busy}
          onClose={() => setConstraintOpen(false)}
          onSubmit={(payload) =>
            runAction("constraint", () => api.createConstraint(payload), "Đã thêm ràng buộc.")
              .then(() => setConstraintOpen(false))
          }
        />
      )}
    </div>
  );
}

function Overview({
  metrics,
  classes,
  issues,
  onNavigate,
}: {
  metrics: DashboardMetrics;
  classes: ClassItem[];
  issues: ValidationIssue[];
  onNavigate: (view: View) => void;
}) {
  const completion = metrics.classes ? Math.round(((metrics.classes - metrics.unassigned_classes) / metrics.classes) * 100) : 0;
  const cards = [
    { label: "Lớp học phần", value: metrics.classes, detail: `${metrics.locked_classes} lớp đã khóa`, icon: BookOpenCheck, tone: "blue" },
    { label: "Giảng viên", value: metrics.lecturers, detail: "Đã nhận diện trong dữ liệu", icon: Users, tone: "violet" },
    { label: "Chưa phân công", value: metrics.unassigned_classes, detail: `${completion}% đã có người dạy`, icon: BarChart3, tone: "amber" },
    { label: "Lỗi nghiêm trọng", value: metrics.validation_errors, detail: metrics.validation_errors ? "Cần xử lý trước tối ưu" : "Dữ liệu sẵn sàng", icon: ShieldCheck, tone: metrics.validation_errors ? "red" : "green" },
  ];
  return (
    <div className={styles.viewStack}>
      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>Hệ thống phân công giảng dạy</span>
          <h2>Một nơi để biến dữ liệu Excel thành lịch dạy khả thi.</h2>
          <p>Kiểm tra dữ liệu, cân bằng tải và tôn trọng nguyện vọng — với mọi quyết định đều có thể truy vết.</p>
        </div>
        <div className={styles.heroActions}>
          <button className={styles.primaryButton} onClick={() => onNavigate("optimize")}><Play size={17} fill="currentColor" />Bắt đầu phân công</button>
          <button className={styles.ghostButton} onClick={() => onNavigate("data")}>Kiểm tra dữ liệu<ChevronRight size={17} /></button>
        </div>
      </section>
      <section className={styles.metricsGrid}>
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <article className={styles.metricCard} key={card.label}>
              <div className={`${styles.metricIcon} ${styles[card.tone]}`}><Icon size={20} /></div>
              <div><span>{card.label}</span><strong>{card.value.toLocaleString("vi-VN")}</strong><small>{card.detail}</small></div>
            </article>
          );
        })}
      </section>
      <section className={styles.twoColumns}>
        <article className={styles.card}>
          <div className={styles.cardHeader}>
            <div><span className={styles.cardEyebrow}>Tiến độ</span><h3>Trạng thái phân công</h3></div>
            <StatusBadge tone={metrics.optimization_status.includes("optimal") ? "success" : "neutral"}>
              {metrics.optimization_status === "not_run" ? "Chưa chạy" : metrics.optimization_status}
            </StatusBadge>
          </div>
          <div className={styles.progressBlock}>
            <div className={styles.progressLabel}><span>Lớp đã có giảng viên</span><strong>{completion}%</strong></div>
            <div className={styles.progressTrack}><span style={{ width: `${completion}%` }} /></div>
          </div>
          <div className={styles.miniStats}>
            <div><strong>{metrics.locked_classes}</strong><span>Đã khóa</span></div>
            <div><strong>{metrics.merged_suggestions}</strong><span>Nhóm ghép đề xuất</span></div>
            <div><strong>{metrics.unassigned_classes}</strong><span>Cần tối ưu</span></div>
          </div>
        </article>
        <article className={styles.card}>
          <div className={styles.cardHeader}>
            <div><span className={styles.cardEyebrow}>Cần chú ý</span><h3>Kiểm tra gần đây</h3></div>
            <button className={styles.textButton} onClick={() => onNavigate("conflicts")}>Xem tất cả</button>
          </div>
          <div className={styles.activityList}>
            {issues.length ? issues.slice(0, 3).map((issue) => (
              <div className={styles.activityItem} key={issue.id}>
                <span className={issue.severity === "error" ? styles.activityDanger : styles.activityWarn}><AlertTriangle size={16} /></span>
                <div><strong>{issue.message}</strong><small>{issue.source_file} · dòng {issue.source_row ?? "—"}</small></div>
              </div>
            )) : (
              <div className={styles.cleanState}><CircleCheck size={21} /><span><strong>Không có lỗi nghiêm trọng</strong><small>{classes.length} lớp đã qua kiểm tra cấu trúc.</small></span></div>
            )}
          </div>
        </article>
      </section>
    </div>
  );
}

function DataView({
  classes,
  query,
  setQuery,
  busy,
  onImportLocal,
  onUpload,
}: {
  classes: ClassItem[];
  query: string;
  setQuery: (value: string) => void;
  busy: string | null;
  onImportLocal: () => void;
  onUpload: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const filtered = classes.filter((item) =>
    `${item.course_code} ${item.course_name} ${item.class_code} ${item.lecturer ?? ""}`.toLocaleLowerCase("vi")
      .includes(query.toLocaleLowerCase("vi")),
  );
  return (
    <div className={styles.viewStack}>
      <section className={styles.sectionHeading}>
        <div><span className={styles.eyebrow}>Excel ingestion</span><h2>Dữ liệu đầu vào</h2><p>Upload lịch học và nguyện vọng. File gốc được giữ nguyên để truy vết.</p></div>
        <button className={styles.secondaryButton} onClick={onImportLocal} disabled={!!busy}>
          {busy === "import" ? <LoaderCircle className={styles.spin} size={17} /> : <Database size={17} />}Nhập dữ liệu mẫu cục bộ
        </button>
      </section>
      <section
        className={styles.dropzone}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          onUpload(Array.from(event.dataTransfer.files).filter((file) => /\.(xlsx?|xls)$/i.test(file.name)));
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".xls,.xlsx"
          hidden
          onChange={(event) => onUpload(Array.from(event.target.files ?? []))}
        />
        <span className={styles.dropIcon}>{busy === "upload" ? <LoaderCircle className={styles.spin} /> : <UploadCloud />}</span>
        <div><strong>Thả file Excel vào đây</strong><p>Hỗ trợ `.xls` và `.xlsx` · lịch học, nguyện vọng hoặc phân công cũ</p></div>
        <button className={styles.ghostButton} onClick={() => inputRef.current?.click()} disabled={!!busy}>Chọn file</button>
      </section>
      <section className={styles.card}>
        <div className={styles.tableToolbar}>
          <div><h3>Dữ liệu đã chuẩn hóa</h3><span>{classes.length} lớp học phần</span></div>
          <label className={styles.searchBox}><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm môn, lớp, giảng viên…" /></label>
        </div>
        <ClassTable items={filtered.slice(0, 100)} />
      </section>
    </div>
  );
}

function ClassTable({ items }: { items: ClassItem[] }) {
  if (!items.length) return <EmptyState title="Chưa có dữ liệu lớp" text="Upload workbook hoặc nhập dữ liệu cục bộ để bắt đầu." />;
  return (
    <div className={styles.tableWrap}>
      <table>
        <thead><tr><th>Mã lớp</th><th>Môn học</th><th>Lịch học</th><th>Giảng viên</th><th>Trạng thái</th></tr></thead>
        <tbody>{items.map((item) => (
          <tr key={item.id}>
            <td><strong>{item.class_code}</strong><small>{item.course_code}</small></td>
            <td><span className={styles.cellTitle}>{item.course_name}</span><small>{item.credits} tín chỉ · {item.sessions.length} buổi</small></td>
            <td>{item.sessions.slice(0, 2).map((session, index) => <span className={styles.scheduleLine} key={index}>T{session.weekday} · {session.start_period}–{session.end_period} · {session.room || "Chưa có phòng"}</span>)}</td>
            <td>{item.lecturer ?? <span className={styles.muted}>Chưa phân công</span>}</td>
            <td><div className={styles.statusStack}>
              {item.locked_assignment && <StatusBadge tone="success">Đã khóa</StatusBadge>}
              {item.merged_group_id && <StatusBadge tone="warning">{item.merged_group_id}</StatusBadge>}
              {!item.locked_assignment && !item.merged_group_id && <StatusBadge tone="neutral">Lớp đơn</StatusBadge>}
            </div></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ConstraintsView({ constraints, onCreate }: { constraints: Constraint[]; onCreate: () => void }) {
  return (
    <div className={styles.viewStack}>
      <section className={styles.sectionHeading}>
        <div><span className={styles.eyebrow}>Quy tắc phân công</span><h2>Ràng buộc</h2><p>Phân biệt quy tắc bắt buộc và nguyện vọng có trọng số từ 0 đến 1.</p></div>
        <button className={styles.primaryButton} onClick={onCreate}><Plus size={18} />Thêm ràng buộc</button>
      </section>
      <div className={styles.infoStrip}><ShieldCheck size={19} /><span><strong>Ràng buộc cứng</strong> không được vi phạm. <strong>Ràng buộc mềm</strong> có thể vi phạm khi cần và được tính vào điểm phạt.</span></div>
      <section className={styles.card}>
        <div className={styles.tableToolbar}><div><h3>Danh sách quy tắc</h3><span>{constraints.length} ràng buộc đã nhận diện</span></div></div>
        {constraints.length ? <div className={styles.constraintList}>{constraints.map((item) => (
          <article className={styles.constraintRow} key={item.id}>
            <span className={`${styles.constraintIcon} ${item.hardness === "hard" ? styles.hard : styles.soft}`}><Settings2 size={18} /></span>
            <div className={styles.constraintCopy}><div><strong>{item.name}</strong><StatusBadge tone={item.hardness === "hard" ? "danger" : "warning"}>{item.hardness === "hard" ? "Cứng" : "Mềm"}</StatusBadge>{!item.confirmed && <StatusBadge tone="neutral">Cần xác nhận</StatusBadge>}</div><p>{item.raw_text || `${item.constraint_type} · ${item.lecturer ?? "Toàn bộ giảng viên"}`}</p></div>
            <div className={styles.weight}><small>Trọng số</small><strong>{item.weight.toFixed(1)}</strong></div>
          </article>
        ))}</div> : <EmptyState title="Chưa có ràng buộc" text="Nhập nguyện vọng hoặc thêm một quy tắc mới." />}
      </section>
    </div>
  );
}

function OptimizeView({ metrics, busy, onRun }: { metrics: DashboardMetrics; busy: string | null; onRun: (merged: boolean) => void }) {
  const [merged, setMerged] = useState(false);
  return (
    <div className={styles.viewStack}>
      <section className={styles.optimizerHero}>
        <span className={styles.optimizerIcon}><Sparkles /></span>
        <div><span className={styles.eyebrow}>CP-SAT optimizer</span><h2>Tạo phương án cân bằng và có thể giải thích.</h2><p>Hệ thống giữ nguyên phân công đã khóa, loại trừ lịch trùng và tối thiểu hóa vi phạm nguyện vọng mềm.</p></div>
        <button className={styles.primaryButton} disabled={!!busy || metrics.validation_errors > 0} onClick={() => onRun(merged)}>
          {busy === "optimize" ? <LoaderCircle className={styles.spin} size={18} /> : <Play size={18} fill="currentColor" />}
          {busy === "optimize" ? "Đang tối ưu…" : "Chạy phân công"}
        </button>
      </section>
      <section className={styles.optimizerGrid}>
        <article className={styles.card}>
          <div className={styles.cardHeader}><div><span className={styles.cardEyebrow}>Phạm vi chạy</span><h3>Cấu hình phương án</h3></div></div>
          <div className={styles.optionList}>
            <label className={styles.checkRow}><input type="checkbox" checked readOnly /><span><strong>Giữ phân công đã khóa</strong><small>{metrics.locked_classes} lớp sẽ không bị thay đổi.</small></span></label>
            <label className={styles.checkRow}><input type="checkbox" checked readOnly /><span><strong>Không trùng lịch giảng viên</strong><small>Kiểm tra thứ, tiết, giai đoạn và tuần hoạt động.</small></span></label>
            <label className={styles.checkRow}><input type="checkbox" checked={merged} onChange={(event) => setMerged(event.target.checked)} /><span><strong>Xác nhận nhóm lớp ghép đề xuất</strong><small>{metrics.merged_suggestions} nhóm dùng chung một giảng viên.</small></span></label>
          </div>
        </article>
        <article className={styles.readinessCard}>
          <div className={styles.scoreRing} style={{ "--score": metrics.validation_errors ? "35%" : "100%" } as React.CSSProperties}><strong>{metrics.validation_errors ? "Chờ" : "Sẵn sàng"}</strong><small>Dữ liệu</small></div>
          <div className={styles.readinessRows}>
            <span><CircleCheck size={17} />{metrics.classes} lớp đã nhập</span>
            <span><CircleCheck size={17} />{metrics.lecturers} giảng viên khả dụng</span>
            <span className={metrics.validation_errors ? styles.dangerText : ""}><AlertTriangle size={17} />{metrics.validation_errors} lỗi nghiêm trọng</span>
          </div>
        </article>
      </section>
      {metrics.validation_errors > 0 && <div className={styles.errorBanner}><AlertTriangle size={19} /><span><strong>Chưa thể chạy tối ưu.</strong>Hãy xử lý các lỗi nghiêm trọng trong mục Xung đột trước.</span></div>}
    </div>
  );
}

function ResultsView({ classes, query, setQuery }: { classes: ClassItem[]; query: string; setQuery: (value: string) => void }) {
  const assigned = classes.filter((item) => item.lecturer);
  const filtered = assigned.filter((item) => `${item.class_code} ${item.course_name} ${item.lecturer}`.toLocaleLowerCase("vi").includes(query.toLocaleLowerCase("vi")));
  return (
    <div className={styles.viewStack}>
      <section className={styles.sectionHeading}>
        <div><span className={styles.eyebrow}>Kết quả</span><h2>Phân công giảng dạy</h2><p>Toàn bộ buổi của một lớp luôn thuộc cùng một giảng viên.</p></div>
        <a className={styles.primaryButton} href={api.exportUrl}><Download size={18} />Tải file Excel</a>
      </section>
      <section className={styles.card}>
        <div className={styles.tableToolbar}><div><h3>Danh sách đã phân công</h3><span>{assigned.length}/{classes.length} lớp</span></div><label className={styles.searchBox}><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm nhanh…" /></label></div>
        <ClassTable items={filtered} />
      </section>
    </div>
  );
}

function CalendarView({ classes }: { classes: ClassItem[] }) {
  const assigned = classes.filter((item) => item.lecturer);
  const lecturers = Array.from(new Set(assigned.map((item) => item.lecturer as string))).sort();
  const [selected, setSelected] = useState(lecturers[0] ?? "");
  const days = [2, 3, 4, 5, 6, 7, 8];
  const events = assigned.filter((item) => item.lecturer === selected).flatMap((item) => item.sessions.map((session) => ({ item, session })));
  return (
    <div className={styles.viewStack}>
      <section className={styles.sectionHeading}>
        <div><span className={styles.eyebrow}>Lịch tuần</span><h2>Thời khóa biểu giảng viên</h2><p>Xem nhanh lịch đã phân công theo thứ và khung tiết.</p></div>
        <label className={styles.selectBox}><Users size={17} /><select value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Chọn giảng viên</option>{lecturers.map((name) => <option key={name}>{name}</option>)}</select><ChevronDown size={16} /></label>
      </section>
      <section className={styles.calendarCard}>
        <div className={styles.calendarHeader}>{days.map((day) => <div key={day}><span>{day === 8 ? "Chủ Nhật" : `Thứ ${day}`}</span><small>{events.filter((event) => event.session.weekday === day).length} buổi</small></div>)}</div>
        <div className={styles.calendarGrid}>{days.map((day) => <div className={styles.dayColumn} key={day}>
          {events.filter((event) => event.session.weekday === day).map(({ item, session }, index) => (
            <article className={styles.calendarEvent} key={`${item.id}-${index}`}>
              <span>Tiết {session.start_period}–{session.end_period}</span><strong>{item.course_name}</strong><small>{item.class_code} · {session.room}</small>
            </article>
          ))}
        </div>)}</div>
        {!selected && <EmptyState title="Chọn một giảng viên" text="Lịch tuần sẽ xuất hiện ở đây." />}
      </section>
    </div>
  );
}

function ConflictsView({ issues }: { issues: ValidationIssue[] }) {
  return (
    <div className={styles.viewStack}>
      <section className={styles.sectionHeading}><div><span className={styles.eyebrow}>Data quality</span><h2>Xung đột và lỗi dữ liệu</h2><p>Mỗi lỗi giữ vị trí nguồn và gợi ý xử lý, không tự động đoán giá trị.</p></div><StatusBadge tone={issues.length ? "danger" : "success"}>{issues.length ? `${issues.length} vấn đề` : "Sạch"}</StatusBadge></section>
      <section className={styles.card}>
        {issues.length ? <div className={styles.issueList}>{issues.map((issue) => (
          <article className={styles.issueRow} key={issue.id}>
            <span className={issue.severity === "error" ? styles.issueDanger : styles.issueWarning}><AlertTriangle size={19} /></span>
            <div><div><strong>{issue.message}</strong><StatusBadge tone={issue.severity === "error" ? "danger" : "warning"}>{issue.severity}</StatusBadge></div><p>{issue.suggestion}</p><small>{issue.source_file} · dòng {issue.source_row ?? "—"} · {issue.code}</small></div>
          </article>
        ))}</div> : <div className={styles.successEmpty}><CircleCheck size={30} /><strong>Dữ liệu không có lỗi nghiêm trọng</strong><p>Bạn có thể chuyển sang bước tự động phân công.</p></div>}
      </section>
    </div>
  );
}

function ConstraintDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: string | null;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [hardness, setHardness] = useState<"soft" | "hard">("soft");
  const [weight, setWeight] = useState(0.8);
  const [name, setName] = useState("");
  const [rawText, setRawText] = useState("");
  return (
    <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <div className={styles.dialogHeader}><div><span className={styles.cardEyebrow}>Quy tắc mới</span><h3 id="dialog-title">Thêm ràng buộc</h3></div><button className={styles.iconButton} onClick={onClose}><X size={18} /></button></div>
        <div className={styles.formStack}>
          <label><span>Tên ràng buộc</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ví dụ: Cô Hồng không dạy thứ 2" /></label>
          <label><span>Mô tả nguyên văn</span><textarea value={rawText} onChange={(event) => setRawText(event.target.value)} rows={4} placeholder="Nhập nội dung để người dùng khác có thể đối chiếu…" /></label>
          <fieldset><legend>Mức độ</legend><div className={styles.segmented}><button className={hardness === "soft" ? styles.segmentActive : ""} onClick={() => setHardness("soft")}>Mềm</button><button className={hardness === "hard" ? styles.segmentActive : ""} onClick={() => setHardness("hard")}>Cứng</button></div></fieldset>
          <label className={styles.rangeLabel}><span><span>Trọng số</span><strong>{weight.toFixed(1)}</strong></span><input type="range" min="0" max="1" step="0.1" value={weight} disabled={hardness === "hard"} onChange={(event) => setWeight(Number(event.target.value))} /></label>
        </div>
        <div className={styles.dialogFooter}><button className={styles.ghostButton} onClick={onClose}>Hủy</button><button className={styles.primaryButton} disabled={!name.trim() || !!busy} onClick={() => onSubmit({ name, raw_text: rawText, hardness, weight: hardness === "hard" ? 1 : weight, constraint_type: "manual", target: {}, confirmed: true })}>{busy === "constraint" ? <LoaderCircle className={styles.spin} size={17} /> : <Plus size={17} />}Thêm ràng buộc</button></div>
      </div>
    </div>
  );
}
