import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import KeychainLoopSettings from "../components/sections/KeychainLoopSettings";
import { useConverterStore } from "../stores/converter";

describe("KeychainLoopSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      add_loop: false,
      puzzleEnabled: false,
      enable_fridge_magnet: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      loop_angle: 0,
      loop_offset_x: 0,
      loop_offset_y: 0,
    } as never);
  });

  it("disables the loop toggle while fridge magnet mode is enabled", () => {
    useConverterStore.setState({
      enable_fridge_magnet: true,
    } as never);

    render(<KeychainLoopSettings />);

    expect(
      screen.getByRole("switch", { name: "添加挂件环" }),
    ).toBeDisabled();
  });
});
