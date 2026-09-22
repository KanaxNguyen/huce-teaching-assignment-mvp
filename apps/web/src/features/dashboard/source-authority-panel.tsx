"use client";
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/src/services/api';
import type { Lecturer, SourceIssue, SourcePreview, SourceState, SourceRole } from '@/src/types/api';
import styles from './semester-workflow.module.css';

function describeMeeting(meeting: Record<string, unknown> | null) {
  if (!meeting) return 'Không có';
  const periods = Array.isArray(meeting.period) ? meeting.period.join('–') : '';
  const weeks = Array.isArray(meeting.week_mask) ? meeting.week_mask.join(', ') : '';
  const dates = Array.isArray(meeting.date_range) ? meeting.date_range.map(d => d ?? 'theo học kỳ').join(' → ') : '';
  return `${meeting.course} · ${meeting.class_code} · Thứ ${meeting.day} · Tiết ${periods} · Phòng ${meeting.room || 'chưa rõ'} · Tuần ${weeks} · ${dates}`;
}

const roles = {CURRENT_SCHEDULE: 'Lịch học', PREFERENCE: 'Nguyện vọng', HISTORICAL: 'Lịch sử', OUTPUT_TEMPLATE: 'Mẫu đầu ra', REFERENCE_MATRIX: 'Ma trận tham chiếu'};

export function SourceAuthorityPanel({semesterId, refreshKey, onChanged, onStateChanged}: {semesterId: number; refreshKey: string | null; onChanged?: () => void; onStateChanged?: (state: SourceState | null) => void}) {
  const [state, setState] = useState<SourceState | null>(null);
  const [lecturers, setLecturers] = useState<Lecturer[]>([]);
  const [preview, setPreview] = useState<SourcePreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadRole, setUploadRole] = useState<SourceRole | ''>('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const load = useCallback(async () => {
    try {
      const sources = await api.sources(semesterId);
      setState(sources);
      onStateChanged?.(sources);
      setError(null);
    } catch (e) {
      setState(null);
      onStateChanged?.(null);
      setError(`Không tải được nguồn dữ liệu. ${e instanceof Error ? e.message : 'Kiểm tra backend và thử lại.'}`);
    }
    try {
      setLecturers(await api.lecturers());
    } catch {
      // The source selector remains usable when the separate lecturer list is unavailable.
      setLecturers([]);
    }
  }, [semesterId, onStateChanged]);
  useEffect(() => { if (!refreshKey) void load(); }, [load, refreshKey]);
  async function activate() {
    if (!preview || !confirmed) return;
    setBusy(true); setError(null);
    try { await api.activateSource(preview, semesterId); setPreview(null); setConfirmed(false); await load(); onChanged?.(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Chưa kích hoạt được.'); }
    finally { setBusy(false); }
  }
  return <section className={styles.flatPanel} aria-label="Nguồn đang hoạt động">
    <h3>Nguồn đang hoạt động</h3>
    <p>Tải file chỉ lưu nguồn ứng viên. Xem đối chiếu và xác nhận để thay đổi nguồn đang sử dụng.</p>
    {error ? <div role="alert"><p>{error}</p><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Thử tải lại nguồn</button></div> : null}
    {(['CURRENT_SCHEDULE', 'PREFERENCE'] as const).map(role => {
      const active = state?.sources.find(s => s.source_type === role && s.active);
      return <p key={role}><strong>{roles[role]}: </strong>{active ? <>{active.original_filename} · {active.content_hash?.slice(0,12) ?? 'Chưa xác minh hash'} · {new Date(active.created_at).toLocaleString('vi-VN')} · <strong>ACTIVE</strong></> : state ? 'Chưa chọn nguồn — dữ liệu cũ chưa xác minh' : 'Chưa xác định vì chưa tải được dữ liệu nguồn'}</p>;
    })}
    <p><strong>MULTI-LECTURER: {state?.issues.filter(i => i.code !== 'SOURCE_CHANGED_REVIEW_REQUIRED').length ?? 0}</strong> · <strong>SOURCE CHANGE REVIEW: {state?.issues.filter(i => i.code === 'SOURCE_CHANGED_REVIEW_REQUIRED').length ?? 0}</strong></p>
    <details><summary>Thêm một nguồn riêng</summary>
      <label className={styles.field}><span>Vai trò nguồn tải lên</span><select value={uploadRole} onChange={e => setUploadRole(e.target.value as SourceRole | '')}><option value="">Chọn vai trò</option>{Object.entries(roles).map(([role,label]) => <option key={role} value={role}>{label}</option>)}</select></label>
      <label className={styles.field}><span>Workbook nguồn</span><input type="file" accept=".xlsx,.xls" onChange={e => setUploadFile(e.target.files?.[0] ?? null)} /></label>
      <button className={styles.secondaryButton} disabled={busy || !uploadRole || !uploadFile} onClick={async () => {
        if (!uploadFile || !uploadRole) return;
        setBusy(true); setError(null);
        try {await api.uploadSource(uploadFile, uploadRole, semesterId); await load();}
        catch(e) {setError(e instanceof Error ? e.message : 'Không lưu được nguồn.');}
        finally {setBusy(false);}
      }}>Lưu nguồn ứng viên</button>
    </details>
    <div className={styles.tableWrap}><table><thead><tr><th>Nguồn</th><th>Vai trò</th><th>Hash / Trạng thái</th><th>Thao tác</th></tr></thead><tbody>
      {state?.sources.map(source => <tr key={source.id}>
        <td>{source.original_filename}<br /><small>{new Date(source.created_at).toLocaleString('vi-VN')}</small></td>
        <td>{roles[source.source_type]}</td><td>{source.content_hash?.slice(0,12) ?? 'LEGACY / UNVERIFIED'} · {source.active ? 'ACTIVE' : 'Ứng viên'}</td>
        <td>{!source.active && ['CURRENT_SCHEDULE','PREFERENCE'].includes(source.source_type) ? <button className={styles.secondaryButton} disabled={busy} onClick={async () => {
          setBusy(true); setError(null); setConfirmed(false);
          try {setPreview(await api.previewSource(source.id, source.source_type, semesterId));}
          catch(e) {setError(e instanceof Error ? e.message : 'Không thể đối chiếu.');}
          finally {setBusy(false);}
        }}>Đối chiếu / Compare</button> : source.active ? 'Đang sử dụng' : 'Chỉ tham chiếu'}</td>
      </tr>)}
    </tbody></table></div>
    {preview ? <div className={styles.flatPanel} aria-label="Đối chiếu nguồn">
      <h4>Đối chiếu: {preview.filename}</h4>
      {preview.diff.counts ? <p>{Object.entries(preview.diff.counts).map(([key,value]) => `${key}: ${value}`).join(' · ')}</p> : <p>{preview.diff.drafts} nguyện vọng · {preview.diff.seminars} seminar. Quy tắc nguồn cũ cần rà soát.</p>}
      {preview.diff.meetings?.filter(m => m.status !== 'UNCHANGED').map((m,index) => <details key={index}><summary>{m.status} · {String(m.after?.class_code ?? m.before?.class_code)} · {m.changed_fields.join(', ')}</summary><p>Trước: {describeMeeting(m.before)}</p><p>Sau: {describeMeeting(m.after)}</p></details>)}
      {preview.diagnostics.map((d,index) => <p key={index}>{d.code}: {d.message}</p>)}
      <ul>{preview.consequences.map(c => <li key={c}>{c}</li>)}</ul>
      <label className={styles.switchLabel}><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Tôi đã rà soát thay đổi và xác nhận sử dụng nguồn này.</label>
      <button className={styles.primaryButton} disabled={busy || !confirmed || !preview.can_activate} onClick={() => void activate()}>Xác nhận kích hoạt / Activate</button>
      <button className={styles.secondaryButton} disabled={busy} onClick={() => setPreview(null)}>Hủy</button>
    </div> : null}
    {state?.issues.map(issue => <SourceReview key={issue.id} issue={issue} lecturers={lecturers} semesterId={semesterId} onResolved={async () => {await load(); onChanged?.();}} />)}
  </section>;
}

function SourceReview({issue, lecturers, semesterId, onResolved}: {issue: SourceIssue; lecturers: Lecturer[]; semesterId: number; onResolved: () => Promise<void>}) {
  const [lecturer, setLecturer] = useState('');
  const [action, setAction] = useState(issue.code === 'SOURCE_CHANGED_REVIEW_REQUIRED' ? 'ACKNOWLEDGE_STALE' : 'NORMALIZE_SINGLE');
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const needsLecturer = ['NORMALIZE_SINGLE','CORRECT_INTERPRETATION'].includes(action);
  return <div className={styles.flatPanel}>
    <strong>{issue.code}: {issue.message}</strong>
    {issue.details.rows?.map(row => <p key={row.row}>Dòng {row.row}: {row.raw}</p>)}
    <label className={styles.field}><span>Cách xử lý</span><select value={action} onChange={e => setAction(e.target.value)}>
      {issue.code === 'SOURCE_CHANGED_REVIEW_REQUIRED' ? <option value="ACKNOWLEDGE_STALE">Đã rà soát; giữ quy tắc cũ vô hiệu, tạo lại nếu cần</option> : <><option value="NORMALIZE_SINGLE">Một giảng viên cho cả nhóm</option><option value="CORRECT_INTERPRETATION">Sửa cách hiểu nguồn thành một giảng viên</option><option value="DEFER_SPECIAL">Tách / đồng giảng thật — tiếp tục chặn solve</option></>}
    </select></label>
    {needsLecturer ? <label className={styles.field}><span>Giảng viên chuẩn</span><select value={lecturer} onChange={e => setLecturer(e.target.value)}><option value="">Chọn giảng viên</option>{lecturers.map(l => <option key={l.id} value={l.id}>{l.code} · {l.name}</option>)}</select></label> : null}
    <label className={styles.field}><span>Người xác nhận</span><input value={actor} onChange={e => setActor(e.target.value)} /></label>
    <label className={styles.field}><span>Lý do / cách hiểu đã xác nhận</span><input value={note} onChange={e => setNote(e.target.value)} /></label>
    {error ? <p role="alert">{error}</p> : null}
    <button className={styles.secondaryButton} disabled={busy || !actor.trim() || !note.trim() || (needsLecturer && !lecturer)} onClick={async () => {
      setBusy(true); setError('');
      try {await api.resolveSourceIssue(issue.id, {action, lecturer_id: lecturer ? Number(lecturer) : null, actor, note}, semesterId); await onResolved();}
      catch(e) {setError(e instanceof Error ? e.message : 'Chưa lưu được.');}
      finally {setBusy(false);}
    }}>Lưu xác nhận</button>
  </div>;
}
