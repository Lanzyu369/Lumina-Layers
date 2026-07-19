import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { translations } from "../i18n/translations";
import ActionBar from "../components/sections/ActionBar";
import {
  CONVERTER_ERROR_KEYS,
  DEFAULT_STATE,
  useConverterStore,
} from "../stores/converter";

vi.mock("../i18n/context", () => ({
  useI18n: () => ({
    lang: "en" as const,
    t: (key: string) => translations[key]?.en ?? key,
  }),
}));

vi.mock("../components/sections/BedSizeSelector", () => ({
  default: () => null,
}));

vi.mock("../components/sections/SlicerSelector", () => ({
  default: () => null,
}));

vi.mock("../components/ui/CanvasPreviewSurface", () => ({
  default: () => null,
}));

vi.mock("../components/ui/LayerMaskViewerDialog", () => ({
  default: () => null,
}));

vi.mock("../components/ui/PreviewHoverInspector", () => ({
  default: () => null,
}));

vi.mock("../recipe/importFlow", () => ({
  exportShareCard: vi.fn(),
  exportSidecar: vi.fn(),
}));

describe("converter relief error language", () => {
  beforeEach(() => {
    useConverterStore.setState({ ...DEFAULT_STATE });
  });

  it("renders the heightmap guard in English through ActionBar", async () => {
    useConverterStore.setState({
      sessionId: "session-relief",
      source_version: "legacy",
      lut_name: "legacy-lut",
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      color_height_map: {},
    });

    await act(async () => {
      await useConverterStore.getState().submitGenerate();
    });

    expect(useConverterStore.getState().error).toBe(
      CONVERTER_ERROR_KEYS.heightmapUploadRequired,
    );

    render(<ActionBar />);

    expect(
      screen.getByText(
        translations[CONVERTER_ERROR_KEYS.heightmapUploadRequired].en,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        translations[CONVERTER_ERROR_KEYS.heightmapUploadRequired].zh,
      ),
    ).not.toBeInTheDocument();
  });
});
