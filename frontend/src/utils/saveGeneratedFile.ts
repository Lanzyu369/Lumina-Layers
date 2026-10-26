export type SavePurpose = 'project' | 'share-card' | 'screenshot';
export type SaveOutcome = 'saved' | 'canceled' | 'download-started';
export async function saveGeneratedFile(blob: Blob, filename: string, purpose: SavePurpose): Promise<SaveOutcome> {
  if (blob.size > 128 * 1024 * 1024) throw new Error('file_save_too_large');
  const bridge = (window as unknown as { electronAPI?: { saveGeneratedFile?: (payload: {
    filename: string; purpose: SavePurpose; bytes: Uint8Array;
  }) => Promise<{ status: string; code?: string }> } }).electronAPI;
  if (bridge) {
    if (!bridge.saveGeneratedFile) throw new Error('file_save_failed');
    try {
      const result = await bridge.saveGeneratedFile({ filename, purpose, bytes: new Uint8Array(await blob.arrayBuffer()) });
      if (result.status === 'saved' || result.status === 'canceled') return result.status;
      throw new Error(result.code === 'too-large' ? 'file_save_too_large' : 'file_save_failed');
    } catch (error) {
      throw new Error(error instanceof Error && error.message === 'file_save_too_large' ? error.message : 'file_save_failed');
    }
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  try { anchor.click(); } finally { anchor.remove(); URL.revokeObjectURL(url); }
  return 'download-started';
}
