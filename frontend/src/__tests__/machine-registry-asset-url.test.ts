import { afterEach, describe, expect, it } from "vitest";
import apiClient from "../api/client";
import { getMachineRegistryAssetUrl } from "../api/system";

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
});
