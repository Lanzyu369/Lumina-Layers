import { afterEach, expect, it, vi } from 'vitest';
import { saveGeneratedFile } from '../utils/saveGeneratedFile';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it('uses native bytes and preserves canceled versus saved', async () => {
  const save = vi.fn().mockResolvedValue({ status: 'canceled' });
  Object.assign(window, { electronAPI: { saveGeneratedFile: save } });
  const blob = new Blob(['{}'], { type: 'application/json' });
  expect(await saveGeneratedFile(blob, 'art.lumina.json', 'project')).toBe('canceled');
  expect(save.mock.calls[0][0]).toMatchObject({ filename: 'art.lumina.json', purpose: 'project' });
  save.mockResolvedValue({ status: 'saved' });
  expect(await saveGeneratedFile(blob, 'art.lumina.json', 'project')).toBe('saved');
});
it('surfaces native errors and limits before sending', async () => {
  const save = vi.fn().mockResolvedValue({ status: 'error', code: 'write-failed' });
  Object.assign(window, { electronAPI: { saveGeneratedFile: save } });
  await expect(saveGeneratedFile(new Blob(['x']), 'x.png', 'screenshot')).rejects.toThrow('file_save_failed');
  const large = new Blob(['x']);
  Object.defineProperty(large, 'size', { value: 128 * 1024 * 1024 + 1 });
  await expect(saveGeneratedFile(large, 'x.png', 'screenshot')).rejects.toThrow('file_save_too_large');
  expect(save).toHaveBeenCalledTimes(1);
});
it('browser starts an anchor download', async () => {
  Object.assign(window, { electronAPI: undefined });
  URL.createObjectURL = vi.fn(() => 'blob:test');
  URL.revokeObjectURL = vi.fn();
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  expect(await saveGeneratedFile(new Blob(['x']), 'x.png', 'share-card')).toBe('download-started');
  expect(click).toHaveBeenCalledOnce();
});
