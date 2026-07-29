import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { translations } from "../i18n/translations";
import { BeadWorkshopModule } from "../workshop/modules/bead/BeadWorkshopModule";
import { BEAD_WORKSHOP_MANIFEST } from "../workshop/modules/bead/manifest";
import { renderBeadProject } from "../workshop/modules/bead/renderer";
import type {
  BeadProcessingEngine,
} from "../workshop/modules/bead/BeadWorkshopModule";
import type {
  BeadProject,
  PatternClassification,
  RecognitionResult,
} from "../workshop/modules/bead/types";
import type {
  WorkshopHostServices,
  WorkshopProjectRecord,
  WorkshopRaster,
} from "../workshop/types";

const t = (key: string) => translations[key]?.zh ?? key;

function sourceRaster(): WorkshopRaster {
  const data = new Uint8ClampedArray(4 * 4 * 4);
  data.fill(255);
  return { width: 4, height: 4, data };
}

class FakeEngine implements BeadProcessingEngine {
  private nextId = 1;

  readonly dispose = vi.fn();

  cancelBefore(): void {}

  cancel(): void {}

  classify() {
    const result: PatternClassification = {
      mode: "hard-pixel",
      confidence: 0.94,
      scores: {
        "numbered-grid": 0.1,
        "hard-pixel": 0.94,
        "ring-preview": 0.1,
      },
    };
    return { id: this.nextId++, promise: Promise.resolve(result) };
  }

  recognize() {
    const result: RecognitionResult = {
      mode: "hard-pixel",
      rows: 2,
      columns: 2,
      palette: [
        [230, 40, 50],
        [20, 120, 210],
      ],
      cells: [
        { kind: "color", paletteIndex: 0 },
        { kind: "color", paletteIndex: 1 },
        { kind: "empty" },
        { kind: "transparent-support" },
      ],
      confidenceIssues: [],
    };
    return { id: this.nextId++, promise: Promise.resolve(result) };
  }

  render(project: BeadProject, compression: number, pixelsPerCell: number) {
    return {
      id: this.nextId++,
      promise: Promise.resolve(
        renderBeadProject(project, {
          compression,
          pixelsPerCell,
        }),
      ),
    };
  }
}

function fakeHost(
  latest: WorkshopProjectRecord<BeadProject> | null = null,
) {
  const save = vi.fn<
    (
      record: Omit<
        WorkshopProjectRecord<BeadProject>,
        "moduleId"
      >,
    ) => Promise<void>
  >().mockResolvedValue(undefined);
  const host: WorkshopHostServices = {
    files: {
      pickImage: vi.fn().mockResolvedValue({
        file: new File(["pattern"], "pattern.png", {
          type: "image/png",
        }),
        raster: sourceRaster(),
      }),
      decodeImage: vi.fn().mockResolvedValue(sourceRaster()),
      encodePng: vi.fn(),
    },
    projects: {
      save,
      load: vi.fn().mockResolvedValue(null),
      latest: vi.fn().mockResolvedValue(latest),
      remove: vi.fn(),
    },
    ui: {
      getLocale: () => "zh",
      getTheme: () => "light",
      translate: t,
    },
    status: {
      reportProgress: vi.fn(),
      reportError: vi.fn(),
      reportDiagnostics: vi.fn(),
    },
    handoffImage: vi.fn(),
  };
  return { host, save };
}

describe("BeadWorkshopModule", () => {
  beforeEach(() => {
    vi.spyOn(
      HTMLCanvasElement.prototype,
      "getContext",
    ).mockReturnValue(null);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:pattern"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("runs upload, calibration, recognition, editing, and autosave locally", async () => {
    const { host, save } = fakeHost();
    const engine = new FakeEngine();
    render(
      <BeadWorkshopModule
        manifest={BEAD_WORKSHOP_MANIFEST}
        host={host}
        pendingRecipeSource={null}
        clearPendingRecipe={vi.fn()}
        createEngine={() => engine}
        autosaveDelayMs={0}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "选择拼豆图纸" }),
    );
    expect(
      await screen.findByRole("heading", { name: "校准图纸" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "图中没有空位" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "识别拼豆矩阵" }),
    );

    expect(
      await screen.findByRole("heading", { name: "编辑拼豆矩阵" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(save).toHaveBeenCalled());
    const saved = save.mock.calls.at(-1)?.[0];
    expect(saved?.project).toMatchObject({
      rows: 2,
      columns: 2,
      compression: 50,
    });
    expect(saved?.project.source?.fileName).toBe("pattern.png");
  });

  it("resumes the latest local project and disposes its engine on unmount", async () => {
    const first = fakeHost();
    const firstEngine = new FakeEngine();
    const firstRender = render(
      <BeadWorkshopModule
        manifest={BEAD_WORKSHOP_MANIFEST}
        host={first.host}
        pendingRecipeSource={null}
        clearPendingRecipe={vi.fn()}
        createEngine={() => firstEngine}
        autosaveDelayMs={0}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "选择拼豆图纸" }),
    );
    await screen.findByRole("heading", { name: "校准图纸" });
    fireEvent.click(
      screen.getByRole("button", { name: "图中没有空位" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "识别拼豆矩阵" }),
    );
    await screen.findByRole("heading", { name: "编辑拼豆矩阵" });
    await waitFor(() => expect(first.save).toHaveBeenCalled());
    const saved = first.save.mock.calls.at(-1)?.[0];
    firstRender.unmount();
    expect(firstEngine.dispose).toHaveBeenCalledTimes(1);

    const record: WorkshopProjectRecord<BeadProject> = {
      moduleId: BEAD_WORKSHOP_MANIFEST.id,
      projectId: saved?.projectId ?? "saved",
      schemaVersion: saved?.schemaVersion ?? "bead-project/v1",
      createdAt:
        saved?.createdAt ?? "2026-07-30T00:00:00.000Z",
      updatedAt:
        saved?.updatedAt ?? "2026-07-30T00:00:00.000Z",
      project: saved?.project as BeadProject,
    };
    const resumed = fakeHost(record);
    const resumedEngine = new FakeEngine();
    render(
      <BeadWorkshopModule
        manifest={BEAD_WORKSHOP_MANIFEST}
        host={resumed.host}
        pendingRecipeSource={null}
        clearPendingRecipe={vi.fn()}
        createEngine={() => resumedEngine}
        autosaveDelayMs={0}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "编辑拼豆矩阵" }),
    ).toBeInTheDocument();
    expect(screen.getByText("已恢复本机项目")).toBeInTheDocument();
  });

  it("renders an exact handoff and confirms before replacing converter content", async () => {
    const { host } = fakeHost();
    const outputFile = new File(["rendered"], "bead.png", {
      type: "image/png",
    });
    vi.mocked(host.files.encodePng).mockResolvedValue(outputFile);
    vi.mocked(host.handoffImage)
      .mockResolvedValueOnce({ status: "needs-confirmation" })
      .mockResolvedValueOnce({ status: "completed" });

    render(
      <BeadWorkshopModule
        manifest={BEAD_WORKSHOP_MANIFEST}
        host={host}
        pendingRecipeSource={null}
        clearPendingRecipe={vi.fn()}
        createEngine={() => new FakeEngine()}
        autosaveDelayMs={0}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "选择拼豆图纸" }),
    );
    await screen.findByRole("heading", { name: "校准图纸" });
    fireEvent.click(
      screen.getByRole("button", { name: "图中没有空位" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "识别拼豆矩阵" }),
    );
    await screen.findByRole("heading", { name: "编辑拼豆矩阵" });

    fireEvent.click(
      screen.getByRole("button", { name: "交给 Lumina 转换" }),
    );

    expect(
      await screen.findByRole("dialog", {
        name: "替换当前转换内容？",
      }),
    ).toBeInTheDocument();
    expect(host.files.encodePng).toHaveBeenCalledWith(
      expect.objectContaining({
        width: 64,
        height: 64,
        pixelsPerCell: 32,
      }),
      expect.stringMatching(/^bead-.+\.png$/),
    );
    expect(host.handoffImage).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        file: outputFile,
        pixelWidth: 64,
        pixelHeight: 64,
        recommendedWidthMm: 5.2,
        recommendedHeightMm: 5.2,
        rows: 2,
        columns: 2,
        beadPitchMm: 2.6,
        preserveCanvasBounds: true,
        recipeSource: expect.objectContaining({
          projectSchemaVersion: "bead-project/v1",
          renderSchemaVersion: "bead-render/v1",
        }),
      }),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "替换并继续" }),
    );
    await waitFor(() =>
      expect(host.handoffImage).toHaveBeenNthCalledWith(
        2,
        expect.objectContaining({ file: outputFile }),
        { replaceExisting: true },
      ),
    );
  });
});
