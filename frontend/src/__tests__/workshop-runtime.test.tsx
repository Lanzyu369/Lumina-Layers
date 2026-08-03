import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  WorkshopFrame,
  type WorkshopFrameModule,
} from "../workshop/runtime/WorkshopFrame";
import {
  WORKSHOP_RUNTIME_CSP,
  desktopModuleUrl,
  isWorkshopApiCompatible,
} from "../workshop/runtime/health";
import type { WorkshopMessagePort } from "../workshop/runtime/rpcHost";

class FakeHostPort implements WorkshopMessagePort {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onmessageerror: ((event: MessageEvent) => void) | null = null;
  readonly postMessage = vi.fn();
  readonly start = vi.fn();
  readonly close = vi.fn();
}

function installedFixture(
  overrides: Partial<WorkshopFrameModule> = {},
): WorkshopFrameModule {
  return {
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    displayName: "Fixture Hello",
    source: "fixture",
    official: false,
    enabled: true,
    runtimeUrl:
      "/api/workshop/v1/modules/fixture.hello/1.0.0/runtime",
    browserRuntimeHtml:
      "<html><head></head><body><script>globalThis.fixture=true</script></body></html>",
    workshopApi: {
      min: "1.0.0",
      maxExclusive: "2.0.0",
    },
    permissions: [],
    candidate: false,
    previousVersion: null,
    consecutiveStartFailures: 0,
    ...overrides,
  };
}

function postReady(
  source: MessageEventSource | null,
  overrides: Partial<{
    moduleId: string;
    moduleVersion: string;
    apiVersion: string;
  }> = {},
): void {
  const event = new MessageEvent("message", {
    data: {
      type: "lumina.workshop.ready",
      moduleId: "fixture.hello",
      moduleVersion: "1.0.0",
      apiVersion: "1.0.0",
      ...overrides,
    },
  });
  Object.defineProperty(event, "source", { value: source });
  window.dispatchEvent(event);
}

function rpcRequest(
  method:
    | "image.pick"
    | "status.progress"
    | "lifecycle.ready"
    | "colorLibrary.read",
  payload: unknown,
  requestId: string,
) {
  return {
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "request",
    requestId,
    method,
    payload,
  };
}

function channelFixture() {
  const port1 = new FakeHostPort();
  const port2 = {
    close: vi.fn(),
  } as unknown as MessagePort;
  return {
    port1,
    port2,
    createChannel: vi.fn(() => ({ port1, port2 })),
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("WorkshopFrame", () => {
  it("accepts ready only from the current iframe window and matching identity", async () => {
    const channel = channelFixture();
    window.localStorage.setItem("outside-frame", "kept");
    const setItem = vi.spyOn(
      Storage.prototype,
      "setItem",
    );

    render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    expect(iframe.getAttribute("sandbox")).not.toContain(
      "allow-same-origin",
    );
    expect(iframe).toHaveAttribute("referrerpolicy", "no-referrer");
    const srcDoc = iframe.getAttribute("srcdoc") ?? "";
    expect(srcDoc.indexOf(WORKSHOP_RUNTIME_CSP)).toBeGreaterThanOrEqual(
      0,
    );
    expect(srcDoc.indexOf(WORKSHOP_RUNTIME_CSP)).toBeLessThan(
      srcDoc.indexOf("<script>"),
    );

    fireEvent.load(iframe);
    const childWindow = (
      iframe as HTMLIFrameElement
    ).contentWindow;
    expect(childWindow).not.toBeNull();
    const connectPort = vi.spyOn(childWindow!, "postMessage");

    act(() => {
      postReady(window, {
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
      });
      postReady(childWindow, {
        moduleId: "other.module",
        moduleVersion: "1.0.0",
      });
      postReady(childWindow, {
        moduleId: "fixture.hello",
        moduleVersion: "9.0.0",
      });
      postReady(childWindow, {
        apiVersion: "2.0.0",
      });
    });
    expect(connectPort).not.toHaveBeenCalled();

    act(() => {
      postReady(childWindow);
    });
    await waitFor(() =>
      expect(connectPort).toHaveBeenCalledTimes(1),
    );
    act(() => {
      postReady(childWindow);
    });
    expect(channel.createChannel).toHaveBeenCalledTimes(1);
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("outside-frame")).toBe("kept");
  });

  it("terminates a frame that misses the ten second handshake", async () => {
    vi.useFakeTimers();
    const onStartFailure = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture()}
        onStartFailure={onStartFailure}
      />,
    );
    fireEvent.load(screen.getByTitle("Fixture Hello"));

    await act(async () => {
      vi.advanceTimersByTime(10_001);
    });

    expect(screen.getByText("模块启动超时")).toBeInTheDocument();
    expect(screen.queryByTitle("Fixture Hello")).not.toBeInTheDocument();
    expect(onStartFailure).toHaveBeenCalledWith(
      expect.objectContaining({
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        reason: "handshake-timeout",
      }),
    );
  });

  it("keeps one active port and closes it on unmount", async () => {
    const channel = channelFixture();
    const view = render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    expect(channel.createChannel).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(channel.port1.close).toHaveBeenCalledTimes(1);
    expect(channel.port1.onmessage).toBeNull();
  });

  it("keeps the active port across semantically identical module props", async () => {
    const channel = channelFixture();
    const imagePick = vi.fn().mockResolvedValue(null);
    const handlers = {
      "image.pick": imagePick,
    };
    const initialPrepareCandidate = vi.fn();
    const moduleOverrides: Partial<WorkshopFrameModule> = {
      permissions: ["image.pick"],
    };
    const view = render(
      <WorkshopFrame
        module={installedFixture(moduleOverrides)}
        handlers={handlers}
        createChannel={channel.createChannel}
        prepareCandidate={initialPrepareCandidate}
        disableVersion={vi.fn()}
        onStartFailure={vi.fn()}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    view.rerender(
      <WorkshopFrame
        module={installedFixture(moduleOverrides)}
        handlers={handlers}
        createChannel={channel.createChannel}
        prepareCandidate={vi.fn()}
        disableVersion={vi.fn()}
        onStartFailure={vi.fn()}
      />,
    );

    expect(channel.port1.close).not.toHaveBeenCalled();
    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("image.pick", {}, "pick-after-rerender"),
        }),
      );
    });
    await waitFor(() => expect(imagePick).toHaveBeenCalledTimes(1));
  });

  it("snapshots a candidate, renders progress, and activates only after lifecycle.ready", async () => {
    const channel = channelFixture();
    const order: string[] = [];
    const prepareCandidate = vi.fn(async () => {
      order.push("snapshot");
    });
    const activateCandidate = vi.fn(async () => {
      order.push("activate");
    });
    render(
      <WorkshopFrame
        module={installedFixture({
          moduleVersion: "1.1.0",
          candidate: true,
        })}
        createChannel={channel.createChannel}
        prepareCandidate={prepareCandidate}
        activateCandidate={activateCandidate}
      />,
    );

    expect(
      screen.queryByTitle("Fixture Hello"),
    ).not.toBeInTheDocument();
    const iframe = await screen.findByTitle("Fixture Hello");
    expect(prepareCandidate).toHaveBeenCalledTimes(1);
    expect(order).toEqual(["snapshot"]);
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );
    expect(activateCandidate).not.toHaveBeenCalled();

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest(
            "status.progress",
            {
              phase: "analyze",
              completed: 1,
              total: 4,
            },
            "progress-1",
          ),
        }),
      );
    });
    expect(await screen.findByText("1 / 4")).toBeInTheDocument();

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-1"),
        }),
      );
    });
    await waitFor(() =>
      expect(activateCandidate).toHaveBeenCalledWith(
        "fixture.hello",
        "1.1.0",
      ),
    );
    expect(order).toEqual(["snapshot", "activate"]);
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("keeps the active port when a candidate becomes the installed version", async () => {
    const channel = channelFixture();
    const activateCandidate = vi.fn().mockResolvedValue(undefined);
    const progress = vi.fn().mockResolvedValue(undefined);
    const candidateModule = installedFixture({
      moduleVersion: "1.1.0",
      candidate: true,
    });
    const view = render(
      <WorkshopFrame
        module={candidateModule}
        handlers={{ "status.progress": progress }}
        createChannel={channel.createChannel}
        prepareCandidate={vi.fn().mockResolvedValue(undefined)}
        activateCandidate={activateCandidate}
      />,
    );

    const iframe = await screen.findByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-1"),
        }),
      );
    });
    await waitFor(() =>
      expect(activateCandidate).toHaveBeenCalledWith(
        "fixture.hello",
        "1.1.0",
      ),
    );

    view.rerender(
      <WorkshopFrame
        module={{ ...candidateModule, candidate: false }}
        handlers={{ "status.progress": progress }}
        createChannel={channel.createChannel}
        prepareCandidate={vi.fn()}
        activateCandidate={activateCandidate}
      />,
    );

    expect(channel.port1.close).not.toHaveBeenCalled();
    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest(
            "status.progress",
            {
              phase: "autosave",
              completed: 1,
              total: 1,
            },
            "progress-after-activation",
          ),
        }),
      );
    });
    await waitFor(() => expect(progress).toHaveBeenCalledTimes(1));
  });

  it("does not repeat candidate activation when the installed runtime restarts", async () => {
    const firstChannel = channelFixture();
    const secondChannel = channelFixture();
    const createChannel = vi
      .fn()
      .mockReturnValueOnce({
        port1: firstChannel.port1,
        port2: firstChannel.port2,
      })
      .mockReturnValueOnce({
        port1: secondChannel.port1,
        port2: secondChannel.port2,
      });
    const prepareCandidate = vi.fn().mockResolvedValue(undefined);
    const activateCandidate = vi.fn().mockResolvedValue(undefined);
    const candidateModule = installedFixture({
      moduleVersion: "1.1.0",
      candidate: true,
    });
    const view = render(
      <WorkshopFrame
        module={candidateModule}
        createChannel={createChannel}
        prepareCandidate={prepareCandidate}
        activateCandidate={activateCandidate}
      />,
    );

    const candidateFrame = await screen.findByTitle("Fixture Hello");
    fireEvent.load(candidateFrame);
    act(() => {
      postReady((candidateFrame as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(firstChannel.port1.start).toHaveBeenCalledTimes(1),
    );
    act(() => {
      firstChannel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-candidate"),
        }),
      );
    });
    await waitFor(() =>
      expect(activateCandidate).toHaveBeenCalledTimes(1),
    );

    view.rerender(
      <WorkshopFrame
        module={{
          ...candidateModule,
          candidate: false,
          browserRuntimeHtml:
            "<html><head></head><body>installed restart</body></html>",
        }}
        createChannel={createChannel}
        prepareCandidate={prepareCandidate}
        activateCandidate={activateCandidate}
      />,
    );

    const installedFrame = await screen.findByTitle("Fixture Hello");
    await waitFor(() =>
      expect(installedFrame.getAttribute("srcdoc")).toContain(
        "installed restart",
      ),
    );
    expect(prepareCandidate).toHaveBeenCalledTimes(1);
    fireEvent.load(installedFrame);
    act(() => {
      postReady((installedFrame as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(secondChannel.port1.start).toHaveBeenCalledTimes(1),
    );
    act(() => {
      secondChannel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-installed"),
        }),
      );
    });
    await waitFor(() =>
      expect(screen.getByText("运行中")).toBeInTheDocument(),
    );
    expect(activateCandidate).toHaveBeenCalledTimes(1);
  });

  it("disables a version after its third consecutive startup failure", async () => {
    vi.useFakeTimers();
    const disableVersion = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture({
          consecutiveStartFailures: 2,
        })}
        disableVersion={disableVersion}
      />,
    );
    fireEvent.load(screen.getByTitle("Fixture Hello"));

    await act(async () => {
      vi.advanceTimersByTime(10_001);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(disableVersion).toHaveBeenCalledWith(
      "fixture.hello",
      "1.0.0",
    );
  });

  it("requires the secure desktop runtime for community packages", () => {
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "registry",
          official: false,
          browserRuntimeHtml: null,
        })}
      />,
    );

    expect(
      screen.getByText("此模块需要 Lumina 桌面版才能运行"),
    ).toBeInTheDocument();
    expect(screen.queryByTitle("Fixture Hello")).not.toBeInTheDocument();
  });

  it("uses the custom scheme for community packages in secure desktop mode", () => {
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "registry",
          official: false,
          browserRuntimeHtml: null,
        })}
        runtimeMode="desktop-secure"
      />,
    );

    expect(screen.getByTitle("Fixture Hello")).toHaveAttribute(
      "src",
      "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
    );
  });

  it("replaces real host data with synthetic handlers in unsafe browser development", async () => {
    const channel = channelFixture();
    const realRead = vi.fn().mockResolvedValue({
      id: "real-library",
    });
    const syntheticRead = vi.fn().mockResolvedValue({
      id: "synthetic-library",
    });
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "local",
          permissions: ["color-library.read"],
        })}
        runtimeMode="browser-unsafe-development"
        handlers={{ "colorLibrary.read": realRead }}
        syntheticHandlers={{
          "colorLibrary.read": syntheticRead,
        }}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest(
            "colorLibrary.read",
            {},
            "library-1",
          ),
        }),
      );
    });
    await waitFor(() =>
      expect(syntheticRead).toHaveBeenCalledTimes(1),
    );
    expect(realRead).not.toHaveBeenCalled();
  });
});

describe("Workshop runtime helpers", () => {
  it("builds one encoded custom-scheme desktop URL", () => {
    expect(
      desktopModuleUrl("fixture.hello", "1.0.0"),
    ).toBe(
      "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
    );
    expect(
      desktopModuleUrl("fixture.hello", "1.0.0+desktop.1"),
    ).toBe(
      "lumina-workshop://fixture.hello/1.0.0+desktop.1/ui/index.html",
    );
  });

  it("accepts only host API versions inside the manifest range", () => {
    expect(
      isWorkshopApiCompatible({
        min: "1.0.0",
        maxExclusive: "2.0.0",
      }),
    ).toBe(true);
    expect(
      isWorkshopApiCompatible({
        min: "1.1.0",
        maxExclusive: "2.0.0",
      }),
    ).toBe(false);
    expect(
      isWorkshopApiCompatible({
        min: "0.9.0",
        maxExclusive: "1.0.0",
      }),
    ).toBe(false);
  });
});
