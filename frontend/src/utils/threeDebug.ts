import * as THREE from "three";

type ThreePerfDebugConfigInput =
  | boolean
  | {
      enabled?: boolean;
      intervalMs?: number;
    };

interface HeapMemoryInfo {
  usedJSHeapSize: number;
  totalJSHeapSize: number;
  jsHeapSizeLimit: number;
}

declare global {
  interface Window {
    __luminaThreePerfDebug?: ThreePerfDebugConfigInput;
  }
}

function roundNumber(value: number, digits: number = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function normalizeInterval(intervalMs: number | undefined): number {
  if (!intervalMs || !Number.isFinite(intervalMs)) {
    return 1500;
  }
  return Math.max(500, Math.round(intervalMs));
}

export function getThreePerfDebugConfig(): {
  enabled: boolean;
  intervalMs: number;
} {
  if (typeof window === "undefined") {
    return { enabled: false, intervalMs: 1500 };
  }

  const raw = window.__luminaThreePerfDebug;
  if (raw == null) {
    return { enabled: import.meta.env.DEV, intervalMs: 1500 };
  }
  if (typeof raw === "boolean") {
    return { enabled: raw, intervalMs: 1500 };
  }
  return {
    enabled: raw.enabled !== false,
    intervalMs: normalizeInterval(raw.intervalMs),
  };
}

export function isThreePerfDebugEnabled(): boolean {
  return getThreePerfDebugConfig().enabled;
}

export function debugThreeLog(
  scope: string,
  payload: Record<string, unknown>,
  level: "info" | "warn" = "info",
): void {
  if (!isThreePerfDebugEnabled()) {
    return;
  }
  console[level](`[ThreePerf][${scope}]`, payload);
}

function collectTexturesFromMaterial(
  material: THREE.Material,
  textureSet: Set<THREE.Texture>,
): void {
  for (const value of Object.values(material as unknown as Record<string, unknown>)) {
    if (value instanceof THREE.Texture) {
      textureSet.add(value);
    }
  }
}

function countTriangles(geometry: THREE.BufferGeometry): number {
  const index = geometry.getIndex();
  if (index) {
    return Math.floor(index.count / 3);
  }
  const position = geometry.getAttribute("position");
  return position ? Math.floor(position.count / 3) : 0;
}

export function summarizeMeshList(meshes: THREE.Mesh[]): {
  mesh_count: number;
  geometry_count: number;
  material_count: number;
  texture_count: number;
  triangle_count: number;
} {
  const geometrySet = new Set<THREE.BufferGeometry>();
  const materialSet = new Set<THREE.Material>();
  const textureSet = new Set<THREE.Texture>();
  let triangleCount = 0;

  for (const mesh of meshes) {
    geometrySet.add(mesh.geometry);
    triangleCount += countTriangles(mesh.geometry);
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) {
      if (!material) {
        continue;
      }
      materialSet.add(material);
      collectTexturesFromMaterial(material, textureSet);
    }
  }

  return {
    mesh_count: meshes.length,
    geometry_count: geometrySet.size,
    material_count: materialSet.size,
    texture_count: textureSet.size,
    triangle_count: triangleCount,
  };
}

export function summarizeObjectTree(
  root: THREE.Object3D | null | undefined,
): {
  object_count: number;
  mesh_count: number;
  line_count: number;
  points_count: number;
  geometry_count: number;
  material_count: number;
  texture_count: number;
  triangle_count: number;
} {
  if (!root) {
    return {
      object_count: 0,
      mesh_count: 0,
      line_count: 0,
      points_count: 0,
      geometry_count: 0,
      material_count: 0,
      texture_count: 0,
      triangle_count: 0,
    };
  }

  const geometrySet = new Set<THREE.BufferGeometry>();
  const materialSet = new Set<THREE.Material>();
  const textureSet = new Set<THREE.Texture>();
  let objectCount = 0;
  let meshCount = 0;
  let lineCount = 0;
  let pointsCount = 0;
  let triangleCount = 0;

  root.traverse((child) => {
    objectCount += 1;
    if (child instanceof THREE.Mesh) {
      meshCount += 1;
      geometrySet.add(child.geometry);
      triangleCount += countTriangles(child.geometry);
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      for (const material of materials) {
        if (!material) {
          continue;
        }
        materialSet.add(material);
        collectTexturesFromMaterial(material, textureSet);
      }
      return;
    }
    if (child instanceof THREE.Line) {
      lineCount += 1;
      return;
    }
    if (child instanceof THREE.Points) {
      pointsCount += 1;
    }
  });

  return {
    object_count: objectCount,
    mesh_count: meshCount,
    line_count: lineCount,
    points_count: pointsCount,
    geometry_count: geometrySet.size,
    material_count: materialSet.size,
    texture_count: textureSet.size,
    triangle_count: triangleCount,
  };
}

export function getRendererInfoSnapshot(gl: THREE.WebGLRenderer): {
  geometries: number;
  textures: number;
  programs: number | null;
  calls: number;
  triangles: number;
  lines: number;
  points: number;
  frame: number;
  pixel_ratio: number;
  canvas_width: number;
  canvas_height: number;
  preserve_drawing_buffer: boolean | null;
} {
  const info = gl.info;
  const rawPrograms = (info as unknown as { programs?: { length: number } | unknown[] }).programs;
  const programCount = Array.isArray(rawPrograms)
    ? rawPrograms.length
    : rawPrograms && typeof rawPrograms === "object" && "length" in rawPrograms
      ? Number(rawPrograms.length)
      : null;
  const contextAttributes = gl.getContextAttributes();

  return {
    geometries: info.memory.geometries,
    textures: info.memory.textures,
    programs: programCount,
    calls: info.render.calls,
    triangles: info.render.triangles,
    lines: info.render.lines,
    points: info.render.points,
    frame: info.render.frame,
    pixel_ratio: roundNumber(gl.getPixelRatio(), 2),
    canvas_width: gl.domElement.width,
    canvas_height: gl.domElement.height,
    preserve_drawing_buffer: contextAttributes?.preserveDrawingBuffer ?? null,
  };
}

export function getHeapMemorySnapshot(): {
  used_js_heap_mb: number;
  total_js_heap_mb: number;
  js_heap_limit_mb: number;
} | null {
  if (typeof performance === "undefined") {
    return null;
  }

  const memory = (performance as Performance & { memory?: HeapMemoryInfo }).memory;
  if (!memory) {
    return null;
  }

  return {
    used_js_heap_mb: roundNumber(memory.usedJSHeapSize / (1024 * 1024), 2),
    total_js_heap_mb: roundNumber(memory.totalJSHeapSize / (1024 * 1024), 2),
    js_heap_limit_mb: roundNumber(memory.jsHeapSizeLimit / (1024 * 1024), 2),
  };
}

export function getLatestResourceTiming(url: string): {
  duration_ms: number;
  transfer_size_kb: number;
  decoded_body_kb: number;
  initiator_type: string | null;
} | null {
  if (typeof performance === "undefined" || typeof window === "undefined") {
    return null;
  }

  let absoluteUrl = url;
  try {
    absoluteUrl = new URL(url, window.location.href).toString();
  } catch {
    absoluteUrl = url;
  }

  const entries = performance
    .getEntriesByType("resource")
    .filter(
      (entry): entry is PerformanceResourceTiming =>
        "initiatorType" in entry && entry.name === absoluteUrl,
    );
  const latest = entries[entries.length - 1];
  if (!latest) {
    return null;
  }

  return {
    duration_ms: roundNumber(latest.duration, 2),
    transfer_size_kb: roundNumber(latest.transferSize / 1024, 2),
    decoded_body_kb: roundNumber(latest.decodedBodySize / 1024, 2),
    initiator_type: latest.initiatorType || null,
  };
}

export function bytesToMiB(bytes: number): number {
  return roundNumber(bytes / (1024 * 1024), 2);
}
