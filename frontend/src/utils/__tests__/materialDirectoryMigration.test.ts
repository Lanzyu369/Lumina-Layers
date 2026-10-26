import { describe, expect, it } from "vitest";

import {
  buildLegacyDirectoryNameMap,
  reconcileDirectoryNames,
} from "../materialDirectoryMigration";

const lib = (names: string[]) => names.map((directory_name) => ({ directory_name }));

describe("buildLegacyDirectoryNameMap", () => {
  it("maps a legacy flat name to the unique nested directory_name", () => {
    const map = buildLegacyDirectoryNameMap(
      lib(["瑞贝思/瑞贝思 PLA 白", "瑞贝思/瑞贝思 PLA 黑", "Legacy Flat"]),
    );
    expect(map.get("瑞贝思 PLA 白")).toBe("瑞贝思/瑞贝思 PLA 白");
    expect(map.get("瑞贝思 PLA 黑")).toBe("瑞贝思/瑞贝思 PLA 黑");
    // Flat entries do not produce legacy mappings.
    expect(map.has("Legacy Flat")).toBe(false);
  });

  it("skips ambiguous tails to avoid silently picking the wrong archive", () => {
    const map = buildLegacyDirectoryNameMap(
      lib(["BrandA/Shared", "BrandB/Shared", "BrandA/Unique"]),
    );
    expect(map.has("Shared")).toBe(false);
    expect(map.get("Unique")).toBe("BrandA/Unique");
  });
});

describe("reconcileDirectoryNames", () => {
  it("returns unchanged when every selection matches an existing directory_name", () => {
    const result = reconcileDirectoryNames(
      ["瑞贝思/瑞贝思 PLA 白"],
      lib(["瑞贝思/瑞贝思 PLA 白", "瑞贝思/瑞贝思 PLA 黑"]),
    );
    expect(result.changed).toBe(false);
    expect(result.names).toEqual(["瑞贝思/瑞贝思 PLA 白"]);
  });

  it("substitutes legacy flat names with their unique nested equivalent and marks changed", () => {
    const result = reconcileDirectoryNames(
      ["瑞贝思 PLA 白", "瑞贝思 PLA 黑"],
      lib(["瑞贝思/瑞贝思 PLA 白", "瑞贝思/瑞贝思 PLA 黑"]),
    );
    expect(result.changed).toBe(true);
    expect(result.names).toEqual([
      "瑞贝思/瑞贝思 PLA 白",
      "瑞贝思/瑞贝思 PLA 黑",
    ]);
  });

  it("drops entries that cannot be resolved", () => {
    const result = reconcileDirectoryNames(
      ["瑞贝思 PLA 白", "does not exist"],
      lib(["瑞贝思/瑞贝思 PLA 白"]),
    );
    expect(result.changed).toBe(true);
    expect(result.names).toEqual(["瑞贝思/瑞贝思 PLA 白"]);
  });

  it("drops ambiguous legacy names rather than guessing", () => {
    const result = reconcileDirectoryNames(
      ["Shared"],
      lib(["BrandA/Shared", "BrandB/Shared"]),
    );
    expect(result.changed).toBe(true);
    expect(result.names).toEqual([]);
  });

  it("preserves order of resolvable entries", () => {
    const result = reconcileDirectoryNames(
      ["B", "瑞贝思 PLA 白", "A"],
      lib(["A", "B", "瑞贝思/瑞贝思 PLA 白"]),
    );
    expect(result.changed).toBe(true);
    expect(result.names).toEqual(["B", "瑞贝思/瑞贝思 PLA 白", "A"]);
  });

  it("migrates selections for the renamed Karvax brand", () => {
    const result = reconcileDirectoryNames(
      ["无境新材/无境新材 PLA 耀石黑", "无境新材/品红_20260428_205254"],
      lib(["Karvax/Karvax PLA 耀石黑", "Karvax/品红_20260428_205254"]),
    );

    expect(result.changed).toBe(true);
    expect(result.names).toEqual([
      "Karvax/Karvax PLA 耀石黑",
      "Karvax/品红_20260428_205254",
    ]);
  });

  it("migrates flat selections saved before the Karvax brand subdirectory", () => {
    const result = reconcileDirectoryNames(
      ["无境新材 PLA 耀石黑"],
      lib(["Karvax/Karvax PLA 耀石黑"]),
    );

    expect(result.changed).toBe(true);
    expect(result.names).toEqual(["Karvax/Karvax PLA 耀石黑"]);
  });

  it("short-circuits on an empty selection", () => {
    const result = reconcileDirectoryNames([], lib(["A/B"]));
    expect(result.changed).toBe(false);
    expect(result.names).toEqual([]);
  });
});
