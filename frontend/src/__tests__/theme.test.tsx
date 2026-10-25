import { describe, it, expect, beforeEach } from "vitest";
import { useEffect } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { renderHook, act } from "@testing-library/react";
import { ThemeToggle } from "../components/ThemeToggle";
import { useDocumentThemeClass } from "../hooks/useDocumentThemeClass";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { THEME_CONFIG } from "../components/themeConfig";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";

// ========== Setup ==========

beforeEach(() => {
  // Reset store to defaults before each test
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  // Clean up dark class from documentElement
  document.documentElement.classList.remove("dark");
});

// ========== ThemeToggle Component Tests ==========

describe("ThemeToggle", () => {
  it("shows dark mode as an unpressed menu item in light mode", () => {
    useSettingsStore.setState({ theme: "light" });
    render(<ThemeToggle />);

    const item = screen.getByRole("button", { name: "深色模式" });
    expect(item).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("theme-icon-moon")).toBeInTheDocument();
    // DESIGN.md forbids native ``title`` tooltips on header controls.
    // DESIGN.md 禁止顶栏控件使用原生 ``title`` 提示。
    expect(item).not.toHaveAttribute("title");
  });

  it("shows dark mode as pressed in dark mode", () => {
    useSettingsStore.setState({ theme: "dark" });
    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: "深色模式" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("toggles theme from light to dark on click", () => {
    useSettingsStore.setState({ theme: "light" });
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("button", { name: "深色模式" }));

    expect(useSettingsStore.getState().theme).toBe("dark");
  });
});

// ========== useDocumentThemeClass Hook Tests ==========

describe("useDocumentThemeClass", () => {
  it("mirrors the stored theme onto the root element", () => {
    useSettingsStore.setState({ theme: "dark" });
    renderHook(() => useDocumentThemeClass());
    expect(document.documentElement).toHaveClass("dark");

    act(() => {
      useSettingsStore.getState().setTheme("light");
    });

    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("sets the class before children's effects read it on mount", () => {
    useSettingsStore.setState({ theme: "dark" });
    const seenByChild: boolean[] = [];
    function ReadsThemeOnMount() {
      useEffect(() => {
        seenByChild.push(document.documentElement.classList.contains("dark"));
      }, []);
      return null;
    }
    function Root() {
      useDocumentThemeClass();
      return <ReadsThemeOnMount />;
    }

    render(<Root />);

    expect(seenByChild).toEqual([true]);
  });
});

// ========== useThemeConfig Hook Tests ==========

describe("useThemeConfig", () => {
  it("returns THEME_CONFIG.light when theme is 'light'", () => {
    useSettingsStore.setState({ theme: "light" });
    const { result } = renderHook(() => useThemeConfig());
    expect(result.current).toEqual(THEME_CONFIG.light);
  });

  it("returns THEME_CONFIG.dark when theme is 'dark'", () => {
    useSettingsStore.setState({ theme: "dark" });
    const { result } = renderHook(() => useThemeConfig());
    expect(result.current).toEqual(THEME_CONFIG.dark);
  });

  it("updates when store theme changes", () => {
    useSettingsStore.setState({ theme: "light" });
    const { result } = renderHook(() => useThemeConfig());

    expect(result.current).toEqual(THEME_CONFIG.light);

    act(() => {
      useSettingsStore.getState().setTheme("dark");
    });

    expect(result.current).toEqual(THEME_CONFIG.dark);
  });
});

// ========== Default Theme Tests ==========

describe("Default theme", () => {
  it("DEFAULT_SETTINGS.theme is 'light'", () => {
    expect(DEFAULT_SETTINGS.theme).toBe("light");
  });
});
