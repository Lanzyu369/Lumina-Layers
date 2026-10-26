import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { computeCoatingPreviewLayers } from "./creativePreview3DUtils";
import { buildExpandedFootprintGeometry } from "./OutlineFrame3D";

export interface CoatingPreview3DProps {
  enabled: boolean;
  backingMesh: THREE.Mesh | null;
  coatingHeightMm: number;
  layerHeightMm: number;
  structureMode: string;
  enableRelief: boolean;
  spacerThickMm: number;
  visibleColorHeightMm: number;
  enableOutline: boolean;
  outlineWidthMm: number;
  displayScale?: number;
  rasterCellSize?: number;
}

/** Show the transparent coating as thin shells around the lightweight model. */
export default function CoatingPreview3D({
  enabled,
  backingMesh,
  coatingHeightMm,
  layerHeightMm,
  structureMode,
  enableRelief,
  spacerThickMm,
  visibleColorHeightMm,
  enableOutline,
  outlineWidthMm,
  displayScale = 1,
  rasterCellSize,
}: CoatingPreview3DProps) {
  const [expandedGeometry, setExpandedGeometry] =
    useState<THREE.BufferGeometry | null>(null);
  const material = useMemo(() => new THREE.MeshPhysicalMaterial({
    color: 0xdde7ef,
    transparent: true,
    opacity: 0.3,
    roughness: 0.22,
    metalness: 0,
    depthWrite: false,
    side: THREE.DoubleSide,
  }), []);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => {
    const geometry = enabled
      && backingMesh
      && enableOutline
      && outlineWidthMm > 0
      ? buildExpandedFootprintGeometry({
          backingPlateMesh: backingMesh,
          expansionMm: outlineWidthMm / Math.max(displayScale, 1e-6),
          rasterCellSize,
        })
      : null;
    setExpandedGeometry(geometry);
    return () => geometry?.dispose();
  }, [
    backingMesh,
    enableOutline,
    enabled,
    displayScale,
    outlineWidthMm,
    rasterCellSize,
  ]);
  const descriptors = useMemo(() => {
    if (!enabled || !backingMesh) return [];
    const geometry = expandedGeometry ?? backingMesh.geometry;
    geometry.computeBoundingBox();
    const bounds = geometry.boundingBox;
    if (!bounds) return [];
    const nativeHeight = bounds.max.z - bounds.min.z;
    if (!Number.isFinite(nativeHeight) || nativeHeight <= 0) return [];
    return computeCoatingPreviewLayers({
      coatingHeightMm,
      layerHeightMm,
      structureMode,
      enableRelief,
      spacerThickMm,
      visibleColorHeightMm,
    }).map((layer) => {
      const layerHeight = layer.zMax - layer.zMin;
      const scaleZ = layerHeight / nativeHeight;
      return {
        position: [
          expandedGeometry ? 0 : backingMesh.position.x,
          expandedGeometry ? 0 : backingMesh.position.y,
          layer.zMin - bounds.min.z * scaleZ,
        ] as [number, number, number],
        scaleX: expandedGeometry ? 1 : backingMesh.scale.x,
        scaleY: expandedGeometry ? 1 : backingMesh.scale.y,
        scaleZ,
      };
    });
  }, [
    backingMesh,
    coatingHeightMm,
    expandedGeometry,
    enableRelief,
    enabled,
    layerHeightMm,
    spacerThickMm,
    structureMode,
    visibleColorHeightMm,
  ]);

  if (!enabled || !backingMesh || descriptors.length === 0) return null;
  const geometry = expandedGeometry ?? backingMesh.geometry;
  return (
    <>
      {descriptors.map((descriptor, index) => (
        <mesh
          key={`${index}-${descriptor.position[2]}`}
          name={index === 0 ? "coating_bottom" : "coating_top"}
          geometry={geometry}
          material={material}
          dispose={null}
          position={descriptor.position}
          scale={[descriptor.scaleX, descriptor.scaleY, descriptor.scaleZ]}
          renderOrder={25}
        />
      ))}
    </>
  );
}
