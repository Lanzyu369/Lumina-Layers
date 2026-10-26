import { afterEach, describe, expect, it } from "vitest";
import apiClient from "../api/client";
import { getMachineRegistryAssetUrl } from "../api/system";
import * as systemApiModule from "../api/system";

const originalBaseUrl = apiClient.defaults.baseURL;

describe("machine registry asset URL", () => {
  afterEach(() => {
    apiClient.defaults.baseURL = originalBaseUrl;
  });

  it("uses a relative API asset path with the default API base", () => {
    apiClient.defaults.baseURL = "/api";

    expect(
      getMachineRegistryAssetUrl(
        "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
      ),
    ).toBe(
      "/api/system/machine-registry/assets/slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
    );
  });

  it("uses the configured absolute API base for image assets", () => {
    apiClient.defaults.baseURL = "http://127.0.0.1:8001/api";

    expect(
      getMachineRegistryAssetUrl(
        "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
      ),
    ).toBe(
      "http://127.0.0.1:8001/api/system/machine-registry/assets/slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
    );
  });

  it("builds a safe URL for the selected device's native slicer bed model", () => {
    apiClient.defaults.baseURL = "/api";
    const getMachineBedModelUrl = (
      systemApiModule as unknown as {
        getMachineBedModelUrl?: (deviceProfileId: string) => string;
      }
    ).getMachineBedModelUrl;

    expect(getMachineBedModelUrl).toBeTypeOf("function");
    if (!getMachineBedModelUrl) return;

    expect(
      getMachineBedModelUrl("OrcaSlicer:bbl:bambu-lab-a1-mini:0.4"),
    ).toBe(
      "/api/system/machine-registry/bed-model?device_profile_id=" +
        "OrcaSlicer%3Abbl%3Abambu-lab-a1-mini%3A0.4",
    );
  });
});
