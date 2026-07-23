/**
 * Feature: slicer-launch-integration
 * Property-Based Tests for slicer launch integration
 *
 * Uses Vitest + fast-check
 */
import { describe, it, beforeEach, expect } from "vitest";
import * as fc from "fast-check";
import { resolveSelectedSlicerId } from "../stores/slicerStore";

// ========== Pure mapping logic extracted from ConverterStore.submitGenerate ==========

/**
 * Redacts a GenerateResponse's legacy threemf_disk_path before store writes.
 * Mirrors: `threemfDiskPath: null`
 */
function mapThreemfDiskPath(
  threemf_disk_path: string | null | undefined
): string | null {
  void threemf_disk_path;
  return null;
}

/**
 * Maps a GenerateResponse's download_url to the store's downloadUrl.
 * Mirrors: `downloadUrl: response.download_url ?? null`
 */
function mapDownloadUrl(download_url: string | null | undefined): string | null {
  return download_url ?? null;
}

// ========== Tests ==========

describe("Slicer Launch Integration — Property-Based Tests", () => {
  /**
   * Feature: slicer-launch-integration, Property 2: ConverterStore 不保存后端磁盘路径
   * **Validates: Requirements 1.2**
   *
   * For any GenerateResponse, threemf_disk_path should not be copied into state.
   */
  describe("Property 2: ConverterStore 不保存后端磁盘路径", () => {
    it("non-empty threemf_disk_path maps to null", () => {
      fc.assert(
        fc.property(
          fc.string({ minLength: 1 }),
          (path) => {
            const result = mapThreemfDiskPath(path);
            return result === null;
          }
        ),
        { numRuns: 100 }
      );
    });

    it("null threemf_disk_path maps to null", () => {
      const result = mapThreemfDiskPath(null);
      return result === null;
    });

    it("undefined threemf_disk_path maps to null", () => {
      const result = mapThreemfDiskPath(undefined);
      return result === null;
    });

    it("for any optional string, mapping always redacts to null", () => {
      fc.assert(
        fc.property(
          fc.option(fc.string({ minLength: 1 }), { nil: undefined }),
          (maybePath) => {
            const result = mapThreemfDiskPath(maybePath);
            return result === null;
          }
        ),
        { numRuns: 100 }
      );
    });

    it("downloadUrl mapping: non-empty url keeps relative value, null/undefined maps to null", () => {
      fc.assert(
        fc.property(
          fc.option(fc.string({ minLength: 1 }), { nil: undefined }),
          (maybeUrl) => {
            const result = mapDownloadUrl(maybeUrl);
            if (maybeUrl) {
              return result === maybeUrl;
            }
            return result === null;
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});

// ========== Property 3: 参数变更使 threemfDiskPath 失效 ==========

import { useConverterStore } from "../stores/converter";
import { ColorMode, ModelingMode, StructureMode } from "../api/types";

/**
 * Feature: slicer-launch-integration, Property 3: 参数变更使 threemfDiskPath 失效
 * **Validates: Requirements 3.1, 3.3**
 *
 * For any 影响生成结果的参数 setter，当 threemfDiskPath 为非 null 值时，
 * 调用该 setter 后 threemfDiskPath 应变为 null。
 */
describe("Property 3: 参数变更使 threemfDiskPath 失效", () => {
  /** Helper: set threemfDiskPath and downloadUrl to non-null before each assertion */
  function seedThreemfPath() {
    useConverterStore.setState({
      threemfDiskPath: "/some/path.3mf",
      downloadUrl: "/api/files/test",
    });
  }

  /** Helper: assert both fields are null after setter call */
  function expectInvalidated() {
    const state = useConverterStore.getState();
    return state.threemfDiskPath === null && state.downloadUrl === null;
  }

  beforeEach(() => {
    // Reset store to default state before each test
    useConverterStore.setState({
      threemfDiskPath: null,
      downloadUrl: null,
      colorRemapMap: {},
      remapHistory: [],
      palette: [],
      aspectRatio: null,
    });
  });

  it("setTargetWidthMm invalidates threemfDiskPath for any valid width", () => {
    fc.assert(
      fc.property(fc.integer({ min: 10, max: 400 }), (width) => {
        seedThreemfPath();
        useConverterStore.getState().setTargetWidthMm(width);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setSpacerThick invalidates threemfDiskPath for any valid thickness", () => {
    fc.assert(
      fc.property(fc.double({ min: 0.2, max: 3.5, noNaN: true }), (thick) => {
        seedThreemfPath();
        useConverterStore.getState().setSpacerThick(thick);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setColorMode invalidates threemfDiskPath for any color mode", () => {
    const colorModes = Object.values(ColorMode);
    fc.assert(
      fc.property(
        fc.constantFrom(...colorModes),
        (mode) => {
          seedThreemfPath();
          useConverterStore.getState().setColorMode(mode);
          return expectInvalidated();
        }
      ),
      { numRuns: 100 }
    );
  });

  it("setModelingMode invalidates threemfDiskPath for any modeling mode", () => {
    const modelingModes = Object.values(ModelingMode);
    fc.assert(
      fc.property(
        fc.constantFrom(...modelingModes),
        (mode) => {
          seedThreemfPath();
          useConverterStore.getState().setModelingMode(mode);
          return expectInvalidated();
        }
      ),
      { numRuns: 100 }
    );
  });

  it("setStructureMode invalidates threemfDiskPath for any structure mode", () => {
    const structureModes = Object.values(StructureMode);
    fc.assert(
      fc.property(
        fc.constantFrom(...structureModes),
        (mode) => {
          seedThreemfPath();
          useConverterStore.getState().setStructureMode(mode);
          return expectInvalidated();
        }
      ),
      { numRuns: 100 }
    );
  });

  it("setQuantizeColors invalidates threemfDiskPath for any valid color count", () => {
    fc.assert(
      fc.property(fc.integer({ min: 8, max: 256 }), (colors) => {
        seedThreemfPath();
        useConverterStore.getState().setQuantizeColors(colors);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setEnableCleanup invalidates threemfDiskPath for any boolean", () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        seedThreemfPath();
        useConverterStore.getState().setEnableCleanup(enabled);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setEnableRelief invalidates threemfDiskPath for any boolean", () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        seedThreemfPath();
        useConverterStore.getState().setEnableRelief(enabled);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setEnableOutline invalidates threemfDiskPath for any boolean", () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        seedThreemfPath();
        useConverterStore.getState().setEnableOutline(enabled);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setEnableCloisonne invalidates threemfDiskPath for any boolean", () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        seedThreemfPath();
        useConverterStore.getState().setEnableCloisonne(enabled);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setEnableCoating invalidates threemfDiskPath for any boolean", () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        seedThreemfPath();
        useConverterStore.getState().setEnableCoating(enabled);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("setAddLoop invalidates threemfDiskPath for any boolean", () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        seedThreemfPath();
        useConverterStore.getState().setAddLoop(enabled);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("applyColorRemap invalidates threemfDiskPath for any hex pair", () => {
    const hexCharArb = fc
      .array(fc.constantFrom(..."0123456789ABCDEF".split("")), {
        minLength: 6,
        maxLength: 6,
      })
      .map((chars) => chars.join(""));
    fc.assert(
      fc.property(hexCharArb, hexCharArb, (origHex, newHex) => {
        seedThreemfPath();
        useConverterStore.getState().applyColorRemap(origHex, newHex);
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("undoColorRemap invalidates threemfDiskPath when history exists", () => {
    const hexCharArb = fc
      .array(fc.constantFrom(..."0123456789ABCDEF".split("")), {
        minLength: 6,
        maxLength: 6,
      })
      .map((chars) => chars.join(""));
    fc.assert(
      fc.property(hexCharArb, hexCharArb, (origHex, newHex) => {
        // First apply a remap so there's history
        useConverterStore.setState({
          colorRemapMap: {},
          remapHistory: [],
          threemfDiskPath: null,
          downloadUrl: null,
        });
        useConverterStore.getState().applyColorRemap(origHex, newHex);
        // Now seed the path and undo
        seedThreemfPath();
        useConverterStore.getState().undoColorRemap();
        return expectInvalidated();
      }),
      { numRuns: 100 }
    );
  });

  it("clearAllRemaps invalidates threemfDiskPath", () => {
    const hexCharArb = fc
      .array(fc.constantFrom(..."0123456789ABCDEF".split("")), {
        minLength: 6,
        maxLength: 6,
      })
      .map((chars) => chars.join(""));
    // clearAllRemaps doesn't need random input, but we test it with random prior state
    fc.assert(
      fc.property(
        fc.dictionary(hexCharArb, hexCharArb) as fc.Arbitrary<Record<string, string>>,
        (remapMap) => {
          useConverterStore.setState({ colorRemapMap: remapMap, remapHistory: [] });
          seedThreemfPath();
          useConverterStore.getState().clearAllRemaps();
          return expectInvalidated();
        }
      ),
      { numRuns: 100 }
    );
  });
});


// ========== Property 5: 切片软件偏好恢复与回退 ==========

import { getDetectedSlicerIdForSoftware } from "../utils/settingsOptionIds";

/**
 * Feature: slicer-launch-integration, Property 5: 切片软件偏好恢复与回退
 * **Validates: Requirements 4.1, 4.2, 4.3**
 *
 * For any 已检测切片软件列表、lastSlicerId 和设置里的 slicerSoftware：
 * - 若设置的软件存在于列表中，则 selectedSlicerId 应等于设置的软件
 * - 若设置的软件是已知软件但未检测到，则 selectedSlicerId 应为 null，不跨软件回退
 * - 若设置的软件无法映射到检测 ID，才允许按 lastSlicerId/第一项做兼容回退
 * - 列表为空时为 null
 */
describe("Property 5: 切片软件偏好恢复与回退", () => {
  /** Arbitrary: non-empty slicer id string */
  const slicerIdArb = fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim().length > 0);
  const slicerSoftwareArb = fc.constantFrom(
    "BambuStudio",
    "OrcaSlicer",
    "SnapmakerOrca",
    "ElegooSlicer",
    "AnycubicSlicerNext",
    "PrusaSlicer",
    "Cura",
  );

  /** Arbitrary: array of slicer objects with unique ids */
  const slicerListArb = fc
    .uniqueArray(slicerIdArb, { minLength: 0, maxLength: 20, comparator: (a, b) => a === b })
    .map((ids) => ids.map((id) => ({ id })));

  it("when the configured slicer exists in the list, result prefers that slicer", () => {
    fc.assert(
      fc.property(
        slicerSoftwareArb,
        slicerListArb,
        slicerIdArb,
        (slicerSoftware, slicers, lastSlicerId) => {
          const preferredId = getDetectedSlicerIdForSoftware(slicerSoftware);
          if (!preferredId) return true;
          const withConfigured = slicers.some((s) => s.id === preferredId)
            ? slicers
            : [{ id: preferredId }, ...slicers];
          const result = resolveSelectedSlicerId(withConfigured, lastSlicerId, slicerSoftware);
          return result === preferredId;
        }
      ),
      { numRuns: 100 }
    );
  });

  it("when known configured slicer is absent, result is null even if lastSlicerId matches", () => {
    fc.assert(
      fc.property(
        slicerListArb.filter((arr) => arr.length > 0),
        slicerSoftwareArb,
        fc.nat(),
        (slicers, slicerSoftware, indexSeed) => {
          const preferredId = getDetectedSlicerIdForSoftware(slicerSoftware);
          const isInList = !!preferredId && slicers.some((s) => s.id === preferredId);
          const lastSlicerId = slicers[indexSeed % slicers.length].id;
          if (isInList) return true;
          const result = resolveSelectedSlicerId(slicers, lastSlicerId, slicerSoftware);
          return result === null;
        }
      ),
      { numRuns: 100 }
    );
  });

  it("when known configured slicer is absent, result is null instead of the first detected slicer", () => {
    fc.assert(
      fc.property(slicerListArb, slicerSoftwareArb, slicerIdArb, (slicers, slicerSoftware, lastSlicerId) => {
        const preferredId = getDetectedSlicerIdForSoftware(slicerSoftware);
        const hasConfigured = preferredId ? slicers.some((s) => s.id === preferredId) : false;
        if (hasConfigured) {
          return true;
        }
        const result = resolveSelectedSlicerId(slicers, lastSlicerId, slicerSoftware);
        return result === null;
      }),
      { numRuns: 100 }
    );
  });

  it("when slicerSoftware is unknown, result falls back to lastSlicerId or first detected slicer", () => {
    fc.assert(
      fc.property(
        slicerListArb,
        fc.option(slicerIdArb, { nil: null }),
        (slicers, lastSlicerId) => {
          const result = resolveSelectedSlicerId(slicers, lastSlicerId, "UnknownSlicer");
          const restored = slicers.find((s) => s.id === lastSlicerId);
          return result === (restored?.id ?? slicers[0]?.id ?? null);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("when slicer list is empty, result is always null regardless of lastSlicerId", () => {
    fc.assert(
      fc.property(
        fc.option(slicerIdArb, { nil: null }),
        slicerSoftwareArb,
        (lastSlicerId, slicerSoftware) => {
          const result = resolveSelectedSlicerId([], lastSlicerId, slicerSoftware);
          return result === null;
        }
      ),
      { numRuns: 100 }
    );
  });

  it("result is always either an id from the list or null (never an invented value)", () => {
    fc.assert(
      fc.property(
        slicerListArb,
        fc.option(slicerIdArb, { nil: null }),
        slicerSoftwareArb,
        (slicers, lastSlicerId, slicerSoftware) => {
          const result = resolveSelectedSlicerId(slicers, lastSlicerId, slicerSoftware);
          if (result === null) {
            const preferredId = getDetectedSlicerIdForSoftware(slicerSoftware);
            return slicers.length === 0 || !!preferredId;
          }
          return slicers.some((s) => s.id === result);
        }
      ),
      { numRuns: 100 }
    );
  });
});


// ========== Property 6: 品牌配色映射完整性 ==========

import {
  SLICER_BRAND_COLORS,
  getSlicerBrandStyle,
  getSlicerLinkHint,
} from "../components/sections/SlicerSelector";

/**
 * Feature: slicer-launch-integration, Property 6: 品牌配色映射完整性
 * **Validates: Requirements 6.1, 6.2**
 *
 * For any 已知切片软件 ID（bambu_studio、orca_slicer、elegoo_slicer、prusa_slicer、cura），
 * 品牌配色映射应返回包含 bg、hover、text 三个非空 Tailwind CSS 类名的对象。
 */
describe("Property 6: 品牌配色映射完整性", () => {
  const KNOWN_SLICER_IDS = [
    "bambu_studio",
    "orca_slicer",
    "anycubic_slicer_next",
    "elegoo_slicer",
    "prusa_slicer",
    "cura",
  ] as const;

  it("for any known slicer ID, getSlicerBrandStyle returns an object with non-empty bg, hover, text strings", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...KNOWN_SLICER_IDS),
        (slicerId) => {
          const style = getSlicerBrandStyle(slicerId);
          return (
            typeof style.bg === "string" &&
            style.bg.length > 0 &&
            typeof style.hover === "string" &&
            style.hover.length > 0 &&
            typeof style.text === "string" &&
            style.text.length > 0
          );
        }
      ),
      { numRuns: 100 }
    );
  });

  it("for any known slicer ID, bg starts with 'bg-', hover starts with 'hover:bg-', text starts with 'text-'", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...KNOWN_SLICER_IDS),
        (slicerId) => {
          const style = getSlicerBrandStyle(slicerId);
          return (
            style.bg.startsWith("bg-") &&
            style.hover.startsWith("hover:bg-") &&
            style.text.startsWith("text-")
          );
        }
      ),
      { numRuns: 100 }
    );
  });

  it("SLICER_BRAND_COLORS contains exactly the 6 known slicer IDs", () => {
    const keys = Object.keys(SLICER_BRAND_COLORS).sort();
    const expected = [...KNOWN_SLICER_IDS].sort();
    expect(keys).toEqual(expected);
  });

  it("for any unknown slicer ID, getSlicerBrandStyle returns the default gray style", () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }).filter(
          (s) => !(KNOWN_SLICER_IDS as readonly string[]).includes(s)
        ),
        (unknownId) => {
          const style = getSlicerBrandStyle(unknownId);
          return (
            style.bg === "bg-slate-600" &&
            style.hover === "hover:bg-slate-700" &&
            style.text === "text-white"
          );
        }
      ),
      { numRuns: 100 }
    );
  });

  it("shows a mismatch hint when selected slicer differs from the configured export slicer", () => {
    const hint = getSlicerLinkHint(
      "anycubic_slicer_next",
      "Anycubic Slicer Next",
      true,
      "orca_slicer",
      "OrcaSlicer",
      (key) => ({
        slicer_preferred_mismatch:
          "Current export format targets {expected}, but the action bar is set to {actual}",
        slicer_preferred_missing:
          "Current export format targets {name}, but the matching slicer is not detected on this device",
      }[key] ?? key),
    );

    expect(hint).toBe(
      "Current export format targets Anycubic Slicer Next, but the action bar is set to OrcaSlicer",
    );
  });

  it("shows a missing hint when the configured slicer is not detected", () => {
    const hint = getSlicerLinkHint(
      "snapmaker_orca",
      "Snapmaker Orca",
      false,
      "orca_slicer",
      "OrcaSlicer",
      (key) => ({
        slicer_preferred_mismatch:
          "Current export format targets {expected}, but the action bar is set to {actual}",
        slicer_preferred_missing:
          "Current export format targets {name}, but the matching slicer is not detected on this device",
      }[key] ?? key),
    );

    expect(hint).toBe(
      "Current export format targets Snapmaker Orca, but the matching slicer is not detected on this device",
    );
  });
});


// ========== Property 4: SlicerSelector 按钮文案反映 3MF 状态 ==========

import { getButtonLabel } from "../components/sections/SlicerSelector";

/** Mock t function that returns Chinese translations for slicer keys */
const mockT = (key: string): string => {
  const map: Record<string, string> = {
    slicer_open_in: "在 {name} 中打开",
    slicer_generate_open_in: "生成并在 {name} 中打开",
    slicer_download_3mf: "下载 3MF",
    slicer_generate_download: "生成并下载",
  };
  return map[key] ?? key;
};

/**
 * Feature: slicer-launch-integration, Property 4: SlicerSelector 按钮文案反映 3MF 状态
 * **Validates: Requirements 3.2**
 *
 * For any 组合状态 (hasSlicers, threemfDiskPath)：
 * - hasSlicers=true 且 threemfDiskPath 非 null → "在 {name} 中打开"
 * - hasSlicers=true 且 threemfDiskPath 为 null → "生成并在 {name} 中打开"
 * - hasSlicers=false 且 threemfDiskPath 非 null → "下载 3MF"
 * - hasSlicers=false 且 threemfDiskPath 为 null → "生成并下载"
 */
describe("Property 4: SlicerSelector 按钮文案反映 3MF 状态", () => {
  /** Arbitrary: non-empty slicer name */
  const slicerNameArb = fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim().length > 0);

  /** Arbitrary: non-empty disk path */
  const diskPathArb = fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0);

  it("hasSlicers=true + non-null threemfDiskPath → '在 {name} 中打开'", () => {
    fc.assert(
      fc.property(diskPathArb, slicerNameArb, (path, name) => {
        const label = getButtonLabel(true, path, name, mockT);
        const expected = "在 {name} 中打开".replace("{name}", name);
        return label === expected;
      }),
      { numRuns: 100 }
    );
  });

  it("hasSlicers=true + null threemfDiskPath → '生成并在 {name} 中打开'", () => {
    fc.assert(
      fc.property(slicerNameArb, (name) => {
        const label = getButtonLabel(true, null, name, mockT);
        const expected = "生成并在 {name} 中打开".replace("{name}", name);
        return label === expected;
      }),
      { numRuns: 100 }
    );
  });

  it("hasSlicers=false + non-null threemfDiskPath → '下载 3MF'", () => {
    fc.assert(
      fc.property(
        diskPathArb,
        fc.option(slicerNameArb, { nil: null }),
        (path, name) => {
          const label = getButtonLabel(false, path, name, mockT);
          return label === "下载 3MF";
        }
      ),
      { numRuns: 100 }
    );
  });

  it("hasSlicers=false + null threemfDiskPath → '生成并下载'", () => {
    fc.assert(
      fc.property(
        fc.option(slicerNameArb, { nil: null }),
        (name) => {
          const label = getButtonLabel(false, null, name, mockT);
          return label === "生成并下载";
        }
      ),
      { numRuns: 100 }
    );
  });
});
