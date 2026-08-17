import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { translations } from "../i18n/translations";
import type { BatchResponse } from "../api/types";
import fs from "node:fs";
import path from "node:path";

// --- Mutable locale for i18n mock ---
let currentLang: "zh" | "en" = "zh";

vi.mock("../i18n/context", () => ({
  useI18n: () => ({
    t: (key: string): string => {
      const entry = translations[key];
      if (!entry) return key;
      return entry[currentLang] ?? entry["zh"] ?? key;
    },
    lang: currentLang,
  }),
  I18nProvider: ({ children }: { children?: React.ReactNode }) => children,
}));

// --- Test fixtures ---
const propsA: BatchResponse = {
  status: "ok",
  message: "batch done",
  download_url: "/api/files/merged-abc123.3mf",
  preview_3d_url: "/api/files/merged-abc123.glb",
  results: [
    { filename: "photo1.png", status: "success" },
    { filename: "photo2.jpg", status: "success" },
  ],
  warnings: [],
};

const propsB: BatchResponse = {
  status: "ok",
  message: "batch done with overflow",
  download_url: "/api/files/merged-def456.3mf",
  preview_3d_url: "/api/files/merged-def456.glb",
  results: [
    { filename: "photo1.png", status: "success" },
    { filename: "photo2.jpg", status: "success" },
    { filename: "photo3.png", status: "success" },
  ],
  warnings: [{ code: "plate-overflow", message: "irrelevant" }],
};

const propsC: BatchResponse = {
  status: "ok",
  message: "batch done",
  download_url: "/api/files/merged-ghi789.3mf",
  preview_3d_url: null,
  results: [{ filename: "photo1.png", status: "success" }],
  warnings: [{ code: "unknown-future-code", message: "x" }],
};

const propsD: BatchResponse = {
  status: "ok",
  message: "batch done with per-file timeout",
  download_url: "/api/files/merged-timeout.3mf",
  preview_3d_url: null,
  results: [
    {
      filename: "photo-timeout.png",
      status: "failed",
      error: "Batch item conversion timed out",
    },
  ],
  warnings: [],
};

const propsE: BatchResponse = {
  ...propsA,
  warnings: [
    {
      code: "wipe_tower_manual_adjustment_required",
      message: "raw fallback should not be rendered",
    },
  ],
};

// Lazy import to allow vi.mock to take effect before module loads
async function importComponent() {
  const mod = await import("../components/ui/BatchResultSummary");
  return mod.default;
}

describe("BatchResultSummary", () => {
  beforeEach(() => {
    currentLang = "zh";
    cleanup();
  });

  describe("Props A: download_url non-empty + warnings empty", () => {
    it("renders download button with correct text and href", async () => {
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsA} />);

      const link = screen.getByRole("link", {
        name: translations["batch.download.mergedThreemf"].zh,
      });
      expect(link).toBeInTheDocument();
      // href should point to the normalized download_url (already relative)
      expect(link).toHaveAttribute("href", "/api/files/merged-abc123.3mf");
    });

    it("does not render any warning text", async () => {
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsA} />);

      expect(
        screen.queryByText(translations["batch.warnings.plateOverflow.body"].zh),
      ).not.toBeInTheDocument();
    });
  });

  describe("Props B: download_url non-empty + plate-overflow warning", () => {
    it("renders download button (not hidden by warnings)", async () => {
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsB} />);

      const link = screen.getByRole("link", {
        name: translations["batch.download.mergedThreemf"].zh,
      });
      expect(link).toBeInTheDocument();
      expect(link).toHaveAttribute("href", "/api/files/merged-def456.3mf");
    });

    it("renders plate-overflow warning from i18n key, not from message text", async () => {
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsB} />);

      // Should show the i18n-translated warning body
      expect(
        screen.getByText(translations["batch.warnings.plateOverflow.body"].zh),
      ).toBeInTheDocument();

      // Should NOT display the raw message text from the WarningEntry
      expect(screen.queryByText("irrelevant")).not.toBeInTheDocument();
    });
  });

  describe("Props C: unknown warning code", () => {
    it("does not render any warning row for unknown codes", async () => {
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsC} />);

      // No plate-overflow warning text
      expect(
        screen.queryByText(translations["batch.warnings.plateOverflow.body"].zh),
      ).not.toBeInTheDocument();
      // No raw message text
      expect(screen.queryByText("x")).not.toBeInTheDocument();
    });

    it("does not throw a UI error", async () => {
      const BatchResultSummary = await importComponent();
      // Should render without throwing
      expect(() => render(<BatchResultSummary result={propsC} />)).not.toThrow();
    });
  });

  describe("wipe-tower manual warning", () => {
    it("renders the localized manual-adjustment warning and keeps the download", async () => {
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsE} />);

      expect(
        screen.getByText(
          translations["batch.warnings.wipeTowerManual.body"].zh,
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText("raw fallback should not be rendered")).not.toBeInTheDocument();
      expect(
        screen.getByRole("link", {
          name: translations["batch.download.mergedThreemf"].zh,
        }),
      ).toBeInTheDocument();
    });
  });

  describe("failed item messages", () => {
    it("localizes backend batch item timeout details instead of rendering raw English", async () => {
      currentLang = "zh";
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsD} />);

      const timeoutMessage = translations["batch.itemError.timeout"];
      expect(timeoutMessage).toBeDefined();
      expect(screen.getByRole("listitem")).toHaveTextContent(timeoutMessage.zh);
      expect(
        screen.queryByText("Batch item conversion timed out"),
      ).not.toBeInTheDocument();
    });
  });

  describe("i18n locale switching (zh ↔ en)", () => {
    it("renders Chinese text in zh locale", async () => {
      currentLang = "zh";
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsB} />);

      expect(
        screen.getByText(translations["batch.download.mergedThreemf"].zh),
      ).toBeInTheDocument();
      expect(
        screen.getByText(translations["batch.warnings.plateOverflow.body"].zh),
      ).toBeInTheDocument();
    });

    it("renders English text in en locale", async () => {
      currentLang = "en";
      const BatchResultSummary = await importComponent();
      render(<BatchResultSummary result={propsB} />);

      expect(
        screen.getByText(translations["batch.download.mergedThreemf"].en),
      ).toBeInTheDocument();
      expect(
        screen.getByText(translations["batch.warnings.plateOverflow.body"].en),
      ).toBeInTheDocument();
    });
  });

  describe("source code compliance scan", () => {
    it("has no raw color literals (#, bg-white, text-black) or hardcoded zh/en strings", () => {
      const componentPath = path.resolve(
        __dirname,
        "../components/ui/BatchResultSummary.tsx",
      );
      const source = fs.readFileSync(componentPath, "utf-8");

      // No bare hex color values like #fff, #000, #ffffff (allow svg stroke/fill refs)
      // Filter out lines that are clearly SVG path data or comments
      const codeLines = source
        .split("\n")
        .filter((line) => {
          const trimmed = line.trim();
          // Skip comments
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return false;
          // Skip SVG path/polyline/line elements
          if (/<path|<polyline|<line/.test(trimmed)) return false;
          return true;
        });

      const codeContent = codeLines.join("\n");

      // No bg-white or text-black Tailwind classes
      expect(codeContent).not.toMatch(/\bbg-white\b/);
      expect(codeContent).not.toMatch(/\btext-black\b/);

      // No bare # color literals in className strings (e.g. style={{ color: "#fff" }})
      // Match patterns like: "#fff", "#000", "#ffffff" in non-SVG context
      const hexInStyles = codeContent.match(/["'`]#[0-9a-fA-F]{3,8}["'`]/g);
      expect(hexInStyles).toBeNull();

      // No hardcoded Chinese user-facing strings (should use t() instead)
      // Check for common Chinese characters that would indicate hardcoded text
      // Exclude import statements and type annotations
      const nonImportLines = codeLines.filter(
        (line) => !line.trim().startsWith("import") && !line.trim().startsWith("export type"),
      );
      const nonImportContent = nonImportLines.join("\n");

      // Should not contain hardcoded Chinese like "下载" or "模型" outside of comments
      expect(nonImportContent).not.toMatch(/["'`][^"'`]*[\u4e00-\u9fff]+[^"'`]*["'`]/);
    });
  });
});
