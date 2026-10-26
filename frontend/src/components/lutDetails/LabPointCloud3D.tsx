import { Canvas } from "@react-three/fiber";
import PreviewOrbitControls from "../ui/PreviewOrbitControls";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { LutDetailsPoint3D } from "../../api/types";
import Slider from "../ui/Slider";
import {
  getHullEdgeMaterialProps,
  getHullFillMaterialProps,
  getReferenceSliceMaterialProps,
  HULL_EDGE_RENDER_ORDER,
  POINT_RENDER_ORDER,
  REFERENCE_SLICE_RENDER_ORDER,
  HULL_RENDER_ORDER,
} from "./labPointCloud3DConfig";
import {
  getOrCreateReferenceSliceData,
  getReferenceSliceKey,
  getReferenceSliceWindowLightnesses,
  trimReferenceSliceCache,
  upsertReferenceSliceTexture,
} from "./labReferenceSliceTexture";

type HullState = "idle" | "loading" | "ready" | "error";

interface HullGeometryData {
  vertices: Float32Array;
  faces: Uint32Array;
}

interface LabPointCloud3DProps {
  dataTestId: string;
  points: LutDetailsPoint3D[];
  emptyMessage: string;
  loadingHullMessage: string;
  hullErrorMessage: string;
  axisXLabel: string;
  axisYLabel: string;
  axisZLabel: string;
  referenceSliceToggleLabel: string;
  referenceSliceStatusTemplate: string;
  referenceSliceSliderLabel: string;
}

let HULL_CACHE = new WeakMap<LutDetailsPoint3D[], HullGeometryData>();
const VIEWPORT_HEIGHT_RATIO = 0.82;
const MIN_VIEWPORT_HEIGHT = 320;
const MAX_VIEWPORT_HEIGHT = 720;
const REFERENCE_A_MIN = -120;
const REFERENCE_A_MAX = 120;
const REFERENCE_B_MIN = -120;
const REFERENCE_B_MAX = 120;
const REFERENCE_L_MIN = 0;
const REFERENCE_L_MAX = 100;

function roundKey(value: number): string {
  return value.toFixed(6);
}

function buildUniqueHullInput(points: LutDetailsPoint3D[]): Float32Array {
  const seen = new Set<string>();
  const values: number[] = [];

  for (const point of points) {
    const key = `${roundKey(point.a)}|${roundKey(point.l)}|${roundKey(point.b)}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    values.push(point.a, point.l, point.b);
  }

  return new Float32Array(values);
}

function buildPointPositions(points: LutDetailsPoint3D[]): Float32Array {
  const values = new Float32Array(points.length * 3);
  for (let index = 0; index < points.length; index += 1) {
    const offset = index * 3;
    const point = points[index];
    values[offset] = point.a;
    values[offset + 1] = point.l;
    values[offset + 2] = point.b;
  }
  return values;
}

function buildPointColors(points: LutDetailsPoint3D[]): Float32Array {
  const values = new Float32Array(points.length * 3);
  for (let index = 0; index < points.length; index += 1) {
    const offset = index * 3;
    const [r, g, b] = points[index]?.rgb ?? [148, 163, 184];
    values[offset] = r / 255;
    values[offset + 1] = g / 255;
    values[offset + 2] = b / 255;
  }
  return values;
}

function computeBounds(points: Float32Array) {
  if (points.length === 0) {
    return {
      minX: -60,
      maxX: 60,
      minY: 0,
      maxY: 100,
      minZ: -60,
      maxZ: 60,
      center: [0, 50, 0] as [number, number, number],
      radius: 120,
    };
  }

  let minX = points[0];
  let maxX = points[0];
  let minY = points[1];
  let maxY = points[1];
  let minZ = points[2];
  let maxZ = points[2];

  for (let index = 0; index < points.length; index += 3) {
    minX = Math.min(minX, points[index]);
    maxX = Math.max(maxX, points[index]);
    minY = Math.min(minY, points[index + 1]);
    maxY = Math.max(maxY, points[index + 1]);
    minZ = Math.min(minZ, points[index + 2]);
    maxZ = Math.max(maxZ, points[index + 2]);
  }

  const spanX = maxX - minX;
  const spanY = maxY - minY;
  const spanZ = maxZ - minZ;
  const radius = Math.max(spanX, spanY, spanZ, 60);

  return {
    minX,
    maxX,
    minY,
    maxY,
    minZ,
    maxZ,
    center: [
      (minX + maxX) / 2,
      (minY + maxY) / 2,
      (minZ + maxZ) / 2,
    ] as [number, number, number],
    radius,
  };
}

function expandBoundsForReferenceSlice(bounds: ReturnType<typeof computeBounds>) {
  return {
    minX: Math.min(bounds.minX, REFERENCE_A_MIN),
    maxX: Math.max(bounds.maxX, REFERENCE_A_MAX),
    minY: Math.min(bounds.minY, REFERENCE_L_MIN),
    maxY: Math.max(bounds.maxY, REFERENCE_L_MAX),
    minZ: Math.min(bounds.minZ, REFERENCE_B_MIN),
    maxZ: Math.max(bounds.maxZ, REFERENCE_B_MAX),
    center: [
      (Math.min(bounds.minX, REFERENCE_A_MIN) + Math.max(bounds.maxX, REFERENCE_A_MAX)) / 2,
      (Math.min(bounds.minY, REFERENCE_L_MIN) + Math.max(bounds.maxY, REFERENCE_L_MAX)) / 2,
      (Math.min(bounds.minZ, REFERENCE_B_MIN) + Math.max(bounds.maxZ, REFERENCE_B_MAX)) / 2,
    ] as [number, number, number],
    radius: Math.max(
      Math.max(bounds.maxX, REFERENCE_A_MAX) - Math.min(bounds.minX, REFERENCE_A_MIN),
      Math.max(bounds.maxY, REFERENCE_L_MAX) - Math.min(bounds.minY, REFERENCE_L_MIN),
      Math.max(bounds.maxZ, REFERENCE_B_MAX) - Math.min(bounds.minZ, REFERENCE_B_MIN),
      60,
    ),
  };
}

function normalizeHullData(data: unknown): HullGeometryData | null {
  if (!data || typeof data !== "object") {
    return null;
  }

  const candidate = data as { vertices?: Float32Array | number[]; faces?: Uint32Array | number[] };
  const vertices = candidate.vertices instanceof Float32Array
    ? candidate.vertices
    : Array.isArray(candidate.vertices)
      ? new Float32Array(candidate.vertices)
      : null;
  const faces = candidate.faces instanceof Uint32Array
    ? candidate.faces
    : Array.isArray(candidate.faces)
      ? new Uint32Array(candidate.faces)
      : null;

  if (!vertices || !faces) {
    return null;
  }

  return { vertices, faces };
}

function getPointSize(pointCount: number): number {
  if (pointCount >= 5000) return 3;
  if (pointCount >= 2000) return 3.6;
  if (pointCount >= 800) return 4.2;
  return 4.8;
}

function deriveViewportHeight(width: number): number {
  if (!Number.isFinite(width) || width <= 0) {
    return 440;
  }
  return Math.round(Math.min(MAX_VIEWPORT_HEIGHT, Math.max(MIN_VIEWPORT_HEIGHT, width * VIEWPORT_HEIGHT_RATIO)));
}

function clampReferenceLightness(value: number): number {
  return Math.min(REFERENCE_L_MAX, Math.max(REFERENCE_L_MIN, value));
}

function createHullWorker(): Worker {
  return new Worker(new URL("./labHullWorker.ts", import.meta.url), { type: "module" });
}

export function clearLabPointCloud3DHullCacheForTests(): void {
  HULL_CACHE = new WeakMap();
}

export default function LabPointCloud3D({
  dataTestId,
  points,
  emptyMessage,
  loadingHullMessage,
  hullErrorMessage,
  axisXLabel,
  axisYLabel,
  axisZLabel,
  referenceSliceToggleLabel,
  referenceSliceStatusTemplate,
  referenceSliceSliderLabel,
}: LabPointCloud3DProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hullState, setHullState] = useState<HullState>(() => (HULL_CACHE.has(points) ? "ready" : "idle"));
  const [hullError, setHullError] = useState<string | null>(null);
  const [hullData, setHullData] = useState<HullGeometryData | null>(() => HULL_CACHE.get(points) ?? null);
  const [showReferenceSlice, setShowReferenceSlice] = useState(false);
  const [viewportHeight, setViewportHeight] = useState<number>(440);
  const workerRef = useRef<Worker | null>(null);
  const requestRef = useRef(0);
  const referenceSliceCacheRef = useRef<Map<number, Uint8Array>>(new Map());
  const referenceSliceTextureRef = useRef<THREE.DataTexture | null>(null);

  const pointPositions = useMemo(() => buildPointPositions(points), [points]);
  const pointColors = useMemo(() => buildPointColors(points), [points]);
  const uniqueHullInput = useMemo(() => buildUniqueHullInput(points), [points]);
  const pointBounds = useMemo(() => computeBounds(pointPositions), [pointPositions]);
  const displayBounds = useMemo(
    () => (showReferenceSlice ? expandBoundsForReferenceSlice(pointBounds) : pointBounds),
    [pointBounds, showReferenceSlice],
  );
  const defaultReferenceSliceLightness = useMemo(
    () => Number(clampReferenceLightness(pointBounds.center[1]).toFixed(1)),
    [pointBounds.center],
  );
  const [referenceSliceLightness, setReferenceSliceLightness] = useState<number>(defaultReferenceSliceLightness);
  const cameraPosition = useMemo<[number, number, number]>(
    () => [
      displayBounds.center[0] + displayBounds.radius * 1.4,
      displayBounds.center[1] + displayBounds.radius * 1.2,
      displayBounds.center[2] + displayBounds.radius * 1.4,
    ],
    [displayBounds.center, displayBounds.radius],
  );
  const referenceSliceData = useMemo(() => {
    if (!showReferenceSlice) {
      return null;
    }

    const data = getOrCreateReferenceSliceData(referenceSliceCacheRef.current, referenceSliceLightness);
    trimReferenceSliceCache(referenceSliceCacheRef.current, referenceSliceLightness);
    return data;
  }, [referenceSliceLightness, showReferenceSlice]);
  const referenceSliceTexture = useMemo(() => {
    if (!showReferenceSlice || !referenceSliceData) {
      return null;
    }

    const texture = upsertReferenceSliceTexture(referenceSliceTextureRef.current, referenceSliceData);
    referenceSliceTextureRef.current = texture;
    return texture;
  }, [referenceSliceData, showReferenceSlice]);
  const referenceSliceDimensions = useMemo(
    () => ({
      width: REFERENCE_A_MAX - REFERENCE_A_MIN,
      height: REFERENCE_B_MAX - REFERENCE_B_MIN,
    }),
    [],
  );

  useEffect(() => {
    setReferenceSliceLightness(defaultReferenceSliceLightness);
  }, [defaultReferenceSliceLightness, points]);

  useEffect(() => {
    if (!showReferenceSlice) {
      return;
    }

    const cache = referenceSliceCacheRef.current;
    const centerKey = getReferenceSliceKey(referenceSliceLightness);
    const pendingLightnesses = getReferenceSliceWindowLightnesses(referenceSliceLightness)
      .filter((lightness) => getReferenceSliceKey(lightness) !== centerKey)
      .filter((lightness) => !cache.has(getReferenceSliceKey(lightness)));

    if (pendingLightnesses.length === 0) {
      return;
    }

    let cancelled = false;
    let timeoutId: number | null = null;

    const warmNext = () => {
      if (cancelled) {
        return;
      }

      const nextLightness = pendingLightnesses.shift();
      if (nextLightness === undefined) {
        return;
      }

      getOrCreateReferenceSliceData(cache, nextLightness);
      trimReferenceSliceCache(cache, referenceSliceLightness);

      if (pendingLightnesses.length > 0) {
        timeoutId = window.setTimeout(warmNext, 0);
      }
    };

    timeoutId = window.setTimeout(warmNext, 0);

    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [referenceSliceLightness, showReferenceSlice]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const updateHeight = (width: number) => {
      setViewportHeight(deriveViewportHeight(width));
    };

    updateHeight(container.getBoundingClientRect().width || container.clientWidth);

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      const nextWidth = entry?.contentRect.width ?? container.getBoundingClientRect().width ?? container.clientWidth;
      updateHeight(nextWidth);
    });

    observer.observe(container);
    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const cached = HULL_CACHE.get(points);
    if (cached) {
      setHullData(cached);
      setHullState("ready");
      setHullError(null);
      return;
    }

    setHullData(null);
    setHullError(null);

    if (uniqueHullInput.length < 12) {
      setHullState("idle");
      return;
    }

    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setHullState("loading");

    const worker = createHullWorker();
    workerRef.current = worker;

    worker.onmessage = (event: MessageEvent) => {
      if (requestRef.current !== requestId) {
        return;
      }
      const nextHull = normalizeHullData(event.data);
      if (!nextHull) {
        setHullState("error");
        setHullError(hullErrorMessage);
        return;
      }
      HULL_CACHE.set(points, nextHull);
      setHullData(nextHull);
      setHullState("ready");
      setHullError(null);
      worker.terminate();
      if (workerRef.current === worker) {
        workerRef.current = null;
      }
    };

    worker.onerror = () => {
      if (requestRef.current !== requestId) {
        return;
      }
      setHullState("error");
      setHullError(hullErrorMessage);
      worker.terminate();
      if (workerRef.current === worker) {
        workerRef.current = null;
      }
    };

    worker.postMessage({ points: uniqueHullInput });

    return () => {
      worker.terminate();
      if (workerRef.current === worker) {
        workerRef.current = null;
      }
    };
  }, [points, hullErrorMessage, uniqueHullInput]);

  const pointGeometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(pointPositions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(pointColors, 3));
    geometry.computeBoundingSphere();
    return geometry;
  }, [pointColors, pointPositions]);

  useEffect(() => () => {
    pointGeometry.dispose();
  }, [pointGeometry]);

  const hullGeometry = useMemo(() => {
    if (!hullData || hullData.vertices.length === 0 || hullData.faces.length === 0) {
      return null;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(hullData.vertices, 3));
    geometry.setIndex(new THREE.BufferAttribute(hullData.faces, 1));
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    return geometry;
  }, [hullData]);

  useEffect(() => () => {
    hullGeometry?.dispose();
  }, [hullGeometry]);

  const hullEdgesGeometry = useMemo(() => {
    if (!hullGeometry) {
      return null;
    }
    return new THREE.EdgesGeometry(hullGeometry);
  }, [hullGeometry]);

  useEffect(() => () => {
    hullEdgesGeometry?.dispose();
  }, [hullEdgesGeometry]);

  useEffect(() => () => {
    referenceSliceTextureRef.current?.dispose();
    referenceSliceTextureRef.current = null;
    referenceSliceCacheRef.current.clear();
  }, []);

  if (points.length === 0) {
    return (
      <div data-testid={dataTestId} data-hull-state="idle">
        <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      data-testid={dataTestId}
      data-hull-state={hullState}

      className="flex flex-col gap-3"
    >
      <div
        className="overflow-hidden rounded-[24px] border border-slate-200/80 dark:border-slate-700/80"
        style={{ background: "var(--surface-section-muted)" }}
      >
        <div
          data-testid={`${dataTestId}-viewport`}
          className="w-full"
          style={{ height: `${viewportHeight}px` }}
        >
          <Canvas
            frameloop="demand"
            camera={{
              position: cameraPosition,
              fov: 38,
              near: 0.1,
              far: Math.max(displayBounds.radius * 12, 800),
            }}
          >
            <ambientLight intensity={0.9} />
            <directionalLight position={[120, 160, 80]} intensity={1.1} />
            <directionalLight position={[-120, 40, -120]} intensity={0.5} />
            <axesHelper args={[Math.max(displayBounds.radius * 0.6, 30)]} />
            {showReferenceSlice && referenceSliceTexture ? (
              <mesh
                position={[
                  (REFERENCE_A_MIN + REFERENCE_A_MAX) / 2,
                  referenceSliceLightness,
                  (REFERENCE_B_MIN + REFERENCE_B_MAX) / 2,
                ]}
                rotation={[-Math.PI / 2, 0, 0]}
                renderOrder={REFERENCE_SLICE_RENDER_ORDER}
              >
                <planeGeometry args={[referenceSliceDimensions.width, referenceSliceDimensions.height]} />
                <meshBasicMaterial
                  map={referenceSliceTexture}
                  {...getReferenceSliceMaterialProps()}
                />
              </mesh>
            ) : null}
            <points geometry={pointGeometry} renderOrder={POINT_RENDER_ORDER}>
              <pointsMaterial
                size={getPointSize(points.length)}
                sizeAttenuation
                vertexColors
                transparent
                opacity={0.96}
              />
            </points>
            {hullGeometry ? (
              <>
                <mesh geometry={hullGeometry} renderOrder={HULL_RENDER_ORDER}>
                  <meshBasicMaterial
                    {...getHullFillMaterialProps()}
                  />
                </mesh>
                {hullEdgesGeometry ? (
                  <lineSegments geometry={hullEdgesGeometry} renderOrder={HULL_EDGE_RENDER_ORDER}>
                    <lineBasicMaterial {...getHullEdgeMaterialProps()} />
                  </lineSegments>
                ) : null}
              </>
            ) : null}
            <PreviewOrbitControls
              enablePan={false}
              enableDamping
              target={displayBounds.center}
            />
          </Canvas>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
            showReferenceSlice
              ? "border-blue-400/60 bg-blue-500 text-white"
              : "border-slate-200/80 bg-white/80 text-slate-600 hover:bg-slate-100 dark:border-slate-700/80 dark:bg-slate-900/60 dark:text-slate-300 dark:hover:bg-slate-800"
          }`}
          aria-pressed={showReferenceSlice}
          onClick={() => setShowReferenceSlice((current) => !current)}
        >
          {referenceSliceToggleLabel}
        </button>
        {showReferenceSlice ? (
          <>
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
              {referenceSliceStatusTemplate.replace("{lightness}", referenceSliceLightness.toFixed(1))}
            </span>
            <span
              data-testid={`${dataTestId}-reference-slice`}
              data-reference-lightness={referenceSliceLightness.toFixed(1)}
              aria-hidden="true"
              className="hidden"
            />
          </>
        ) : null}
      </div>
      {showReferenceSlice ? (
        <Slider
          label={referenceSliceSliderLabel}
          value={referenceSliceLightness}
          min={REFERENCE_L_MIN}
          max={REFERENCE_L_MAX}
          step={0.5}
          onChange={(value) => setReferenceSliceLightness(clampReferenceLightness(value))}
          displayDecimals={1}
        />
      ) : null}

      <div className="flex flex-wrap gap-3 text-xs font-medium text-slate-500 dark:text-slate-400">
        <span>{axisXLabel}</span>
        <span>{axisYLabel}</span>
        <span>{axisZLabel}</span>
      </div>

      {hullState === "loading" ? (
        <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{loadingHullMessage}</p>
      ) : null}
      {hullError ? (
        <p className="text-sm leading-6 text-red-600 dark:text-red-300">{hullError}</p>
      ) : null}
    </div>
  );
}
