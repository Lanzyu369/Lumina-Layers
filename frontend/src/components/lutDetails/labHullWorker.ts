/// <reference lib="webworker" />

import { Vector3 } from "three";
import { ConvexHull } from "three/examples/jsm/math/ConvexHull.js";

interface LabHullWorkerRequest {
  points: Float32Array | number[];
}

interface LabHullWorkerResponse {
  vertices: Float32Array;
  faces: Uint32Array;
}

function normalizePoints(points: Float32Array | number[] | undefined): Float32Array {
  if (points instanceof Float32Array) {
    return points;
  }
  return new Float32Array(points ?? []);
}

function buildFaces(points: Vector3[], hull: ConvexHull): Uint32Array {
  const pointIndex = new Map<Vector3, number>();
  points.forEach((point, index) => {
    pointIndex.set(point, index);
  });

  const faces: number[] = [];
  for (const face of hull.faces) {
    const indices: number[] = [];
    let edge = face.edge;

    do {
      const index = pointIndex.get(edge.head().point);
      if (index !== undefined) {
        indices.push(index);
      }
      edge = edge.next;
    } while (edge !== face.edge);

    if (indices.length < 3) {
      continue;
    }

    for (let triangleIndex = 1; triangleIndex < indices.length - 1; triangleIndex += 1) {
      faces.push(indices[0], indices[triangleIndex], indices[triangleIndex + 1]);
    }
  }

  return new Uint32Array(faces);
}

self.onmessage = (event: MessageEvent<LabHullWorkerRequest>) => {
  const vertices = normalizePoints(event.data?.points);
  if (vertices.length < 12 || vertices.length % 3 !== 0) {
    const emptyFaces = new Uint32Array(0);
    const response: LabHullWorkerResponse = { vertices, faces: emptyFaces };
    self.postMessage(response, [vertices.buffer, emptyFaces.buffer]);
    return;
  }

  const points: Vector3[] = [];
  for (let index = 0; index < vertices.length; index += 3) {
    points.push(new Vector3(vertices[index], vertices[index + 1], vertices[index + 2]));
  }

  const hull = new ConvexHull().setFromPoints(points);
  const faces = buildFaces(points, hull);
  const response: LabHullWorkerResponse = { vertices, faces };
  self.postMessage(response, [vertices.buffer, faces.buffer]);
};

export {};
