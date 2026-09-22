import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SourceAuthorityPanel } from '../src/features/dashboard/source-authority-panel';
import { api } from '../src/services/api';

vi.mock('../src/services/api', () => ({api: {sources: vi.fn(), lecturers: vi.fn(), previewSource: vi.fn(), activateSource: vi.fn(), resolveSourceIssue: vi.fn()}}));
afterEach(cleanup);
const source = {id: 9, source_type: 'CURRENT_SCHEDULE', original_filename: 'candidate.xlsx', content_hash: 'abcdef123456789', created_at: '2026-09-09T00:00:00', provenance_status: 'VERIFIED', active: false, parse_summary: {}, parent_version_id: null};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.sources).mockResolvedValue({sources: [source], issues: [], active_schedule_source_id: null, active_preference_source_id: null, source_revision: 0, legacy_unverified: true} as never);
  vi.mocked(api.lecturers).mockResolvedValue([{id: 1, code: 'A', name: 'Teacher Alpha'}] as never);
  vi.mocked(api.previewSource).mockResolvedValue({source_id: 9, source_type: 'CURRENT_SCHEDULE', filename: 'candidate.xlsx', preview_token: 'receipt', can_activate: true, diff: {counts: {ADDED: 1}}, diagnostics: [], consequences: ['Old references require review.']} as never);
  vi.mocked(api.activateSource).mockResolvedValue({active: true});
});
it('shows candidates without activating and requires reviewed confirmation', async () => {
  render(<SourceAuthorityPanel semesterId={1} refreshKey={null} />);
  await screen.findByText('candidate.xlsx');
  expect(api.activateSource).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name: 'Đối chiếu / Compare'}));
  const activate = await screen.findByRole('button', {name: 'Xác nhận kích hoạt / Activate'});
  expect(activate).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));
  expect(activate).toBeEnabled();
  fireEvent.click(activate);
  await waitFor(() => expect(api.activateSource).toHaveBeenCalledWith(expect.objectContaining({preview_token:'receipt'}), 1));
});
it('reference sources have no implicit schedule activation action', async () => {
  vi.mocked(api.sources).mockResolvedValue({sources: [{...source, source_type: 'HISTORICAL'}], issues: []} as never);
  render(<SourceAuthorityPanel semesterId={1} refreshKey={null} />);
  await screen.findByText('candidate.xlsx');
  expect(screen.queryByRole('button', {name: 'Đối chiếu / Compare'})).not.toBeInTheDocument();
  expect(screen.getByText('Chỉ tham chiếu')).toBeInTheDocument();
});
it('keeps source selection available if the separate lecturer request fails', async () => {
  vi.mocked(api.lecturers).mockRejectedValue(new TypeError('Failed to fetch'));
  render(<SourceAuthorityPanel semesterId={1} refreshKey={null} />);
  await screen.findByText('candidate.xlsx');
  expect(screen.queryByText('Failed to fetch')).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Đối chiếu / Compare'})).toBeEnabled();
});
it('shows an actionable source API error instead of a raw network exception', async () => {
  vi.mocked(api.sources).mockRejectedValue(new Error('Không kết nối được máy chủ HUCE. Kiểm tra backend và thử tải lại dữ liệu.'));
  render(<SourceAuthorityPanel semesterId={1} refreshKey={null} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Không tải được nguồn dữ liệu. Không kết nối được máy chủ HUCE.');
  expect(screen.queryByText('Failed to fetch')).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Thử tải lại nguồn'})).toBeEnabled();
});
it('special-case resolution requires an actor and note and remains explicitly deferred', async () => {
  vi.mocked(api.sources).mockResolvedValue({sources: [], issues: [{id: 2, code: 'MULTI_LECTURER_REVIEW', message:'L needs review', details:{rows:[{row:2,raw:'Alpha; Beta'}]}, resolution_status:'OPEN'}]} as never);
  render(<SourceAuthorityPanel semesterId={1} refreshKey={null} />);
  await screen.findByText('Dòng 2: Alpha; Beta');
  const save=screen.getByRole('button',{name:'Lưu xác nhận'});
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Cách xử lý'),{target:{value:'DEFER_SPECIAL'}});
  fireEvent.change(screen.getByLabelText('Người xác nhận'),{target:{value:'Reviewer'}});
  fireEvent.change(screen.getByLabelText('Lý do / cách hiểu đã xác nhận'),{target:{value:'Two real teachers'}});
  fireEvent.click(save);
  await waitFor(() => expect(api.resolveSourceIssue).toHaveBeenCalledWith(2,expect.objectContaining({action:'DEFER_SPECIAL',actor:'Reviewer'}),1));
});
