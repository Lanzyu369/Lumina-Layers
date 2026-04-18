import { beforeEach, describe, expect, it } from "vitest";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import { useConverterStore } from "../stores/converter";

async function flushAsyncImports(): Promise<void> {
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("device setting changes invalidate generated 3MF artifacts", () => {
  beforeEach(() => {
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useConverterStore.setState({
      threemfDiskPath: "E:/fake/model.3mf",
      downloadUrl: "/api/files/fake-3mf",
    });
  });

  it("clears generated artifacts when printer changes", async () => {
    useSettingsStore.getState().setPrinterModel("bambu-p1s");
    await flushAsyncImports();

    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("clears generated artifacts when slicer changes", async () => {
    useSettingsStore.getState().setSlicerSoftware("OrcaSlicer");
    await flushAsyncImports();

    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("clears generated artifacts when nozzle size changes", async () => {
    useSettingsStore.getState().setNozzleSize("0.2");
    await flushAsyncImports();

    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });
});
