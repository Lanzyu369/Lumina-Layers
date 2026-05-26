import readExcelFile from "read-excel-file/browser";
import type {
  ColorcheckerReferenceNormalizeResponse,
  ColorcheckerReferencePatch,
  ColorcheckerReferenceSource,
} from "../api/extractor";

type CellValue = string | number | boolean | Date | null;
type SheetRow = CellValue[];

export interface ParsedColorcheckerReference {
  patches: ColorcheckerReferencePatch[];
  source: ColorcheckerReferenceSource;
  sheetName: string;
}

export interface StoredColorcheckerReference {
  key: string;
  name: string;
  patches: ColorcheckerReferencePatch[];
  source: ColorcheckerReferenceSource;
  referenceHash: string;
  warnings: string[];
  createdAt: string;
}

interface HeaderMapping {
  index: number;
  label: number | null;
  srgb: [number, number, number] | null;
  labD50: [number, number, number] | null;
  labD65: [number, number, number] | null;
  dataStart: number;
}

type HeaderChannel = "r" | "g" | "b" | "l" | "a";

const CUSTOM_REFERENCES_STORAGE_KEY = "lumina.colorchecker.references.v1";
const SELECTED_REFERENCE_STORAGE_KEY = "lumina.colorchecker.selectedReference.v1";

export async function readColorcheckerReferenceWorkbook(
  file: File,
): Promise<ParsedColorcheckerReference> {
  const sheets = await readExcelFile(file);
  const selected = sheets.find((sheet) => sheet.sheet === "Sheet1") ?? sheets[0];
  if (!selected) {
    throw new Error("未找到可读取的工作表。");
  }
  return parseColorcheckerReferenceRows(
    selected.data as SheetRow[],
    file.name,
    selected.sheet,
  );
}

export function parseColorcheckerReferenceRows(
  rows: SheetRow[],
  fileName: string = "custom-reference.xlsx",
  sheetName: string = "Sheet1",
): ParsedColorcheckerReference {
  const mapping = findHeaderMapping(rows);
  if (!mapping) {
    throw new Error("未找到 No/Number、sRGB、Lab D50 或 Lab D65 表头。");
  }

  const patches: ColorcheckerReferencePatch[] = [];
  for (let rowIndex = mapping.dataStart; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex] ?? [];
    const index = cellToInteger(row[mapping.index]);
    if (index === null) {
      if (row.every((cell) => cell === null || cell === "")) {
        continue;
      }
      continue;
    }
    const label = mapping.label === null ? undefined : cellToText(row[mapping.label]);
    const patch: ColorcheckerReferencePatch = {
      index,
      label: label || `Patch ${index}`,
    };
    const srgb = readTriplet(row, mapping.srgb, "sRGB", index);
    const labD50 = readTriplet(row, mapping.labD50, "Lab D50", index);
    const labD65 = readTriplet(row, mapping.labD65, "Lab D65", index);
    if (srgb) patch.sRGB = srgb;
    if (labD50) patch.Lab_d50 = labD50;
    if (labD65) patch.Lab_d65 = labD65;
    patches.push(patch);
    if (patches.length === 24) break;
  }

  const baseName = fileName.replace(/\.[^.]+$/, "") || "自定义校色基准";
  return {
    patches,
    sheetName,
    source: {
      sourceType: "user_upload",
      sourceName: baseName,
      serialNumber: findSerialNumber(rows),
      patchCount: patches.length,
      labWhitePoint: mapping.labD50 ? "D50" : "D65",
    },
  };
}

export function makeStoredColorcheckerReference(
  normalized: ColorcheckerReferenceNormalizeResponse,
  fallbackName: string,
): StoredColorcheckerReference {
  const hash = normalized.referenceHash;
  const sourceName = normalized.source.sourceName?.trim() || fallbackName || "自定义校色基准";
  const serial = normalized.source.serialNumber?.trim();
  return {
    key: `custom:${hash}`,
    name: serial ? `${sourceName} (${serial})` : sourceName,
    patches: normalized.patches,
    source: {
      ...normalized.source,
      referenceHash: hash,
      patchCount: normalized.patches.length,
    },
    referenceHash: hash,
    warnings: normalized.warnings,
    createdAt: new Date().toISOString(),
  };
}

export function loadStoredColorcheckerReferences(): StoredColorcheckerReference[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CUSTOM_REFERENCES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isStoredReference);
  } catch {
    return [];
  }
}

export function saveStoredColorcheckerReferences(
  references: StoredColorcheckerReference[],
) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    CUSTOM_REFERENCES_STORAGE_KEY,
    JSON.stringify(references.filter(isStoredReference)),
  );
}

export function upsertStoredColorcheckerReference(
  reference: StoredColorcheckerReference,
) {
  const current = loadStoredColorcheckerReferences();
  const next = [
    reference,
    ...current.filter((item) => item.key !== reference.key),
  ];
  saveStoredColorcheckerReferences(next);
  return next;
}

export function removeStoredColorcheckerReference(key: string) {
  const next = loadStoredColorcheckerReferences().filter((item) => item.key !== key);
  saveStoredColorcheckerReferences(next);
  return next;
}

export function loadSelectedColorcheckerReferenceKey(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SELECTED_REFERENCE_STORAGE_KEY);
}

export function saveSelectedColorcheckerReferenceKey(key: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SELECTED_REFERENCE_STORAGE_KEY, key);
}

function findHeaderMapping(rows: SheetRow[]): HeaderMapping | null {
  const maxRows = Math.min(rows.length, 20);
  for (let index = 0; index < maxRows; index += 1) {
    const first = rows[index] ?? [];
    const second = rows[index + 1] ?? [];
    const singleRowMapping = buildMapping(first, [], index + 1);
    if (singleRowMapping) return singleRowMapping;
    const mapping = buildMapping(first, second, index + 2);
    if (mapping) return mapping;
  }
  return null;
}

function buildMapping(
  firstHeaderRow: SheetRow,
  secondHeaderRow: SheetRow,
  dataStart: number,
): HeaderMapping | null {
  const maxCols = Math.max(firstHeaderRow.length, secondHeaderRow.length);
  const groups = forwardFilled(firstHeaderRow, maxCols);
  let indexColumn: number | null = null;
  let labelColumn: number | null = null;
  const srgb: Partial<Record<HeaderChannel, number>> = {};
  const labD50: Partial<Record<HeaderChannel, number>> = {};
  const labD65: Partial<Record<HeaderChannel, number>> = {};

  for (let column = 0; column < maxCols; column += 1) {
    const group = normalizeHeader(groups[column]);
    const sub = normalizeHeader(secondHeaderRow[column]);
    const direct = normalizeHeader(firstHeaderRow[column]);
    const combined = `${group} ${sub || direct}`.trim();

    if (indexColumn === null && (direct === "no" || direct === "number" || direct === "index")) {
      indexColumn = column;
      continue;
    }
    if (labelColumn === null && (direct === "number" || direct === "name" || direct === "label")) {
      labelColumn = column;
      continue;
    }

    const channel = colorChannel(sub || direct) ?? compactColorChannel(direct);
    if (!channel) continue;
    if (combined.includes("srgb") || combined.includes("rgb")) {
      srgb[channel] = column;
    } else if (combined.includes("d50")) {
      labD50[channel] = column;
    } else if (combined.includes("d65")) {
      labD65[channel] = column;
    }
  }

  if (indexColumn === null) return null;
  const srgbCols = tripletColumns(srgb);
  const labD50Cols = tripletColumns(labD50);
  const labD65Cols = tripletColumns(labD65);
  if (!srgbCols && !labD50Cols && !labD65Cols) return null;
  return {
    index: indexColumn,
    label: labelColumn,
    srgb: srgbCols,
    labD50: labD50Cols,
    labD65: labD65Cols,
    dataStart,
  };
}

function forwardFilled(row: SheetRow, length: number) {
  const values: CellValue[] = [];
  let current: CellValue = null;
  for (let index = 0; index < length; index += 1) {
    if (row[index] !== null && row[index] !== undefined && row[index] !== "") {
      current = row[index];
    }
    values.push(current);
  }
  return values;
}

function tripletColumns(
  columns: Partial<Record<HeaderChannel, number>>,
): [number, number, number] | null {
  if (
    typeof columns.r === "number" &&
    typeof columns.g === "number" &&
    typeof columns.b === "number"
  ) {
    return [columns.r, columns.g, columns.b];
  }
  if (
    typeof columns.l === "number" &&
    typeof columns.a === "number" &&
    typeof columns.b === "number"
  ) {
    return [columns.l, columns.a, columns.b];
  }
  return null;
}

function colorChannel(value: string): HeaderChannel | null {
  if (value === "r" || value === "red") return "r";
  if (value === "g" || value === "green") return "g";
  if (value === "b" || value === "blue") return "b";
  if (value === "l" || value === "lstar") return "l";
  if (value === "a" || value === "astar") return "a";
  if (value === "bstar") return "b";
  return null;
}

function compactColorChannel(value: string): HeaderChannel | null {
  const rgbMatch = /(?:^|srgb|rgb)([rgb])$/.exec(value);
  if (rgbMatch && (value.includes("srgb") || value.includes("rgb"))) {
    return rgbMatch[1] as HeaderChannel;
  }
  const labMatch = /(?:lab)?d(?:50|65)([lab])$/.exec(value);
  if (labMatch) {
    return labMatch[1] as HeaderChannel;
  }
  return null;
}

function readTriplet(
  row: SheetRow,
  columns: [number, number, number] | null,
  label: string,
  patchIndex: number,
): number[] | null {
  if (!columns) return null;
  const values = columns.map((column) => cellToNumber(row[column]));
  if (values.every((value) => value === null)) return null;
  if (values.some((value) => value === null)) {
    throw new Error(`色块 ${patchIndex} 的 ${label} 三元组不完整。`);
  }
  return values as number[];
}

function cellToInteger(value: CellValue): number | null {
  const parsed = cellToNumber(value);
  if (parsed === null) return null;
  return Number.isInteger(parsed) ? parsed : Math.round(parsed);
}

function cellToNumber(value: CellValue): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function cellToText(value: CellValue): string | undefined {
  if (value === null || value === undefined) return undefined;
  return String(value).trim() || undefined;
}

function findSerialNumber(rows: SheetRow[]) {
  for (const row of rows.slice(0, 12)) {
    for (const cell of row) {
      const text = cellToText(cell);
      const match = text?.match(/\bSN\s*[:：]\s*([A-Za-z0-9._-]+)/i);
      if (match) return match[1];
    }
  }
  return null;
}

function normalizeHeader(value: CellValue) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/cie/g, "")
    .replace(/cielab/g, "lab")
    .replace(/色值|编号|序号/g, "")
    .replace(/[()\[\]{}*_\-\s/.：:]+/g, "");
}

function isStoredReference(value: unknown): value is StoredColorcheckerReference {
  if (!value || typeof value !== "object") return false;
  const item = value as StoredColorcheckerReference;
  return (
    typeof item.key === "string" &&
    item.key.startsWith("custom:") &&
    typeof item.name === "string" &&
    typeof item.referenceHash === "string" &&
    Array.isArray(item.patches)
  );
}
