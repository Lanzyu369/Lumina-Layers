/**
 * Material picker dialog and selection persistence tests.
 * 耗材选择弹窗与选择持久化测试。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import MaterialPickerDialog from "../components/ui/MaterialPickerDialog";
import { useConverterStore } from "../stores/converter";
import type { SavedMaterialLibraryItem } from "../api/types";

function makeMaterial(
  overrides: Partial<SavedMaterialLibraryItem> & {
    material_name: string;
    directory_name: string;
  },
): SavedMaterialLibraryItem {
  return {
    archive_path: `materials/${overrides.directory_name}/material.json`,
    stage_a_params_path: `materials/${overrides.directory_name}/stage_A_parameters.json`,
    material_file_url: `/api/files/${overrides.directory_name}-material`,
    stage_a_params_url: `/api/files/${overrides.directory_name}-stage-a`,
    created_at: "2026-04-17T00:00:00Z",
    updated_at: "2026-04-17T00:00:00Z",
    estimated_rgb: [200, 50, 50],
    layer_height_mm: 0.08,
    mean_delta_e: 1.4,
    verification_count: 1,
    verification_history: [],
    ...overrides,
  };
}

const SAMPLE_MATERIALS: SavedMaterialLibraryItem[] = [
  makeMaterial({ material_name: "Red PLA", directory_name: "red-pla" }),
  makeMaterial({ material_name: "Yellow PLA", directory_name: "yellow-pla", estimated_rgb: [240, 220, 60] }),
  makeMaterial({ material_name: "Blue PLA", directory_name: "blue-pla", estimated_rgb: [40, 80, 200] }),
];

describe("MaterialPickerDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <MaterialPickerDialog
        open={false}
        materials={SAMPLE_MATERIALS}
        loading={false}
        initialSelected={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("lists every available material when open", () => {
    render(
      <MaterialPickerDialog
        open={true}
        materials={SAMPLE_MATERIALS}
        loading={false}
        initialSelected={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("Red PLA")).toBeInTheDocument();
    expect(screen.getByText("Yellow PLA")).toBeInTheDocument();
    expect(screen.getByText("Blue PLA")).toBeInTheDocument();
  });

  it("confirms the staged selection without committing intermediate toggles", () => {
    const onConfirm = vi.fn();
    render(
      <MaterialPickerDialog
        open={true}
        materials={SAMPLE_MATERIALS}
        loading={false}
        initialSelected={["red-pla"]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    // Toggle Yellow (add) and Red (remove)
    fireEvent.click(screen.getByText("Yellow PLA"));
    fireEvent.click(screen.getByText("Red PLA"));

    fireEvent.click(screen.getByText("完成"));
    expect(onConfirm).toHaveBeenCalledWith(["yellow-pla"]);
  });

  it("cancel does not commit pending changes", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <MaterialPickerDialog
        open={true}
        materials={SAMPLE_MATERIALS}
        loading={false}
        initialSelected={[]}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByText("Red PLA"));
    fireEvent.click(screen.getByText("关闭"));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("groups materials by brand and puts unassigned entries in a trailing group", () => {
    const materials = [
      makeMaterial({
        material_name: "Red PLA",
        directory_name: "瑞贝思/red-pla",
        brand: "瑞贝思",
      }),
      makeMaterial({
        material_name: "White PLA",
        directory_name: "瑞贝思/white-pla",
        brand: "瑞贝思",
      }),
      makeMaterial({
        material_name: "Legacy PLA",
        directory_name: "legacy-pla",
        brand: null,
      }),
    ];
    render(
      <MaterialPickerDialog
        open={true}
        materials={materials}
        loading={false}
        initialSelected={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const groups = screen.getAllByTestId("material-picker-brand-group");
    expect(groups).toHaveLength(2);
    expect(groups[0].getAttribute("data-brand")).toBe("瑞贝思");
    expect(groups[1].getAttribute("data-brand")).toBe("");

    // Brand header + 2 branded materials under that group
    expect(groups[0].textContent).toContain("瑞贝思");
    expect(groups[0].textContent).toContain("Red PLA");
    expect(groups[0].textContent).toContain("White PLA");

    // Unassigned header + legacy entry at the end
    expect(groups[1].textContent).toContain("Legacy PLA");
  });

  it("select-all toggles to clear-all once everything is selected", () => {
    const onConfirm = vi.fn();
    render(
      <MaterialPickerDialog
        open={true}
        materials={SAMPLE_MATERIALS}
        loading={false}
        initialSelected={[]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("全选"));
    fireEvent.click(screen.getByText("完成"));
    expect(onConfirm).toHaveBeenLastCalledWith(["red-pla", "yellow-pla", "blue-pla"]);
  });
});

describe("converter store — selectedMaterialDirNames persistence", () => {
  const KEY = "lumina_selectedMaterialDirNames";

  beforeEach(() => {
    localStorage.clear();
    useConverterStore.setState({ selectedMaterialDirNames: [] });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("writes the latest selection to localStorage when set", () => {
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-a", "mat-b"]);
    expect(JSON.parse(localStorage.getItem(KEY) ?? "[]")).toEqual(["mat-a", "mat-b"]);
  });

  it("overwrites previous persisted value on subsequent updates", () => {
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-a"]);
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-c", "mat-d"]);
    expect(JSON.parse(localStorage.getItem(KEY) ?? "[]")).toEqual(["mat-c", "mat-d"]);
  });

  it("clearing the selection persists an empty array (not removed)", () => {
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-a"]);
    useConverterStore.getState().setSelectedMaterialDirNames([]);
    expect(localStorage.getItem(KEY)).toBe("[]");
  });
});
