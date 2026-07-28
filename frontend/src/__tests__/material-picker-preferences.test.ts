import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SavedMaterialLibraryItem } from "../api/types";
import {
  favoriteKeyForMaterial,
  loadMaterialProfileFavorites,
  saveMaterialProfileFavorites,
} from "../utils/materialPickerPreferences";

const FAVORITES_KEY = "lumina_material_profile_favorites_v1";

describe("material picker favorites", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("persists any number of independent profile favorites", () => {
    const favorites = new Set([
      "profile:profile-a",
      "profile:profile-b",
      "profile:profile-c",
    ]);

    saveMaterialProfileFavorites(favorites);

    expect(loadMaterialProfileFavorites()).toEqual(favorites);
    expect(JSON.parse(localStorage.getItem(FAVORITES_KEY) ?? "[]")).toEqual([
      "profile:profile-a",
      "profile:profile-b",
      "profile:profile-c",
    ]);
  });

  it("uses the stable profile id and falls back to the legacy directory", () => {
    const explicit = {
      material_profile_id: "profile-a",
      directory_name: "Brand/Profile A",
    } as SavedMaterialLibraryItem;
    const legacy = {
      material_profile_id: null,
      directory_name: "Brand/Legacy",
    } as SavedMaterialLibraryItem;

    expect(favoriteKeyForMaterial(explicit)).toBe("profile:profile-a");
    expect(favoriteKeyForMaterial(legacy)).toBe("dir:Brand/Legacy");
  });

  it("degrades malformed persisted data to an empty set", () => {
    localStorage.setItem(FAVORITES_KEY, "{not-json");
    expect(loadMaterialProfileFavorites()).toEqual(new Set());

    localStorage.setItem(FAVORITES_KEY, JSON.stringify(["ok", 42, null]));
    expect(loadMaterialProfileFavorites()).toEqual(new Set(["ok"]));
  });

  it("does not throw when browser storage rejects a write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });

    expect(() =>
      saveMaterialProfileFavorites(new Set(["profile:profile-a"])),
    ).not.toThrow();
  });
});
