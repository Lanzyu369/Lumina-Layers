/**
 * Recipe utility functions: base64 conversion and asset building.
 * 配方工具函数：base64 转换与素材构建。
 */

import type { AssetEntry } from "./types";

/**
 * Convert a File/Blob to a base64-encoded string (no data-URI prefix).
 * 将 File/Blob 转换为 base64 编码字符串（不含 data-URI 前缀）。
 */
export function fileToBase64(file: File | Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip "data:...;base64," prefix
      const idx = result.indexOf(",");
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/**
 * Convert a base64-encoded string back to a File object.
 * 将 base64 编码字符串还原为 File 对象。
 */
export function base64ToFile(
  b64: string,
  filename: string,
  mimeType: string,
): File {
  const binaryStr = atob(b64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }
  return new File([bytes], filename, { type: mimeType });
}

/**
 * Build an AssetEntry from a File, preserving its bytes as base64.
 * 从 File 构建 AssetEntry，以 base64 保留文件原始字节。
 */
export async function buildAssetEntry(file: File): Promise<AssetEntry> {
  const payload = await fileToBase64(file);
  return {
    filename: file.name,
    mime_type: file.type || "application/octet-stream",
    byte_size: file.size,
    encoding: "base64",
    payload_b64: payload,
  };
}
