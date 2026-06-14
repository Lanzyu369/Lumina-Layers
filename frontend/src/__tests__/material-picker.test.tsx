/**
 * Material picker dialog and selection persistence tests.
 * 耗材选择弹窗与选择持久化测试。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

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

const expandAllMaterialPickerGroups = () => {
  for (const toggle of screen.getAllByTestId("material-picker-brand-group-toggle")) {
    if (toggle.getAttribute("aria-expanded") === "false") {
      fireEvent.click(toggle);
    }
  }
};

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
    const groupToggle = screen.getByTestId("material-picker-brand-group-toggle");
    expect(groupToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Red PLA")).not.toBeInTheDocument();

    fireEvent.click(groupToggle);
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

    expandAllMaterialPickerGroups();

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
    expandAllMaterialPickerGroups();
    fireEvent.click(screen.getByText("Red PLA"));
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("groups materials by brand, prefixes names with brand tags, and toggles groups", () => {
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

    // Brand headers are visible, but material rows start collapsed.
    expect(groups[0].textContent).toContain("瑞贝思");
    expect(groups[0].textContent).not.toContain("Red PLA");
    expect(groups[0].textContent).not.toContain("White PLA");
    expect(groups[1].textContent).not.toContain("Legacy PLA");

    const firstGroupToggle = within(groups[0]).getByTestId("material-picker-brand-group-toggle");
    const unassignedGroupToggle = within(groups[1]).getByTestId("material-picker-brand-group-toggle");
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(unassignedGroupToggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(firstGroupToggle);
    fireEvent.click(unassignedGroupToggle);

    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "true");
    expect(within(groups[0]).getByText("Red PLA")).toBeInTheDocument();
    expect(within(groups[0]).getByText("White PLA")).toBeInTheDocument();
    expect(within(groups[1]).getByText("Legacy PLA")).toBeInTheDocument();

    const brandTags = screen.getAllByTestId("material-picker-brand-tag");
    expect(brandTags.map((tag) => tag.textContent)).toEqual([
      "瑞贝思",
      "瑞贝思",
      expect.stringMatching(/未分组|Unassigned/),
    ]);

    fireEvent.click(firstGroupToggle);
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(groups[0]).queryByText("Red PLA")).not.toBeInTheDocument();
    expect(within(groups[0]).queryByText("White PLA")).not.toBeInTheDocument();
    expect(within(groups[1]).getByText("Legacy PLA")).toBeInTheDocument();
  });

  it("force-expands matching groups while searching, then restores collapse state", () => {
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

    // Groups start collapsed; the matching row is hidden.
    const groupToggle = screen.getByTestId("material-picker-brand-group-toggle");
    expect(groupToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Red PLA")).not.toBeInTheDocument();

    // Searching reveals the matching row even though the group was collapsed.
    fireEvent.change(screen.getByTestId("material-picker-search-input"), {
      target: { value: "Red" },
    });
    expect(screen.getByText("Red PLA")).toBeInTheDocument();
    expect(screen.queryByText("White PLA")).not.toBeInTheDocument();

    // Clearing the search restores the user's collapsed state.
    fireEvent.change(screen.getByTestId("material-picker-search-input"), {
      target: { value: "" },
    });
    expect(screen.getByTestId("material-picker-brand-group-toggle")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Red PLA")).not.toBeInTheDocument();
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

  it("keeps the material list as the stable scroll area while toggling cross-brand selections", () => {
    const materials = [
      makeMaterial({
        material_name: "Brand A Red PLA",
        directory_name: "brand-a/red-pla",
        brand: "Brand A",
      }),
      makeMaterial({
        material_name: "Brand A Yellow PLA",
        directory_name: "brand-a/yellow-pla",
        brand: "Brand A",
      }),
      makeMaterial({
        material_name: "Brand B Blue PLA",
        directory_name: "brand-b/blue-pla",
        brand: "Brand B",
      }),
      makeMaterial({
        material_name: "Brand B White PLA",
        directory_name: "brand-b/white-pla",
        brand: "Brand B",
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

    const dialog = screen.getByTestId("material-picker-dialog");
    const scrollArea = screen.getByTestId("material-picker-scroll-area");

    expect(dialog).toHaveClass("grid");
    expect(dialog).toHaveStyle({
      height: "85vh",
      maxHeight: "42rem",
      gridTemplateRows: "auto auto minmax(0, 1fr) auto",
    });
    expect(scrollArea).toHaveClass("row-start-3");
    expect(scrollArea).toHaveClass("min-h-0");
    expect(scrollArea).toHaveClass("overflow-y-auto");
    expect(scrollArea).toHaveClass("overscroll-contain");
    expect(scrollArea).toHaveClass("[overflow-anchor:none]");

    expandAllMaterialPickerGroups();

    fireEvent.click(screen.getByText("Brand A Red PLA"));
    fireEvent.click(screen.getByText("Brand A Yellow PLA"));
    fireEvent.click(screen.getByText("Brand B Blue PLA"));

    expect(scrollArea).toHaveClass("min-h-0");
    expect(scrollArea).toHaveClass("overflow-y-auto");
    expect(screen.getByText("Brand A Red PLA")).toBeInTheDocument();
    expect(screen.getByText("Brand A Yellow PLA")).toBeInTheDocument();
    expect(screen.getByText("Brand B Blue PLA")).toBeInTheDocument();
    expect(screen.getByText("Brand B White PLA")).toBeInTheDocument();
    expect(screen.getAllByTestId("material-picker-brand-group")).toHaveLength(2);
  });
});

describe("converter store — selectedMaterialDirNames persistence", () => {
  const KEY = "lumina_selectedMaterialDirNames";
  const BACKING_KEY = "lumina_materialBackingMaterialDirName";

  beforeEach(() => {
    localStorage.clear();
    useConverterStore.setState({
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });
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

  it("keeps the base plate material inside the selected material list", () => {
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-a", "mat-b"]);
    useConverterStore.getState().setMaterialBackingMaterialDirName("mat-b");
    expect(localStorage.getItem(BACKING_KEY)).toBe("mat-b");

    useConverterStore.getState().setSelectedMaterialDirNames(["mat-c", "mat-d"]);

    expect(useConverterStore.getState().materialBackingMaterialDirName).toBe("mat-c");
    expect(localStorage.getItem(BACKING_KEY)).toBe("mat-c");
  });

  it("defaults the base plate material to a selected white material", () => {
    useConverterStore.getState().setSelectedMaterialDirNames([
      "brand/pla-green",
      "brand/pla-yellow",
      "brand/pla-white",
    ]);

    expect(useConverterStore.getState().materialBackingMaterialDirName).toBe("brand/pla-white");
    expect(localStorage.getItem(BACKING_KEY)).toBe("brand/pla-white");
  });

  it("detects Chinese white material names for the base plate default", () => {
    useConverterStore.getState().setSelectedMaterialDirNames([
      "瑞贝思/瑞贝思 PLA 绿",
      "瑞贝思/瑞贝思 PLA 白",
    ]);

    expect(useConverterStore.getState().materialBackingMaterialDirName).toBe("瑞贝思/瑞贝思 PLA 白");
  });

  it("changing only the base plate material preserves preview state", () => {
    useConverterStore.setState({
      sessionId: "session-1",
      previewImageUrl: "/preview.png",
      previewGlbUrl: "/preview.glb",
      downloadUrl: "/old.3mf",
      threemfDiskPath: "/tmp/old.3mf",
      selectedMaterialDirNames: ["mat-a", "mat-b"],
      materialBackingMaterialDirName: "mat-a",
    });

    useConverterStore.getState().setMaterialBackingMaterialDirName("mat-b");

    expect(useConverterStore.getState().sessionId).toBe("session-1");
    expect(useConverterStore.getState().previewImageUrl).toBe("/preview.png");
    expect(useConverterStore.getState().previewGlbUrl).toBe("/preview.glb");
    expect(useConverterStore.getState().downloadUrl).toBeNull();
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
  });
});
