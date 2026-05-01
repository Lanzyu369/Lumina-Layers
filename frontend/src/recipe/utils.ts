/**
 * Recipe utility functions: hashing, base64 conversion, asset building.
 * 配方工具函数：哈希、base64 转换、asset 构建。
 */

import type { AssetEntry } from "./types";

const SHA256_INITIAL_HASH = [
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
];

const SHA256_ROUND_CONSTANTS = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function rotateRight(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

function sha256HexFallback(data: ArrayBuffer): string {
  const input = new Uint8Array(data);
  const withTerminatorLength = input.length + 1;
  const paddingLength = (64 - ((withTerminatorLength + 8) % 64)) % 64;
  const totalLength = withTerminatorLength + paddingLength + 8;
  const message = new Uint8Array(totalLength);
  message.set(input);
  message[input.length] = 0x80;

  const messageView = new DataView(message.buffer);
  const bitLengthHigh = Math.floor(input.length / 0x20000000);
  const bitLengthLow = (input.length << 3) >>> 0;
  messageView.setUint32(totalLength - 8, bitLengthHigh);
  messageView.setUint32(totalLength - 4, bitLengthLow);

  const hash = [...SHA256_INITIAL_HASH];
  const words = new Uint32Array(64);

  for (let offset = 0; offset < totalLength; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      words[i] = messageView.getUint32(offset + i * 4);
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotateRight(words[i - 15], 7) ^ rotateRight(words[i - 15], 18) ^ (words[i - 15] >>> 3);
      const s1 = rotateRight(words[i - 2], 17) ^ rotateRight(words[i - 2], 19) ^ (words[i - 2] >>> 10);
      words[i] = (words[i - 16] + s0 + words[i - 7] + s1) >>> 0;
    }

    let [a, b, c, d, e, f, g, h] = hash;
    for (let i = 0; i < 64; i += 1) {
      const s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + ch + SHA256_ROUND_CONSTANTS[i] + words[i]) >>> 0;
      const s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }

  return hash.map((word) => word.toString(16).padStart(8, "0")).join("");
}

/**
 * Compute SHA-256 hex digest of an ArrayBuffer using Web Crypto API.
 * 使用 Web Crypto API 计算 ArrayBuffer 的 SHA-256 十六进制摘要。
 */
export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle?.digest) {
    return sha256HexFallback(data);
  }
  let hashBuffer: ArrayBuffer;
  try {
    hashBuffer = await subtle.digest("SHA-256", data);
  } catch {
    return sha256HexFallback(data);
  }
  const bytes = new Uint8Array(hashBuffer);
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

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
 * Build an AssetEntry from a File, computing sha256 and base64 payload.
 * 从 File 构建 AssetEntry，计算 sha256 和 base64 负载。
 */
export async function buildAssetEntry(file: File): Promise<AssetEntry> {
  const buffer = await file.arrayBuffer();
  const [hash, payload] = await Promise.all([
    sha256Hex(buffer),
    fileToBase64(file),
  ]);
  return {
    filename: file.name,
    mime_type: file.type || "application/octet-stream",
    byte_size: file.size,
    sha256: hash,
    encoding: "base64",
    payload_b64: payload,
  };
}

/**
 * Compute SHA-256 hex digest of a UTF-8 string.
 * 计算 UTF-8 字符串的 SHA-256 十六进制摘要。
 */
export async function sha256String(str: string): Promise<string> {
  const encoder = new TextEncoder();
  return sha256Hex(encoder.encode(str).buffer as ArrayBuffer);
}
