import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_STATE,
  getMaterialArchiveReliefMinimumTotalHeight,
  isDynamicMaterialActive,
  useConverterStore,
} from "../stores/converter";
import {
  DEFAULT_SETTINGS,
  useSettingsStore,
} from "../stores/settingsStore";

const STALE_DYNAMIC_RECIPE = { target_srgb: [1, 2, 3] };
const STALE_BENEFIT_POINT = { layer_cap: 7 };

function seedPreviewArtifacts(): void {
  useConverterStore.setState({
    sessionId: "stale-session",
    previewImageUrl: "/stale-preview.png",
    previewGlbUrl: "/stale-preview.glb",
    modelUrl: "/stale-model.glb",
    threemfDiskPath: "C:/stale/model.3mf",
    downloadUrl: "/stale-model.3mf",
    materialDynamicRecipes: [STALE_DYNAMIC_RECIPE],
    materialLayerBenefitCurve: [STALE_BENEFIT_POINT],
  } as never);
}

function expectPreviewArtifactsCleared(): void {
  expect(useConverterStore.getState()).toMatchObject({
    sessionId: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    modelUrl: null,
    threemfDiskPath: null,
    downloadUrl: null,
    materialDynamicRecipes: [],
    materialLayerBenefitCurve: [],
  });
}

describe("converter store dynamic material layer count", () => {
  beforeEach(() => {
    localStorage.clear();
    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "material",
      materialDynamicLayerCountEnabled: false,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 10,
      materialDynamicRecipes: [],
      materialLayerBenefitCurve: [],
      hue_enable: false,
    } as never);
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  it("ships disabled with the approved 5 to 10 layer range and empty results", () => {
    expect(DEFAULT_STATE).toMatchObject({
      materialDynamicLayerCountEnabled: false,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 10,
      materialDynamicRecipes: [],
      materialLayerBenefitCurve: [],
    });
  });

  it("treats dynamic matching as active only for material source", () => {
    expect(
      isDynamicMaterialActive({
        source_version: "material",
        materialDynamicLayerCountEnabled: true,
      }),
    ).toBe(true);
    expect(
      isDynamicMaterialActive({
        source_version: "legacy",
        materialDynamicLayerCountEnabled: true,
      }),
    ).toBe(false);
  });

  it("lets the edited minimum win, clamps it, raises maximum, and clears stale output", () => {
    useConverterStore.setState({
      materialMinLayerCount: 5,
      materialMaxLayerCount: 6,
    } as never);
    seedPreviewArtifacts();

    useConverterStore.getState().setMaterialMinLayerCount(9.6);

    expect(useConverterStore.getState()).toMatchObject({
      materialMinLayerCount: 10,
      materialMaxLayerCount: 10,
    });
    expectPreviewArtifactsCleared();
  });

  it("lets the edited maximum win, clamps it, lowers minimum, and clears stale output", () => {
    useConverterStore.setState({
      materialMinLayerCount: 9,
      materialMaxLayerCount: 10,
    } as never);
    seedPreviewArtifacts();

    useConverterStore.getState().setMaterialMaxLayerCount(4);

    expect(useConverterStore.getState()).toMatchObject({
      materialMinLayerCount: 5,
      materialMaxLayerCount: 5,
    });
    expectPreviewArtifactsCleared();
  });

  it("enables dynamic mode atomically, clears hue protection, and invalidates output", () => {
    useConverterStore.setState({ hue_enable: true });
    seedPreviewArtifacts();

    useConverterStore.getState().setMaterialDynamicLayerCountEnabled(true);

    expect(useConverterStore.getState()).toMatchObject({
      materialDynamicLayerCountEnabled: true,
      hue_enable: false,
    });
    expectPreviewArtifactsCleared();
  });

  it("refuses direct hue enable while active and clears stale hue on returning to material", () => {
    useConverterStore.setState({
      source_version: "material",
      materialDynamicLayerCountEnabled: true,
      hue_enable: false,
    } as never);

    useConverterStore.getState().setHueEnable(true);
    expect(useConverterStore.getState().hue_enable).toBe(false);

    useConverterStore.getState().setSourceVersion("legacy");
    expect(useConverterStore.getState().materialDynamicLayerCountEnabled).toBe(true);
    useConverterStore.getState().setHueEnable(true);
    expect(useConverterStore.getState().hue_enable).toBe(true);

    useConverterStore.getState().setSourceVersion("material");
    expect(useConverterStore.getState()).toMatchObject({
      materialDynamicLayerCountEnabled: true,
      hue_enable: false,
    });
  });

  it("uses dynamic maximum as material relief depth while fixed mode remains unchanged", () => {
    expect(
      getMaterialArchiveReliefMinimumTotalHeight({
        source_version: "material",
        materialLayerCount: 5,
        materialDynamicLayerCountEnabled: true,
        materialMaxLayerCount: 9,
        spacer_thick: 0.2,
      }),
    ).toBeCloseTo(0.72, 10);
    expect(
      getMaterialArchiveReliefMinimumTotalHeight({
        source_version: "material",
        materialLayerCount: 5,
        materialDynamicLayerCountEnabled: false,
        materialMaxLayerCount: 9,
        spacer_thick: 0.2,
      }),
    ).toBeCloseTo(0.4, 10);
  });

  it("invalidates an active dynamic preview when tolerance changes", () => {
    useConverterStore.setState({
      source_version: "material",
      materialDynamicLayerCountEnabled: true,
    } as never);
    seedPreviewArtifacts();

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(0.8);

    expectPreviewArtifactsCleared();
  });

  it("preserves an unrelated preview when tolerance changes outside active dynamic material mode", () => {
    useConverterStore.setState({
      source_version: "legacy",
      materialDynamicLayerCountEnabled: true,
    } as never);
    seedPreviewArtifacts();

    useSettingsStore.getState().setMaterialDeltaE00Tolerance(0.8);

    expect(useConverterStore.getState()).toMatchObject({
      sessionId: "stale-session",
      previewImageUrl: "/stale-preview.png",
      modelUrl: "/stale-model.glb",
      materialDynamicRecipes: [STALE_DYNAMIC_RECIPE],
      materialLayerBenefitCurve: [STALE_BENEFIT_POINT],
    });
  });
  it("keeps fixed-mode backing selection behavior unchanged", () => {
    useConverterStore.setState({
      source_version: "material",
      materialDynamicLayerCountEnabled: false,
    } as never);
    seedPreviewArtifacts();

    useConverterStore
      .getState()
      .setMaterialBackingMaterialDirName("brand/pla-blue");

    expect(useConverterStore.getState()).toMatchObject({
      materialBackingMaterialDirName: "brand/pla-blue",
      sessionId: "stale-session",
      previewImageUrl: "/stale-preview.png",
      materialDynamicRecipes: [STALE_DYNAMIC_RECIPE],
      materialLayerBenefitCurve: [STALE_BENEFIT_POINT],
    });
  });
});
