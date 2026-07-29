import { describe, expect, it, vi } from "vitest";

import {
  WorkshopHostError,
  createWorkshopHostServices,
} from "../workshop/host";
import type {
  WorkshopFileServices,
  WorkshopModuleManifest,
  WorkshopProjectRecord,
  WorkshopProjectStorage,
} from "../workshop/types";

const MANIFEST: WorkshopModuleManifest = {
  manifestSchemaVersion: 1,
  id: "lumina.bead-pattern",
  name: { zh: "拼豆模式", en: "Bead Pattern" },
  description: { zh: "读取拼豆图纸", en: "Read bead patterns" },
  author: "Lumina Studio",
  version: "1.0.0",
  icon: "bead-grid",
  minLuminaVersion: "2.0.0",
  inputKinds: ["image/png"],
  outputKinds: ["image/png"],
  capabilities: [
    "file.pick-image",
    "project.read-write",
    "handoff.image",
    "ui.theme",
    "ui.locale",
    "status.progress",
    "status.error",
  ],
};

function projectStorage(): WorkshopProjectStorage {
  return {
    save: vi.fn(),
    load: vi.fn().mockResolvedValue(null),
    latest: vi.fn().mockResolvedValue(null),
    remove: vi.fn(),
  };
}

function fileServices(): WorkshopFileServices {
  return {
    pickImage: vi.fn().mockResolvedValue(null),
    decodeImage: vi.fn(),
    encodePng: vi.fn(),
  };
}

function dependencies(
  storage: WorkshopProjectStorage,
  files = fileServices(),
) {
  return {
    storage,
    files,
    getLocale: () => "zh" as const,
    getTheme: () => "dark" as const,
    translate: (key: string) => key,
    onProgress: vi.fn(),
    onError: vi.fn(),
    onDiagnostics: vi.fn(),
    handoffImage: vi.fn(),
  };
}

describe("createWorkshopHostServices", () => {
  it("forces project writes and reads into the manifest module namespace", async () => {
    const storage = projectStorage();
    const deps = {
      ...dependencies(storage),
      onProjectSaved: vi.fn(),
    };
    const host = createWorkshopHostServices(
      MANIFEST,
      deps,
    );
    const record: Omit<WorkshopProjectRecord<{ value: number }>, "moduleId"> = {
      projectId: "project-1",
      schemaVersion: "test/v1",
      createdAt: "2026-07-30T00:00:00.000Z",
      updatedAt: "2026-07-30T00:00:00.000Z",
      project: { value: 1 },
    };

    await host.projects.save(record);
    await host.projects.load("project-1");
    await host.projects.latest();
    await host.projects.remove("project-1");

    expect(storage.save).toHaveBeenCalledWith({
      ...record,
      moduleId: "lumina.bead-pattern",
    });
    expect(storage.load).toHaveBeenCalledWith(
      "lumina.bead-pattern",
      "project-1",
    );
    expect(storage.latest).toHaveBeenCalledWith("lumina.bead-pattern");
    expect(storage.remove).toHaveBeenCalledWith(
      "lumina.bead-pattern",
      "project-1",
    );
    expect(deps.onProjectSaved).toHaveBeenCalledWith(
      "lumina.bead-pattern",
      "project-1",
    );
  });

  it("scopes diagnostics to the manifest identity", () => {
    const deps = dependencies(projectStorage());
    const host = createWorkshopHostServices(MANIFEST, deps);
    const summary = {
      projectSchemaVersion: "bead-project/v1",
      inputMode: "numbered-grid",
      rows: 52,
      columns: 52,
      compression: 50,
      errorCode: null,
    };

    host.status.reportDiagnostics(summary);

    expect(deps.onDiagnostics).toHaveBeenCalledWith(
      "lumina.bead-pattern",
      "1.0.0",
      summary,
    );
  });

  it("denies a service when the manifest did not request its capability", async () => {
    const files = fileServices();
    const host = createWorkshopHostServices(
      {
        ...MANIFEST,
        capabilities: MANIFEST.capabilities.filter(
          (capability) => capability !== "file.pick-image",
        ),
      },
      dependencies(projectStorage(), files),
    );

    await expect(host.files.pickImage()).rejects.toMatchObject({
      code: "capability-denied",
    } satisfies Partial<WorkshopHostError>);
    expect(files.pickImage).not.toHaveBeenCalled();
  });
});
