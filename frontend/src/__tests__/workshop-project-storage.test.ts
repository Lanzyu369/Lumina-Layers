import "fake-indexeddb/auto";

import { Blob as NodeBlob } from "node:buffer";
import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";

import {
  IndexedDbWorkshopProjectStorage,
  MemoryWorkshopProjectStorage,
  createWorkshopProjectStorage,
} from "../workshop/projectStorage";
import type { WorkshopProjectRecord } from "../workshop/types";

interface TestProject {
  label: string;
  source: Blob | null;
}

function record(
  moduleId: string,
  projectId: string,
  updatedAt: string,
  label = projectId,
): WorkshopProjectRecord<TestProject> {
  return {
    moduleId,
    projectId,
    schemaVersion: "test/v1",
    createdAt: "2026-07-30T00:00:00.000Z",
    updatedAt,
    project: {
      label,
      source: new NodeBlob([`source:${label}`], {
        type: "text/plain",
      }) as unknown as Blob,
    },
  };
}

function readBlobAsText(blob: Blob): Promise<string> {
  return (
    blob as Blob & {
      text(): Promise<string>;
    }
  ).text();
}

describe("IndexedDbWorkshopProjectStorage", () => {
  it("saves and loads a structured-clone project within its module namespace", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-save-load",
    );
    const stored = record(
      "lumina.bead-pattern",
      "project-1",
      "2026-07-30T01:00:00.000Z",
    );

    await storage.save(stored);

    const loaded = await storage.load<TestProject>(
      "lumina.bead-pattern",
      "project-1",
    );
    expect(loaded).toMatchObject({
      moduleId: "lumina.bead-pattern",
      projectId: "project-1",
      project: { label: "project-1" },
    });
    expect(
      await readBlobAsText(loaded?.project.source as Blob),
    ).toBe("source:project-1");
    expect(await storage.load("other.module", "project-1")).toBeNull();
  });

  it("returns the newest project from only the requested module", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-latest",
    );
    await storage.save(
      record(
        "lumina.bead-pattern",
        "older",
        "2026-07-30T01:00:00.000Z",
      ),
    );
    await storage.save(
      record(
        "other.module",
        "foreign-newest",
        "2026-07-30T03:00:00.000Z",
      ),
    );
    await storage.save(
      record(
        "lumina.bead-pattern",
        "newer",
        "2026-07-30T02:00:00.000Z",
      ),
    );

    expect(
      (await storage.latest("lumina.bead-pattern"))?.projectId,
    ).toBe("newer");
  });

  it("atomically replaces an existing project and removes it explicitly", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-replace-remove",
    );
    await storage.save(
      record(
        "lumina.bead-pattern",
        "project-1",
        "2026-07-30T01:00:00.000Z",
        "before",
      ),
    );
    await storage.save(
      record(
        "lumina.bead-pattern",
        "project-1",
        "2026-07-30T02:00:00.000Z",
        "after",
      ),
    );

    expect(
      (
        await storage.load<TestProject>(
          "lumina.bead-pattern",
          "project-1",
        )
      )?.project.label,
    ).toBe("after");

    await storage.remove("lumina.bead-pattern", "project-1");
    expect(
      await storage.load("lumina.bead-pattern", "project-1"),
    ).toBeNull();
  });
});

describe("MemoryWorkshopProjectStorage", () => {
  it("preserves the same namespace behavior for a session fallback", async () => {
    const storage = new MemoryWorkshopProjectStorage();
    await storage.save(
      record(
        "lumina.bead-pattern",
        "project-1",
        "2026-07-30T01:00:00.000Z",
      ),
    );

    expect(
      (await storage.latest("lumina.bead-pattern"))?.projectId,
    ).toBe("project-1");
    expect(await storage.latest("other.module")).toBeNull();
  });

  it("reports when IndexedDB is unavailable and supplies a memory store", () => {
    const result = createWorkshopProjectStorage(null);

    expect(result.persistent).toBe(false);
    expect(result.status).toBe("persistence-unavailable");
    expect(result.storage).toBeInstanceOf(MemoryWorkshopProjectStorage);
  });
});
