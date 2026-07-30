import "fake-indexeddb/auto";

import { Blob as NodeBlob } from "node:buffer";
import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";

import {
  IndexedDbWorkshopProjectStorage,
  MemoryWorkshopProjectStorage,
  WORKSHOP_MODULE_QUOTA_BYTES,
  WORKSHOP_RECIPE_QUOTA_BYTES,
  WORKSHOP_RECORD_QUOTA_BYTES,
  WorkshopProjectStorageError,
  assertWorkshopRecipeEnvelopeWithinQuota,
  createWorkshopProjectStorage,
  estimateStoredBytes,
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

function recordWithPayload(
  moduleId: string,
  projectId: string,
  project: unknown,
): WorkshopProjectRecord<unknown> {
  return {
    moduleId,
    projectId,
    schemaVersion: "fixture/v1",
    createdAt: "2026-07-30T00:00:00.000Z",
    updatedAt: "2026-07-30T01:00:00.000Z",
    project,
  };
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

  it("rejects a write above the configured module quota", async () => {
    const first = recordWithPayload(
      "fixture.hello",
      "one",
      new Uint8Array(32),
    );
    const second = recordWithPayload(
      "fixture.hello",
      "two",
      new Uint8Array(48),
    );
    const firstBytes = estimateStoredBytes(first);
    const secondBytes = estimateStoredBytes(second);
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-module-quota",
      {
        moduleQuotaBytes: firstBytes + secondBytes - 1,
        recordQuotaBytes: Math.max(firstBytes, secondBytes),
      },
    );

    await storage.save(first);

    await expect(storage.save(second)).rejects.toMatchObject({
      code: "project-quota-exceeded",
    });
    expect(await storage.load("fixture.hello", "one")).not.toBeNull();
    expect(await storage.load("fixture.hello", "two")).toBeNull();
  });

  it("accepts the exact record boundary and rejects one byte above it", async () => {
    const allowed = recordWithPayload(
      "fixture.hello",
      "allowedx",
      new Uint8Array(8),
    );
    const denied = recordWithPayload(
      "fixture.hello",
      "deniedxx",
      new Uint8Array(9),
    );
    const allowedBytes = estimateStoredBytes(allowed);
    const deniedBytes = estimateStoredBytes(denied);
    expect(deniedBytes).toBe(allowedBytes + 1);
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-record-quota",
      {
        moduleQuotaBytes: allowedBytes + deniedBytes,
        recordQuotaBytes: allowedBytes,
      },
    );

    await storage.save(allowed);

    await expect(storage.save(denied)).rejects.toMatchObject({
      code: "project-record-too-large",
      limitBytes: allowedBytes,
      actualBytes: deniedBytes,
    });
  });

  it("restores a pre-update snapshot without touching another module", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-snapshot-restore",
    );
    await storage.save(
      recordWithPayload("fixture.hello", "p1", "before"),
    );
    await storage.save(
      recordWithPayload("other.module", "p1", "foreign"),
    );
    const snapshotId = await storage.snapshotModule(
      "fixture.hello",
      "1.0.0",
    );
    await storage.save(
      recordWithPayload("fixture.hello", "p1", "after"),
    );
    await storage.save(
      recordWithPayload("fixture.hello", "new", "remove-me"),
    );

    await storage.restoreSnapshot("fixture.hello", snapshotId);

    expect(
      (await storage.load("fixture.hello", "p1"))?.project,
    ).toBe("before");
    expect(await storage.load("fixture.hello", "new")).toBeNull();
    expect(
      (await storage.load("other.module", "p1"))?.project,
    ).toBe("foreign");
  });

  it("keeps current projects when a snapshot does not exist", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-snapshot-missing",
    );
    await storage.save(
      recordWithPayload("fixture.hello", "p1", "current"),
    );

    await expect(
      storage.restoreSnapshot("fixture.hello", "missing"),
    ).rejects.toMatchObject({
      code: "project-snapshot-not-found",
    });

    expect(
      (await storage.load("fixture.hello", "p1"))?.project,
    ).toBe("current");
  });

  it("deletes snapshots and module projects only when explicitly requested", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-explicit-delete",
    );
    await storage.save(
      recordWithPayload("fixture.hello", "p1", "fixture"),
    );
    await storage.save(
      recordWithPayload("other.module", "p1", "foreign"),
    );
    const snapshotId = await storage.snapshotModule(
      "fixture.hello",
      "1.0.0",
    );

    await storage.deleteSnapshot("fixture.hello", snapshotId);
    await expect(
      storage.restoreSnapshot("fixture.hello", snapshotId),
    ).rejects.toMatchObject({
      code: "project-snapshot-not-found",
    });

    const secondSnapshot = await storage.snapshotModule(
      "fixture.hello",
      "1.0.0",
    );
    expect(secondSnapshot).not.toBe(snapshotId);
    await storage.deleteModuleProjects("fixture.hello");

    expect(await storage.load("fixture.hello", "p1")).toBeNull();
    expect(
      (await storage.load("other.module", "p1"))?.project,
    ).toBe("foreign");
    await expect(
      storage.restoreSnapshot("fixture.hello", secondSnapshot),
    ).rejects.toMatchObject({
      code: "project-snapshot-not-found",
    });
  });

  it("rejects cyclic and non-cloneable values before mutating storage", async () => {
    const storage = new IndexedDbWorkshopProjectStorage(
      new IDBFactory(),
      "workshop-storage-invalid-values",
    );
    const cyclic: { self?: unknown } = {};
    cyclic.self = cyclic;

    await expect(
      storage.save(
        recordWithPayload("fixture.hello", "cyclic", cyclic),
      ),
    ).rejects.toMatchObject({
      code: "project-value-invalid",
    });
    await expect(
      storage.save(
        recordWithPayload(
          "fixture.hello",
          "function",
          () => undefined,
        ),
      ),
    ).rejects.toMatchObject({
      code: "project-value-invalid",
    });

    expect(await storage.latest("fixture.hello")).toBeNull();
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

  it("supports the same snapshot and explicit-delete lifecycle", async () => {
    const storage = new MemoryWorkshopProjectStorage();
    await storage.save(
      recordWithPayload("fixture.hello", "p1", "before"),
    );
    const snapshotId = await storage.snapshotModule(
      "fixture.hello",
      "1.0.0",
    );
    await storage.save(
      recordWithPayload("fixture.hello", "p1", "after"),
    );

    await storage.restoreSnapshot("fixture.hello", snapshotId);
    expect(
      (await storage.load("fixture.hello", "p1"))?.project,
    ).toBe("before");

    await storage.deleteModuleProjects("fixture.hello");
    expect(await storage.latest("fixture.hello")).toBeNull();
  });
});

describe("Workshop project byte limits", () => {
  it("keeps the v1 production limits fixed", () => {
    expect(WORKSHOP_MODULE_QUOTA_BYTES).toBe(256 * 1024 * 1024);
    expect(WORKSHOP_RECORD_QUOTA_BYTES).toBe(64 * 1024 * 1024);
    expect(WORKSHOP_RECIPE_QUOTA_BYTES).toBe(1024 * 1024);
  });

  it("counts strings, blobs, buffers, typed arrays, arrays, and records", () => {
    expect(estimateStoredBytes("é")).toBe(2);
    expect(estimateStoredBytes(new ArrayBuffer(4))).toBe(4);
    expect(estimateStoredBytes(new Uint8Array(3))).toBe(3);
    expect(
      estimateStoredBytes(
        new NodeBlob(["12345"]) as unknown as Blob,
      ),
    ).toBe(5);
    expect(estimateStoredBytes(["a", "bc"])).toBeGreaterThan(3);
    expect(estimateStoredBytes({ label: "value" })).toBeGreaterThan(
      estimateStoredBytes("value"),
    );
  });

  it("enforces the exact recipe-envelope boundary", () => {
    expect(() =>
      assertWorkshopRecipeEnvelopeWithinQuota(
        "x".repeat(WORKSHOP_RECIPE_QUOTA_BYTES),
      ),
    ).not.toThrow();
    expect(() =>
      assertWorkshopRecipeEnvelopeWithinQuota(
        "x".repeat(WORKSHOP_RECIPE_QUOTA_BYTES + 1),
      ),
    ).toThrowError(
      expect.objectContaining({
        code: "project-recipe-too-large",
      }),
    );
  });

  it("exposes typed quota failures for host-side rendering", () => {
    const error = new WorkshopProjectStorageError(
      "project-quota-exceeded",
      "quota",
      10,
      11,
    );

    expect(error).toMatchObject({
      name: "WorkshopProjectStorageError",
      code: "project-quota-exceeded",
      limitBytes: 10,
      actualBytes: 11,
    });
  });
});
