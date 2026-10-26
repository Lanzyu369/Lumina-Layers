import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Button from "../Button";
import TransientBanner from "../TransientBanner";

afterEach(() => vi.useRealTimers());
describe("button loading and transient feedback", () => {
  it.each([false, true])("replaces button content with one centered spinner (icon=%s)", iconOnly => {
    const click = vi.fn();
    const { rerender } = render(<Button label="Refresh" onClick={click} loading icon={iconOnly ? <svg data-testid="icon" /> : undefined} />);
    const button = screen.getByRole("button", { name: "Refresh" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector(".invisible")).toHaveAttribute("aria-hidden", "true");
    const spinner = button.querySelector(".animate-spin")!;
    expect(spinner.parentElement).toHaveClass("absolute", "inset-0", "items-center", "justify-center");
    fireEvent.click(button); expect(click).not.toHaveBeenCalled();
    rerender(<Button label="Refresh" onClick={click} />);
    expect(button.querySelector(".invisible")).toBeNull();
    expect(button.querySelector(".animate-spin")).toBeNull();
    fireEvent.click(button); expect(click).toHaveBeenCalledOnce();
  });
  it("keeps success for five seconds, fades, then collapses before dismissal", () => {
    vi.useFakeTimers();
    const dismiss = vi.fn();
    render(<TransientBanner message="Saved" onDismiss={dismiss} />);
    const wrapper = screen.getByRole("status").parentElement!;
    act(() => vi.advanceTimersByTime(4999));
    expect(wrapper).toHaveAttribute("data-phase", "visible");
    act(() => vi.advanceTimersByTime(1));
    expect(wrapper).toHaveAttribute("data-phase", "fade");
    expect(dismiss).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(200));
    expect(wrapper).toHaveAttribute("data-phase", "collapse");
    act(() => vi.advanceTimersByTime(250));
    expect(dismiss).toHaveBeenCalledOnce();
  });
  it("restarts the lifetime for a new message and clears old timers", () => {
    vi.useFakeTimers(); const dismiss = vi.fn();
    const view = render(<TransientBanner message="First" onDismiss={dismiss} />);
    act(() => vi.advanceTimersByTime(4000));
    view.rerender(<TransientBanner message="Second" onDismiss={dismiss} />);
    act(() => vi.advanceTimersByTime(2000));
    expect(dismiss).not.toHaveBeenCalled();
    expect(screen.getByRole("status").parentElement).toHaveAttribute("data-phase", "visible");
    view.unmount(); act(() => vi.advanceTimersByTime(6000));
    expect(dismiss).not.toHaveBeenCalled();
  });
  it("fades and collapses an info banner the caller clears early", () => {
    vi.useFakeTimers();
    const view = render(<TransientBanner tone="info" message="Registry offline" onDismiss={() => {}} />);
    act(() => vi.advanceTimersByTime(1000));
    const wrapper = screen.getByRole("status").parentElement!;
    expect(wrapper).toHaveAttribute("data-phase", "visible");

    view.rerender(<TransientBanner tone="info" message={null} onDismiss={() => {}} />);
    expect(wrapper).toHaveAttribute("data-phase", "fade");
    expect(screen.getByRole("status")).toHaveTextContent("Registry offline");
    act(() => vi.advanceTimersByTime(200));
    expect(wrapper).toHaveAttribute("data-phase", "collapse");
    act(() => vi.advanceTimersByTime(250));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
  it("keeps a persistent banner until the caller clears it", () => {
    vi.useFakeTimers();
    const view = render(<TransientBanner tone="info" autoDismiss={false} message="Loading index" />);
    act(() => vi.advanceTimersByTime(10000));
    expect(screen.getByRole("status").parentElement).toHaveAttribute("data-phase", "visible");

    view.rerender(<TransientBanner tone="info" autoDismiss={false} message={null} />);
    act(() => vi.advanceTimersByTime(200));
    expect(screen.getByRole("status").parentElement).toHaveAttribute("data-phase", "collapse");
    act(() => vi.advanceTimersByTime(250));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
