import { describe, expect, it } from "vitest";

import {
  validateWorkshopModules,
  type WorkshopModuleDisabledReason,
} from "../workshop/registry";
import type {
  WorkshopCapability,
  WorkshopModuleDefinition,
  WorkshopModuleManifest,
} from "../workshop/types";

const validManifest: WorkshopModuleManifest = {
  manifestSchemaVersion: 1,
  id: "lumina.bead-pattern",
  name: { zh: "拼豆模式", en: "Bead Pattern" },
  description: { zh: "读取拼豆图纸", en: "Read bead patterns" },
  author: "Lumina Studio",
  version: "1.0.0",
  icon: "bead-grid",
  minLuminaVersion: "2.0.0",
  inputKinds: ["image/png", "image/jpeg", "image/webp"],
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

function definition(
  manifest: WorkshopModuleManifest,
): WorkshopModuleDefinition {
  return {
    manifest,
    Component: () => null,
  };
}

function expectDisabled(
  manifest: WorkshopModuleManifest,
  reason: WorkshopModuleDisabledReason,
  options: {
    appVersion?: string;
    whitelist?: ReadonlySet<string>;
  } = {},
): void {
  const [record] = validateWorkshopModules([definition(manifest)], {
    appVersion: options.appVersion ?? "2.0.0",
    whitelist:
      options.whitelist ?? new Set<string>(["lumina.bead-pattern"]),
  });

  expect(record).toEqual(
    expect.objectContaining({
      enabled: false,
      reason,
    }),
  );
}

describe("validateWorkshopModules", () => {
  it("enables a valid whitelisted built-in module", () => {
    expect(
      validateWorkshopModules([definition(validManifest)], {
        appVersion: "2.0.0",
        whitelist: new Set(["lumina.bead-pattern"]),
      }),
    ).toEqual([
      expect.objectContaining({
        definition: expect.objectContaining({ manifest: validManifest }),
        enabled: true,
        reason: null,
      }),
    ]);
  });

  it("disables every definition that shares a duplicate ID", () => {
    const duplicate = definition({
      ...validManifest,
      name: { zh: "另一个模块", en: "Another module" },
    });

    const records = validateWorkshopModules(
      [definition(validManifest), duplicate],
      {
        appVersion: "2.0.0",
        whitelist: new Set(["lumina.bead-pattern"]),
      },
    );

    expect(records).toHaveLength(2);
    expect(records.every((record) => !record.enabled)).toBe(true);
    expect(records.map((record) => record.reason)).toEqual([
      "duplicate-id",
      "duplicate-id",
    ]);
  });

  it("fails closed for a capability the host does not know", () => {
    expectDisabled(
      {
        ...validManifest,
        capabilities: [
          ...validManifest.capabilities,
          "network.fetch" as WorkshopCapability,
        ],
      },
      "unknown-capability",
    );
  });

  it("rejects unsupported manifest schema versions", () => {
    expectDisabled(
      {
        ...validManifest,
        manifestSchemaVersion: 2 as 1,
      },
      "unsupported-manifest",
    );
  });

  it("rejects malformed semantic versions", () => {
    expectDisabled(
      {
        ...validManifest,
        version: "v1",
      },
      "invalid-manifest",
    );
  });

  it("compares minimum Lumina versions numerically", () => {
    expectDisabled(
      {
        ...validManifest,
        minLuminaVersion: "2.10.0",
      },
      "app-version-too-old",
      { appVersion: "2.9.9" },
    );
  });

  it("rejects modules absent from the source whitelist", () => {
    expectDisabled(validManifest, "not-whitelisted", {
      whitelist: new Set(),
    });
  });
});
