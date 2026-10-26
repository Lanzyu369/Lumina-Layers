import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { translations } from "../i18n/translations";
import type { BatchResponse } from "../api/types";

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

});
