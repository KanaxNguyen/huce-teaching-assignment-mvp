import styles from './semester-workflow.module.css';

type Props = { summary: Record<string, unknown> | null; score: number | null };
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}
function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
function display(value: unknown): string {
  const n = number(value);
  return n === null ? 'N/A' : n.toLocaleString('vi-VN', {maximumFractionDigits: 6});
}
export function RunMetricsPanel({summary, score}: Props) {
  const experiment = record(summary?.experiment);
  const parts = record(experiment.objective_components);
  const configuration = record(experiment.configuration);
  const bound = number(experiment.best_objective_bound);
  const gap = score !== null && bound !== null ? Math.abs(score - bound) / Math.max(1, Math.abs(score)) : null;
  return <section className={styles.flatPanel} aria-label="Metric phiên bản phân công">
    <h3>Metric phiên bản phân công</h3>
    {summary?.solution_origin === 'MANUAL' ? <p>Phiên bản chỉnh thủ công. Chưa chạy solver lại; không có objective, thời gian hay chứng nhận tối ưu mới.</p> : null}
    {!Object.keys(experiment).length ? <p>Phiên bản này chưa có metric solver. Giá trị thiếu được ghi N/A.</p> : null}
    <dl>
      <dt>Tổng objective</dt><dd>{display(score)}</dd>
      <dt>Phạt lớp chưa phân công</dt><dd>{display(parts.unassigned)}</dd>
      <dt>Phạt giảng viên chưa có lớp</dt><dd>{display(parts.zero_assigned_lecturers)}</dd>
      <dt>Phạt chênh lệch tải</dt><dd>{display(parts.workload_disparity)}</dd>
      <dt>Phạt nguyện vọng mềm</dt><dd>{display(parts.soft_preferences)}</dd>
      <dt>Best bound</dt><dd>{display(bound)}</dd>
      <dt>Gap: |objective − bound| / max(1, |objective|)</dt><dd>{display(gap)}</dd>
      <dt>Solver wall time (giây)</dt><dd>{display(experiment.solver_wall_time_seconds)}</dd>
      <dt>Dựng mô hình (giây)</dt><dd>{display(experiment.model_build_seconds)}</dd>
      <dt>Toàn hàm solver, gồm lưu DB (giây)</dt><dd>{display(experiment.solver_pipeline_seconds)}</dd>
      <dt>Giới hạn thời gian / workers / seed</dt><dd>{display(configuration.max_time_in_seconds)} / {display(configuration.num_search_workers)} / {display(configuration.random_seed)}</dd>
    </dl>
    <p>Phạt mềm bằng 0 chỉ phản ánh các quy tắc đã áp dụng. OPTIMAL không đồng nghĩa tất cả lớp đã được giao.</p>
  </section>;
}
