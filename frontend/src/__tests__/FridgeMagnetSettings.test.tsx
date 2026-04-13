import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import type { FridgeMagnetItem } from "../api/types";
import { StructureMode } from "../api/types";
import FridgeMagnetSettings from "../components/sections/FridgeMagnetSettings";
import { useConverterStore } from "../stores/converter";

const selectedMagnet: FridgeMagnetItem = {
  id: "magnet-1",
  shape: "round",
  preset_key: "round-d12x3",
  diameter_mm: 12,
  width_mm: null,
  height_mm: null,
  thickness_mm: 3,
  center_x_mm: 0,
  center_y_mm: 0,
};

describe("FridgeMagnetSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      enable_fridge_magnet: true,
      fridge_magnets: [selectedMagnet],
      selectedFridgeMagnetId: selectedMagnet.id,
      structure_mode: StructureMode.SINGLE_SIDED,
      spacer_thick: 1.2,
    });
  });

  it("renders translated labels and does not leak raw fridge magnet keys", () => {
    render(<FridgeMagnetSettings />);

    expect(
      screen.getByRole("checkbox", { name: "启用冰箱贴磁铁槽" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加磁铁" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "自动布局" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除当前磁铁" })).toBeInTheDocument();
    expect(screen.getByText("磁铁 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除选中" })).toBeInTheDocument();
    const magnetRow = screen.getByRole("button", { name: /磁铁 1/ });
    expect(within(magnetRow).getByText("圆形")).toBeInTheDocument();
    expect(within(magnetRow).getByText("圆形 D12×3 mm")).toBeInTheDocument();
    expect(screen.queryByText("fridge_magnet_enable")).not.toBeInTheDocument();
    expect(screen.queryByText("fridge_magnet_add")).not.toBeInTheDocument();
    expect(screen.queryByText("fridge_magnet_item_label")).not.toBeInTheDocument();
  });
});
