/**
 * 单元测试: isValidImageType、ACCEPT_IMAGE_FORMATS、i18n 错误消息
 * Feature: alpha-channel-support
 *
 * Validates: Requirements 1.1, 1.3, 1.4, 3.1, 3.2, 4.1, 4.2, 5.1
 */
import { describe, it, expect } from "vitest";
import {
  isValidImageType,
  ACCEPT_IMAGE_FORMATS,
} from "../stores/converter";
import { translations } from "../i18n/translations";

const SUPPORTED_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/svg+xml",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

describe("isValidImageType — 支持的格式返回 true", () => {
  it.each(SUPPORTED_MIME_TYPES)("returns true for %s", (mime) => {
    expect(isValidImageType(mime)).toBe(true);
  });
});

describe("isValidImageType 鈥?不支持的格式返回 false", () => {
  it.each(["application/pdf", "text/plain", "image/bmp", "image/tiff", ""])(
    'returns false for "%s"',
    (mime) => {
      expect(isValidImageType(mime)).toBe(false);
    },
  );
});

const RAW_FILE_NAMES = [
  "photo.dng",
  "photo.cr2",
  "photo.cr3",
  "photo.nef",
  "photo.arw",
  "photo.orf",
  "photo.rw2",
  "photo.raf",
  "photo.pef",
  "photo.srw",
  "photo.raw",
] as const;

describe("JFIF files accepted by extension", () => {
  it.each(["photo.jfif", "photo.JFIF"])("accepts %s without a JPEG MIME type", (fileName) => {
    for (const mime of ["", "application/octet-stream", "image/jpeg"]) {
      expect(isValidImageType(mime, fileName)).toBe(true);
    }
  });

  it("includes JFIF in the native file picker", () => {
    expect(ACCEPT_IMAGE_FORMATS.split(",")).toContain(".jfif");
  });

  it("does not accept unrelated or misleading extensions", () => {
    expect(isValidImageType("", "photo.jfif.exe")).toBe(false);
    expect(isValidImageType("", "photo.txt")).toBe(false);
  });
});

describe("RAW files accepted by extension", () => {
  it.each(RAW_FILE_NAMES)("returns true for %s with empty MIME", (fileName) => {
    expect(isValidImageType("", fileName)).toBe(true);
  });
});

describe("ACCEPT_IMAGE_FORMATS 常量", () => {
  it("包含所有 6 种支持的 MIME 类型", () => {
    for (const mime of SUPPORTED_MIME_TYPES) {
      expect(ACCEPT_IMAGE_FORMATS).toContain(mime);
    }
  });

  it("是逗号分隔的字符串", () => {
    const parts = ACCEPT_IMAGE_FORMATS.split(",");
    expect(parts.length).toBeGreaterThanOrEqual(17);
    parts.forEach((part) => {
      expect(part.trim()).not.toBe("");
    });
  });
});

/**
 * i18n 错误消息测试
 * Validates: Requirements 4.1, 4.2
 */
describe("i18n basic_image_format_error 翻译", () => {
  const entry = translations["basic_image_format_error"];

  it("翻译 key 存在", () => {
    expect(entry).toBeDefined();
  });

  it("中文消息包含 WebP 和 HEIC", () => {
    expect(entry.zh).toContain("WebP");
    expect(entry.zh).toContain("HEIC");
  });

  it("英文消息包含 WebP 和 HEIC", () => {
    expect(entry.en).toContain("WebP");
    expect(entry.en).toContain("HEIC");
  });
});

