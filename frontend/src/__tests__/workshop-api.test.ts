import { beforeEach, describe, expect, it, vi } from "vitest";

const getMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  default: {
    get: getMock,
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { workshopApi } from "../api/workshop";

describe("Workshop API resource paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not duplicate the shared /api prefix for module details", async () => {
    getMock.mockResolvedValue({
      data: {
        module_id: "fixture.hello",
        version: "1.0.0",
        readme_markdown: "# Fixture",
        license_text: "MIT",
        gallery_urls: [],
      },
    });

    await workshopApi.fetchDetails(
      "/api/workshop/v1/modules/fixture.hello/1.0.0/details",
    );

    expect(getMock).toHaveBeenCalledWith(
      "/workshop/v1/modules/fixture.hello/1.0.0/details",
    );
  });
});
