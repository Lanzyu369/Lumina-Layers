import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import {
  computePuzzleOverlayPlacement,
  computePuzzleOverlayTextureSize,
  MAX_3D_OVERLAY_TEXTURE_SIZE_PX,
  type PuzzleOverlayBounds,
} from "./puzzleOverlay3DUtils";

export interface PuzzleOverlay3DProps {
  enabled: boolean;
  overlayUrl: string | null;
  modelBounds: PuzzleOverlayBounds | null;
  spacerThick: number;
  enableRelief: boolean;
  colorHeightMap: Record<string, number>;
  enableOutline: boolean;
  enableCloisonne: boolean;
  wireHeightMm: number;
}

/**
 * Render the puzzle overlay as a transparent plane above the preview model.
 * 将拼图叠线作为透明平面渲染在预览模型上方。
 */
export default function PuzzleOverlay3D({
  enabled,
  overlayUrl,
  modelBounds,
  spacerThick,
  enableRelief,
  colorHeightMap,
  enableOutline,
  enableCloisonne,
  wireHeightMm,
}: PuzzleOverlay3DProps) {
  const [texture, setTexture] = useState<THREE.Texture | null>(null);
  const textureRef = useRef<THREE.Texture | null>(null);

  const placement = useMemo(
    () =>
      computePuzzleOverlayPlacement(
        modelBounds,
        spacerThick,
        enableRelief,
        colorHeightMap,
        enableOutline,
        enableCloisonne,
        wireHeightMm,
      ),
    [
      modelBounds,
      spacerThick,
      enableRelief,
      colorHeightMap,
      enableOutline,
      enableCloisonne,
      wireHeightMm,
    ],
  );

  useEffect(() => {
    if (!enabled || !overlayUrl) {
      if (textureRef.current) {
        textureRef.current.dispose();
        textureRef.current = null;
      }
      setTexture(null);
      return;
    }

    let active = true;
    const loader = new THREE.TextureLoader();
    loader.load(
      overlayUrl,
      (loadedTexture) => {
        if (!active) {
          loadedTexture.dispose();
          return;
        }

        const preparedTexture = preparePuzzleOverlayTexture(loadedTexture);

        if (textureRef.current) {
          textureRef.current.dispose();
        }
        textureRef.current = preparedTexture;
        setTexture(preparedTexture);
      },
      undefined,
      () => {
        if (!active) {
          return;
        }
        if (textureRef.current) {
          textureRef.current.dispose();
          textureRef.current = null;
        }
        setTexture(null);
      },
    );

    return () => {
      active = false;
    };
  }, [enabled, overlayUrl]);

  useEffect(() => {
    return () => {
      if (textureRef.current) {
        textureRef.current.dispose();
        textureRef.current = null;
      }
    };
  }, []);

  if (!enabled || !placement || !texture) {
    return null;
  }

  return (
    <mesh
      position={[placement.centerX, placement.centerY, placement.z]}
      renderOrder={980}
    >
      <planeGeometry args={[placement.width, placement.height]} />
      <meshBasicMaterial
        map={texture}
        transparent
        alphaTest={0.05}
        depthTest={false}
        depthWrite={false}
        toneMapped={false}
      />
    </mesh>
  );
}

function preparePuzzleOverlayTexture(texture: THREE.Texture): THREE.Texture {
  const source = texture.image as HTMLImageElement | HTMLCanvasElement | undefined;
  if (!source) {
    applyTextureDefaults(texture);
    return texture;
  }

  const width = source.width;
  const height = source.height;
  if (width <= 0 || height <= 0) {
    applyTextureDefaults(texture);
    return texture;
  }

  const targetSize = computePuzzleOverlayTextureSize(
    width,
    height,
    MAX_3D_OVERLAY_TEXTURE_SIZE_PX,
  );

  if (targetSize.width === width && targetSize.height === height) {
    applyTextureDefaults(texture);
    return texture;
  }

  const croppedCanvas = document.createElement("canvas");
  croppedCanvas.width = targetSize.width;
  croppedCanvas.height = targetSize.height;
  const croppedContext = croppedCanvas.getContext("2d");
  if (!croppedContext) {
    applyTextureDefaults(texture);
    return texture;
  }
  croppedContext.imageSmoothingEnabled = true;
  croppedContext.drawImage(
    source,
    0,
    0,
    width,
    height,
    0,
    0,
    targetSize.width,
    targetSize.height,
  );

  texture.dispose();
  const croppedTexture = new THREE.CanvasTexture(croppedCanvas);
  applyTextureDefaults(croppedTexture);
  return croppedTexture;
}


function applyTextureDefaults(texture: THREE.Texture): void {
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.needsUpdate = true;
}
