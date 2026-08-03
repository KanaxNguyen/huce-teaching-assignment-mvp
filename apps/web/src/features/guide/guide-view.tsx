import { Braces, CalendarCheck, CircleCheck, Cloud, FileInput, FileOutput, Settings2, Sparkles } from "lucide-react";

import { api } from "@/src/services/api";
import type { DashboardMetrics, ImportBatch, OptimizationRun } from "@/src/types/api";
import dashboardStyles from "@/src/features/dashboard/dashboard.module.css";

import styles from "./guide-view.module.css";

export function GuideView({ metrics, latestImport, latestRun }: { metrics: DashboardMetrics; latestImport: ImportBatch | null; latestRun: OptimizationRun | null }) {
  const steps = [
    { title: "Nạp ba file nguồn", text: "Lịch học, nguyện vọng và file mẫu cũ.", done: !!latestImport, icon: FileInput },
    { title: "Kiểm tra quy tắc", text: "Xác nhận ràng buộc mềm, cứng và trọng số.", done: metrics.validation_errors === 0 && metrics.classes > 0, icon: Settings2 },
    { title: "Chạy tối ưu", text: "Khóa phân công cũ và xác nhận 41 nhóm lớp ghép.", done: !!latestRun, icon: Sparkles },
    { title: "Kiểm tra lịch", text: "Đối chiếu giảng viên, seminar và xung đột cứng.", done: metrics.unassigned_classes === 0 && metrics.validation_errors === 0, icon: CalendarCheck },
    { title: "Xuất và kết nối", text: "Excel, Google Calendar, CSV và JSON API.", done: !!latestRun, icon: FileOutput },
  ];
  return (
    <div className={dashboardStyles.viewStack}>
      <section className={styles.hero}>
        <div><span className={dashboardStyles.eyebrow}>Bàn giao sản phẩm</span><h2>Quy trình vận hành MVP</h2><p>Một checklist ngắn để người phụ trách bộ môn có thể sử dụng app mà không cần kiến thức kỹ thuật.</p></div>
        <span className={styles.readyBadge}><CircleCheck size={20} /><strong>MVP sẵn sàng</strong><small>HK1 · 2026–2027</small></span>
      </section>
      <section className={styles.stepGrid}>
        {steps.map((step, index) => {
          const Icon = step.icon;
          return <article className={`${styles.step} ${step.done ? styles.done : ""}`} key={step.title}><span className={styles.number}>{index + 1}</span><span className={styles.stepIcon}><Icon size={19} /></span><div><strong>{step.title}</strong><p>{step.text}</p></div>{step.done && <CircleCheck className={styles.check} size={18} />}</article>;
        })}
      </section>
      <section className={styles.twoColumns}>
        <article className={dashboardStyles.card}>
          <div className={dashboardStyles.cardHeader}><div><span className={dashboardStyles.cardEyebrow}>Kết nối dữ liệu</span><h3>Đầu ra tích hợp</h3></div><Braces size={20} /></div>
          <div className={styles.links}>
            <a href={api.exportUrl}><FileOutput size={17} /><span><strong>Workbook hoàn chỉnh</strong><small>Biểu mẫu Excel 7 sheet</small></span></a>
            <a href={api.calendarUrl()}><CalendarCheck size={17} /><span><strong>iCalendar (.ics)</strong><small>Google, Outlook, Apple Calendar</small></span></a>
            <a href={api.csvUrl()}><FileOutput size={17} /><span><strong>Dữ liệu CSV</strong><small>Chuyển cho khoa hoặc phòng đào tạo</small></span></a>
            <a href={api.jsonUrl()}><Braces size={17} /><span><strong>JSON API</strong><small>Đồng bộ với phần mềm khác</small></span></a>
          </div>
        </article>
        <article className={dashboardStyles.card}>
          <div className={dashboardStyles.cardHeader}><div><span className={dashboardStyles.cardEyebrow}>Triển khai</span><h3>Sẵn sàng đưa vào dùng</h3></div><Cloud size={20} /></div>
          <div className={styles.deployList}>
            <span><CircleCheck size={16} /><strong>GitHub</strong><small>Mã nguồn, CI và kiểm thử tự động</small></span>
            <span><CircleCheck size={16} /><strong>Docker</strong><small>Frontend và API tách dịch vụ</small></span>
            <span><CircleCheck size={16} /><strong>Render Blueprint</strong><small>Có ổ lưu trữ database và file xuất</small></span>
            <span><CircleCheck size={16} /><strong>Sao lưu</strong><small>Workbook thật không được commit lên Git</small></span>
          </div>
        </article>
      </section>
    </div>
  );
}
