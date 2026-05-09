import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import type * as THREE from "three";
import { useConverterStore } from "../stores/converter";

// Mock i18n — return key as-is
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

// Mock child components that live inside Canvas (R3F components)
vi.mock("../components/ModelViewer", () => ({ default: () => null }));
let capturedInteractiveViewerProps: Record<string, unknown> | null = null;
vi.mock("../components/InteractiveModelViewer", () => ({
  default: (props: Record<string, unknown>) => {
    capturedInteractiveViewerProps = props;
    return null;
  },
  extractHexFromMeshName: (name: string) => name.slice(6),
}));
vi.mock("../components/BedPlatform", () => ({ default: () => null }));
vi.mock("../components/KeychainRing3D", () => ({ default: () => null }));
let capturedFridgeMagnet3DProps: Record<string, unknown> | null = null;
vi.mock("../components/FridgeMagnet3D", () => ({
  default: (props: Record<string, unknown>) => {
    capturedFridgeMagnet3DProps = props;
    return <div data-testid="mock-fridge-magnet-3d" />;
  },
}));

// Mock @react-three/drei — Environment renders a queryable DOM element
// Boolean false is dropped by React DOM, so we explicitly map props to data-* attributes
vi.mock("@react-three/drei", () => ({
  OrbitControls: () => null,
  Environment: (props: Record<string, unknown>) => (
    <div
      data-testid="mock-environment"
      data-files={String(props.files ?? "")}
      data-background={String(props.background ?? "")}
      data-environment-intensity={String(props.environmentIntensity ?? "")}
    />
  ),
  Html: ({ children, ...props }: Record<string, unknown> & { children?: React.ReactNode }) => (
    <div data-testid="mock-html" {...(props as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>
  ),
}));

// Override the global Canvas mock to capture onPointerMissed
let capturedCanvasProps: Record<string, unknown> = {};
function createMockGl() {
  const domElement = document.createElement("canvas");
  domElement.width = 800;
  domElement.height = 600;
  return {
    domElement,
    setClearColor: vi.fn(),
    getPixelRatio: vi.fn(() => 1),
    getContextAttributes: vi.fn(() => ({ preserveDrawingBuffer: true })),
    info: {
      memory: {
        geometries: 0,
        textures: 0,
      },
      programs: [],
      render: {
        calls: 0,
        triangles: 0,
        lines: 0,
        points: 0,
        frame: 0,
      },
    },
  };
}

// Shared mock state so every ``useThree`` call inside a single test returns
// the SAME references. Helpers like ``ScreenshotHelper`` and ``ThemeUpdater``
// depend on ``gl`` in their effect-deps; if the mock returned a fresh object
// per call, those effects would re-fire on every render, trigger
// ``setDiagnostics`` from ``handleGlReady``, and spin into an infinite loop
// that exhausts the Node heap (the symptom before this fix was a 60s OOM).
// ``beforeEach`` resets this so each test sees a fresh renderer-info + DOM
// canvas, matching the previous "new gl per test" intent.
// 共享 mock state：保证同一测试内每次 useThree 返回的 gl / scene / camera
// 引用一致，避免 ScreenshotHelper 等组件的 effect 每次 render 都重跑而
// 通过 handleGlReady 的 setDiagnostics 引发无限 re-render（原本表现为
// Scene3D.test.tsx 60s OOM 无一测试跑通）。
type MockThreeState = {
  gl: ReturnType<typeof createMockGl>;
  scene: { children: THREE.Object3D[] };
  camera: { position: { x: number; y: number; z: number } };
  controls: null;
  invalidate: ReturnType<typeof vi.fn>;
};
let mockThreeState: MockThreeState | null = null;
function getMockThreeState(): MockThreeState {
  if (!mockThreeState) {
    mockThreeState = {
      gl: createMockGl(),
      scene: { children: [] as THREE.Object3D[] },
      camera: { position: { x: 0, y: 0, z: 0 } },
      controls: null,
      invalidate: vi.fn(),
    };
  }
  return mockThreeState;
}

vi.mock("@react-three/fiber", () => ({
  Canvas: (props: Record<string, unknown> & { children?: React.ReactNode }) => {
    capturedCanvasProps = props;
    return <div data-testid="mock-canvas">{props.children}</div>;
  },
  useThree: (selector?: (state: MockThreeState) => unknown) => {
    const state = getMockThreeState();
    return selector ? selector(state) : state;
  },
  useFrame: vi.fn(),
}));

// Must import Scene3D after mocks are set up
import Scene3D from "../components/Scene3D";

describe("Scene3D", () => {
beforeEach(() => {
    capturedCanvasProps = {};
    capturedInteractiveViewerProps = null;
    capturedFridgeMagnet3DProps = null;
    // Reset the shared useThree state so each test gets a fresh renderer /
    // scene snapshot while every hook call within that test still sees
    // stable references.
    // 清空 useThree 的共享 state，保证每个 test 拿到新的 renderer/scene，
    // 同时保持同一 test 内引用稳定。
    mockThreeState = null;
    (window as Window & { __luminaThreePerfDebug?: boolean }).__luminaThreePerfDebug = false;
    // Reset store to defaults
      useConverterStore.setState({
        isLoading: false,
        previewGlbUrl: null,
        previewImageUrl: null,
        previewBaseImageUrl: null,
        puzzleEnabled: false,
        puzzleOverlayUrl: null,
        selectedColor: null,
        layerImages: [],
        layerImagesLoading: false,
        layerImagesOpen: false,
        layerImagesSourceKey: null,
        add_loop: false,
        enable_fridge_magnet: false,
        fridge_magnets: [],
        selectedFridgeMagnetId: null,
        modelBounds: null,
      });
  });

  describe("loading overlay (Req 1.4)", () => {
    it("renders loading overlay when isLoading is true", () => {
      useConverterStore.setState({ isLoading: true });
      render(<Scene3D />);
      expect(screen.getByTestId("loading-overlay")).toBeInTheDocument();
    });

    it("does not render loading overlay when isLoading is false", () => {
      useConverterStore.setState({ isLoading: false });
      render(<Scene3D />);
      expect(screen.queryByTestId("loading-overlay")).not.toBeInTheDocument();
    });

    it("loading overlay contains a spinner element", () => {
      useConverterStore.setState({ isLoading: true });
      render(<Scene3D />);
      const overlay = screen.getByTestId("loading-overlay");
      const spinner = overlay.querySelector(".rgb-loader-ring");
      expect(spinner).toBeInTheDocument();
    });
  });

  describe("fullscreen thumbnail removal (Req 9.3)", () => {
    it("does not render fullscreen-thumbnail element", () => {
      render(<Scene3D />);
      expect(
        screen.queryByTestId("fullscreen-thumbnail"),
      ).not.toBeInTheDocument();
    });

    it("does not render fullscreen-thumbnail even with previewImageUrl set", () => {
      useConverterStore.setState({
        previewImageUrl: "http://example.com/img.png",
      });
      render(<Scene3D />);
      expect(
        screen.queryByTestId("fullscreen-thumbnail"),
      ).not.toBeInTheDocument();
    });
  });

  describe("diagnostics overlay", () => {
    it("opens the diagnostics panel when the diagnostics button is clicked", () => {
      render(<Scene3D />);

      expect(screen.queryByTestId("scene3d-diagnostics-panel")).not.toBeInTheDocument();

      fireEvent.click(screen.getByTestId("scene3d-diagnostics-toggle"));

      expect(screen.getByTestId("scene3d-diagnostics-panel")).toBeInTheDocument();
    });
  });

  describe("onPointerMissed deselection (Req 2.5)", () => {
    it("Canvas receives onPointerMissed prop", () => {
      render(<Scene3D />);
      expect(capturedCanvasProps.onPointerMissed).toBeTypeOf("function");
    });

    it("clears selected fridge magnet on empty-canvas clicks while fridge mode is enabled", () => {
      useConverterStore.setState({
        enable_fridge_magnet: true,
        selectedFridgeMagnetId: "magnet-1",
      });
      render(<Scene3D />);

      act(() => {
        (capturedCanvasProps.onPointerMissed as () => void)();
      });

      expect(useConverterStore.getState().selectedFridgeMagnetId).toBeNull();
    });
  });

  describe("puzzle overlay wiring", () => {
    it("passes the live puzzle overlay into InteractiveModelViewer", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        puzzleEnabled: true,
        puzzleOverlayUrl: "/api/files/mock-puzzle-overlay.png",
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.puzzleOverlayEnabled).toBe(true);
      expect(capturedInteractiveViewerProps?.puzzleOverlayUrl).toBe(
        "/api/files/mock-puzzle-overlay.png",
      );
    });

    it("does not wire hover sampling props into InteractiveModelViewer", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        puzzleEnabled: true,
        puzzleOverlayUrl: "/api/files/mock-puzzle-overlay.png",
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.onHoverSample).toBeUndefined();
      expect(capturedInteractiveViewerProps?.hoverEnabled).toBeUndefined();
    });

  });

  describe("fridge magnet proxy wiring", () => {
    it("passes fridge mode into InteractiveModelViewer for outline preview handling", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        enable_fridge_magnet: true,
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.enableFridgeMagnet).toBe(true);
    });

    it("does not render the proxy layer when fridge mode is disabled", () => {
      useConverterStore.setState({
        enable_fridge_magnet: false,
        fridge_magnets: [{
          id: "magnet-1",
          shape: "round",
          preset_key: "round-d12x3",
          diameter_mm: 12,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3,
          center_x_mm: 0,
          center_y_mm: 0,
        }],
        modelBounds: {
          minX: -10,
          maxX: 10,
          minY: -10,
          maxY: 10,
          maxZ: 5,
        },
      });

      render(<Scene3D />);

      expect(screen.queryByTestId("mock-fridge-magnet-3d")).not.toBeInTheDocument();
      expect(capturedFridgeMagnet3DProps).toBeNull();
    });

    it("does not render the proxy layer without model bounds", () => {
      useConverterStore.setState({
        enable_fridge_magnet: true,
        fridge_magnets: [{
          id: "magnet-1",
          shape: "round",
          preset_key: "round-d12x3",
          diameter_mm: 12,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3,
          center_x_mm: 0,
          center_y_mm: 0,
        }],
        modelBounds: null,
      });

      render(<Scene3D />);

      expect(screen.queryByTestId("mock-fridge-magnet-3d")).not.toBeInTheDocument();
      expect(capturedFridgeMagnet3DProps).toBeNull();
    });

    it("passes fridge magnet state and actions into the proxy layer", () => {
      const fridgeMagnets = [{
        id: "magnet-1",
        shape: "round" as const,
        preset_key: "round-d12x3",
        diameter_mm: 12,
        width_mm: null,
        height_mm: null,
        thickness_mm: 3,
        center_x_mm: 2,
        center_y_mm: -1,
      }];
      const modelBounds = {
        minX: -10,
        maxX: 10,
        minY: -10,
        maxY: 10,
        maxZ: 5,
      };

      useConverterStore.setState({
        enable_fridge_magnet: true,
        fridge_magnets: fridgeMagnets,
        selectedFridgeMagnetId: "magnet-1",
        modelBounds,
        target_width_mm: 120,
        target_height_mm: 80,
        preview_width_mm: 60,
        preview_height_mm: 40,
      });

      render(<Scene3D />);

      expect(screen.getByTestId("mock-fridge-magnet-3d")).toBeInTheDocument();
      expect(capturedFridgeMagnet3DProps).toMatchObject({
        enabled: true,
        magnets: fridgeMagnets,
        selectedMagnetId: "magnet-1",
        modelBounds,
        scaleX: 2,
        scaleY: 2,
      });
      expect(capturedFridgeMagnet3DProps?.onSelectMagnet).toBe(
        useConverterStore.getState().selectFridgeMagnet,
      );
      expect(capturedFridgeMagnet3DProps?.onUpdateMagnetCenter).toBe(
        useConverterStore.getState().updateFridgeMagnetCenter,
      );
    });

  });

  describe("lighting (Environment optimization)", () => {
    it("does not render hemisphereLight", () => {
      const { container } = render(<Scene3D />);
      expect(container.querySelector("hemisphereLight")).toBeNull();
    });

    it("renders exactly one directionalLight", () => {
      const { container } = render(<Scene3D />);
      const lights = container.querySelectorAll("directionalLight");
      expect(lights.length).toBe(1);
    });

    it("renders Environment component with correct HDR file and background=false", () => {
      render(<Scene3D />);
      const env = screen.getByTestId("mock-environment");
      expect(env).toBeInTheDocument();
      expect(env.getAttribute("data-files")).toBe("/hdr/studio_small_09_1k.hdr");
      expect(env.getAttribute("data-background")).toBe("false");
    });

    it("key directional light position is right-upper-front", () => {
      const { container } = render(<Scene3D />);
      const light = container.querySelector("directionalLight");
      expect(light).not.toBeNull();
      // Position [200, 300, 500] — front-upper-right for vertical view
      const pos = light?.getAttribute("position");
      expect(pos).toBeTruthy();
    });

    it("Canvas clearColor uses theme config value", () => {
      render(<Scene3D />);
      expect(capturedCanvasProps.onCreated).toBeTypeOf("function");
      // Use the shared ``createMockGl`` helper so onCreated's downstream
      // ``getRendererInfoSnapshot(gl)`` / diagnostic logging see the same
      // renderer-info shape the mock already provides; the previous inline
      // stub only had ``setClearColor`` + ``domElement.addEventListener``,
      // which crashed the new PR #68 postClientLog path with
      // "Cannot read properties of undefined (reading 'programs')".
      // 复用 createMockGl：否则 onCreated 里走到 getRendererInfoSnapshot 会
      // 因为 gl.info/gl.getPixelRatio 缺失崩溃。
      const mockGl = createMockGl();
      (capturedCanvasProps.onCreated as (state: { gl: typeof mockGl }) => void)({
        gl: mockGl,
      });
      // Default theme is "light", so canvasClearColor should be "#e8e8ec"
      expect(mockGl.setClearColor).toHaveBeenCalledWith("#e8e8ec");
    });
  });

  describe("camera debug helper cleanup", () => {
    it("removes window.__luminaCameraDebug on unmount", () => {
      const { unmount } = render(<Scene3D />);

      expect(window.__luminaCameraDebug).toBeTypeOf("function");

      const debugRef = window.__luminaCameraDebug;
      unmount();

      expect(window.__luminaCameraDebug).toBeUndefined();
      expect(debugRef).toBeTypeOf("function");
    });
  });
});
