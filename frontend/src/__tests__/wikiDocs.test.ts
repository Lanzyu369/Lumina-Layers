import { describe, expect, it } from "vitest";
import { buildWikiDocUrl } from "../utils/wikiDocs";

describe("buildWikiDocUrl", () => {
  const path = "/docs/reference/converter-basic/actions/" as const;

  it("uses the Chinese Wiki route for Chinese UI", () => {
    expect(buildWikiDocUrl(path, "zh")).toBe(
      "https://wiki.luminastudio.com.cn/zh/docs/reference/converter-basic/actions/",
    );
  });

  it("uses the English Wiki route for English UI", () => {
    expect(buildWikiDocUrl(path, "en")).toBe(
      "https://wiki.luminastudio.com.cn/en/docs/reference/converter-basic/actions/",
    );
  });
});
