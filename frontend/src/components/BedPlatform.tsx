import { useMemo, useEffect, useLayoutEffect, useState } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { getMachineBedModelUrl } from "../api/system";
import { electronAPI } from "../integrations/electron";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { getSlicerLogoSource } from "../utils/slicerBranding";
import { disposeMeshResources } from "../utils/threeDisposal";
import { resolveBedPlatformColors } from "./themeConfig";
import {
  LUMINA_BED_MARK_URL,
  createBedTextureRequest,
  stageBedTextureReplacement,
} from "./bedPlatformTexture";
import {
  computeBedPreviewCameraPose,
  createFallbackBedGeometry,
  loadNativeBedGeometrySource,
  prepareNativeBedGeometry,
} from "./bedPlatformGeometry";

function useBedImage(source: string | null): HTMLImageElement | null {
  const [markImage, setMarkImage] = useState<HTMLImageElement | null>(null);

  useEffect(() => {
    setMarkImage(null);
    if (!source) return;
    let active = true;
    const image = new Image();
    const handleLoad = () => {
      if (active) setMarkImage(image);
    };
    image.addEventListener("load", handleLoad, { once: true });
    image.src = source;
    return () => {
      active = false;
      image.removeEventListener("load", handleLoad);
    };
  }, [source]);

  return markImage;
}

function imageElementToDataUrl(image: HTMLImageElement | null): string | null {
  if (!image) return null;
  if (image.currentSrc.startsWith("data:")) return image.currentSrc;

  const sourceWidth = image.naturalWidth || image.width;
  const sourceHeight = image.naturalHeight || image.height;
  if (sourceWidth <= 0 || sourceHeight <= 0) return null;

  const canvas = document.createElement("canvas");
  canvas.width = sourceWidth;
  canvas.height = sourceHeight;
  const context = canvas.getContext("2d");
  if (!context) return null;

  try {
    context.drawImage(image, 0, 0, sourceWidth, sourceHeight);
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

function useNativeBedGeometry(
  deviceProfileId: string,
  printableWidthMm: number,
  printableHeightMm: number,
): THREE.BufferGeometry | null {
  const modelUrl = useMemo(
    () => getMachineBedModelUrl(deviceProfileId),
    [deviceProfileId],
  );
  const [loaded, setLoaded] = useState<{
    url: string;
    geometry: THREE.BufferGeometry;
  } | null>(null);

  useEffect(() => {
    if (!modelUrl) {
      setLoaded(null);
      return;
    }
    let active = true;
    let ownedGeometry: THREE.BufferGeometry | null = null;
    const loader = new STLLoader();
    void loadNativeBedGeometrySource({
      desktopModelReader: electronAPI?.getNativeBedModel,
      deviceProfileId,
      loader,
      modelUrl,
    })
      .then((sourceGeometry) => {
        if (!sourceGeometry) {
          if (active) setLoaded(null);
          return;
        }
        const prepared = prepareNativeBedGeometry(
          sourceGeometry,
          printableWidthMm,
          printableHeightMm,
        );
        sourceGeometry.dispose();
        if (!active) {
          prepared.dispose();
          return;
        }
        ownedGeometry = prepared;
        setLoaded({ url: modelUrl, geometry: prepared });
      })
      .catch(() => {
        if (active) setLoaded(null);
      });
    return () => {
      active = false;
      ownedGeometry?.dispose();
    };
  }, [deviceProfileId, modelUrl, printableWidthMm, printableHeightMm]);

  return loaded?.url === modelUrl ? loaded.geometry : null;
}

interface BedPlatformProps {
  surfaceModelActive?: boolean;
  gridVisible?: boolean;
}

export default function BedPlatform({
  surfaceModelActive = false,
  gridVisible = true,
}: BedPlatformProps) {
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const modelUrl = useConverterStore((s) => s.modelUrl);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const batchPreviewItems = useConverterStore((s) => s.batchPreviewItems);
  const theme = useSettingsStore((s) => s.theme);
  const buildPlateId = useSettingsStore((s) => s.buildPlateId);
  const deviceProfileId = useSettingsStore((s) => s.deviceProfileId);
  const slicerSoftware = useSettingsStore((s) => s.slicerSoftware);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);

  const selectedBed = useMemo(
    () => bedSizes.find((bed) => bed.label === bed_label),
    [bedSizes, bed_label],
  );

  const bedDims = useMemo(() => {
    return selectedBed
      ? { w: selectedBed.width_mm, h: selectedBed.height_mm }
      : { w: 256, h: 256 };
  }, [selectedBed]);

  const luminaMarkImage = useBedImage(LUMINA_BED_MARK_URL);
  const slicerLogoSource = useMemo(
    () => getSlicerLogoSource(slicerSoftware),
    [slicerSoftware],
  );
  const slicerLogoImage = useBedImage(slicerLogoSource);
  const nativeBedGeometry = useNativeBedGeometry(
    deviceProfileId,
    bedDims.w,
    bedDims.h,
  );

  // Find current bed dimensions and its printer-specific visual palette.
  const bedColors = useMemo(() => {
    return resolveBedPlatformColors(
      theme,
      selectedBed?.printer_id,
      bed_label,
      buildPlateId,
    );
  }, [theme, selectedBed?.printer_id, bed_label, buildPlateId]);

  // Create bed geometry + material
  const bedMesh = useMemo(() => {
    const geo = nativeBedGeometry
      ? nativeBedGeometry.clone()
      : createFallbackBedGeometry(bedDims.w, bedDims.h);
    const mat = new THREE.MeshStandardMaterial({
      roughness: 0.68,
      metalness: 0.12,
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "scene-build-plate";
    mesh.userData.bedGeometrySource = nativeBedGeometry
      ? "slicer-native"
      : "dimensional-fallback";
    mesh.position.set(0, 0, -0.1);
    return mesh;
  }, [bedDims, nativeBedGeometry]);

  useLayoutEffect(() => {
    const material = bedMesh.material as THREE.MeshStandardMaterial;
    bedMesh.userData.gridVisible = gridVisible;
    const request = createBedTextureRequest({
      widthMm: bedDims.w,
      heightMm: bedDims.h,
      colors: bedColors,
      gridVisible,
      luminaMarkDataUrl: imageElementToDataUrl(luminaMarkImage),
      slicerLogoDataUrl: imageElementToDataUrl(slicerLogoImage),
      slicerLogoAspectRatio: slicerLogoImage
        ? (slicerLogoImage.naturalWidth || 1) /
          (slicerLogoImage.naturalHeight || 1)
        : 1,
    });
    return stageBedTextureReplacement(
      material,
      request,
      bedColors.bedInner,
    );
  }, [
    bedColors,
    bedDims.h,
    bedDims.w,
    bedMesh,
    gridVisible,
    luminaMarkImage,
    slicerLogoImage,
  ]);

  useEffect(() => {
    return () => {
      disposeMeshResources(bedMesh);
    };
  }, [bedMesh]);

  // Auto-fit camera when bed changes and no model is loaded
  useEffect(() => {
    if (modelUrl || previewGlbUrl || batchPreviewItems.length > 0 || surfaceModelActive) {
      return;
    }

    const perspCam = camera as THREE.PerspectiveCamera;
    const pose = computeBedPreviewCameraPose(
      bedDims.w,
      bedDims.h,
      perspCam.fov,
    );

    camera.position.set(...pose.position);
    camera.lookAt(...pose.target);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(...pose.target);
      oc.maxDistance = pose.fitDistance * 5;
      oc.minDistance = pose.fitDistance * 0.1;
      oc.update();
    }
  }, [bedDims, modelUrl, previewGlbUrl, batchPreviewItems.length, surfaceModelActive, camera, controls]);

  return <primitive object={bedMesh} />;
}
