import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../src/services/api';

afterEach(() => vi.unstubAllGlobals());

it('uses same-origin API and reports a recoverable network failure', async () => {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
  vi.stubGlobal('fetch', fetchMock);
  await expect(api.sources(2)).rejects.toThrow('Kiểm tra backend và thử tải lại dữ liệu.');
  expect(fetchMock).toHaveBeenCalledWith('/api/backend/api/v1/sources?semester_id=2', expect.any(Object));
});
