export type ImageRotationDegrees = 90 | 180 | 270;

const SVG_MIME_TYPE = "image/svg+xml";

const normalizeImageRotationDegrees = (degrees: ImageRotationDegrees): ImageRotationDegrees => {
  if (degrees === 90 || degrees === 180 || degrees === 270) {
    return degrees;
  }
  return 90;
};

export function resolveRotatedImageSize(
  width: number,
  height: number,
  degrees: ImageRotationDegrees,
): { width: number; height: number } {
  const normalized = normalizeImageRotationDegrees(degrees);
  return normalized === 180
    ? { width, height }
    : { width: height, height: width };
}

export function drawRotatedImageToCanvas(
  context: CanvasRenderingContext2D,
  image: CanvasImageSource,
  width: number,
  height: number,
  degrees: ImageRotationDegrees,
): void {
  const normalized = normalizeImageRotationDegrees(degrees);
  if (normalized === 90) {
    context.translate(height, 0);
    context.rotate(Math.PI / 2);
  } else if (normalized === 180) {
    context.translate(width, height);
    context.rotate(Math.PI);
  } else {
    context.translate(0, width);
    context.rotate((3 * Math.PI) / 2);
  }
  context.drawImage(image, 0, 0, width, height);
}

export function isSvgImageFile(file: File | null | undefined): boolean {
  if (!file) {
    return false;
  }
  return file.type === SVG_MIME_TYPE || file.name.toLowerCase().endsWith(".svg");
}

function loadImage(sourceUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Unable to load image for rotation"));
    image.src = sourceUrl;
  });
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("Unable to export rotated image"));
    }, "image/png");
  });
}

function escapeXmlAttribute(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function svgRotationTransform(
  degrees: ImageRotationDegrees,
  width: number,
  height: number,
): string {
  const normalized = normalizeImageRotationDegrees(degrees);
  if (normalized === 90) {
    return `translate(${height} 0) rotate(90)`;
  }
  if (normalized === 180) {
    return `translate(${width} ${height}) rotate(180)`;
  }
  return `translate(0 ${width}) rotate(270)`;
}

function parseSvgViewBox(
  viewBox: string | null,
  fallbackWidth = 100,
  fallbackHeight = 100,
): { minX: number; minY: number; width: number; height: number } {
  const fallback = { minX: 0, minY: 0, width: fallbackWidth, height: fallbackHeight };
  if (!viewBox) {
    return fallback;
  }
  const parts = viewBox
    .trim()
    .split(/[\s,]+/)
    .map((part) => Number.parseFloat(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) {
    return fallback;
  }
  const [minX, minY, width, height] = parts;
  if (width <= 0 || height <= 0) {
    return fallback;
  }
  return { minX, minY, width, height };
}

function getSvgAttribute(root: Element, name: string): string | null {
  const value = root.getAttribute(name);
  return value && value.trim().length > 0 ? value.trim() : null;
}

function parsePositiveSvgLength(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function serializeSvgAttributes(root: Element): string {
  const blocked = new Set(["x", "y", "width", "height", "viewbox", "preserveaspectratio"]);
  const attrs: string[] = [];
  for (const attr of Array.from(root.attributes)) {
    if (blocked.has(attr.name.toLowerCase())) {
      continue;
    }
    attrs.push(`${attr.name}="${escapeXmlAttribute(attr.value)}"`);
  }
  return attrs.join(" ");
}

async function rotateSvgFile(file: File, degrees: ImageRotationDegrees): Promise<File> {
  const source = await file.text();
  const document = new DOMParser().parseFromString(source, SVG_MIME_TYPE);
  const parseError = document.querySelector("parsererror");
  const root = document.documentElement;
  if (parseError || root.tagName.toLowerCase() !== "svg") {
    throw new Error("Invalid SVG for rotation");
  }

  const sourceViewBox = getSvgAttribute(root, "viewBox");
  const fallbackWidth = parsePositiveSvgLength(getSvgAttribute(root, "width")) ?? 100;
  const fallbackHeight = parsePositiveSvgLength(getSvgAttribute(root, "height")) ?? 100;
  const parsedViewBox = parseSvgViewBox(sourceViewBox, fallbackWidth, fallbackHeight);
  const originalViewBox = sourceViewBox ?? `${parsedViewBox.minX} ${parsedViewBox.minY} ${parsedViewBox.width} ${parsedViewBox.height}`;
  const rotatedSize = resolveRotatedImageSize(parsedViewBox.width, parsedViewBox.height, degrees);
  const originalAttributes = serializeSvgAttributes(root);
  const rotatedSource = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${rotatedSize.width} ${rotatedSize.height}">
  <g transform="${escapeXmlAttribute(svgRotationTransform(degrees, parsedViewBox.width, parsedViewBox.height))}">
    <svg ${originalAttributes} x="0" y="0" width="${parsedViewBox.width}" height="${parsedViewBox.height}" viewBox="${escapeXmlAttribute(originalViewBox)}" preserveAspectRatio="none">
      ${root.innerHTML}
    </svg>
  </g>
</svg>
`;
  const baseName = file.name.replace(/\.svg$/i, "") || "image";
  return new File([rotatedSource], `${baseName}_rotated_${degrees}.svg`, {
    type: SVG_MIME_TYPE,
    lastModified: Date.now(),
  });
}

async function rotateRasterImageFile(
  file: File,
  sourceUrl: string,
  degrees: ImageRotationDegrees,
): Promise<File> {
  const image = await loadImage(sourceUrl);
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  if (!width || !height) {
    throw new Error("Invalid image size for rotation");
  }

  const rotatedSize = resolveRotatedImageSize(width, height, degrees);
  const canvas = document.createElement("canvas");
  canvas.width = rotatedSize.width;
  canvas.height = rotatedSize.height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Canvas 2D context is unavailable");
  }
  drawRotatedImageToCanvas(context, image, width, height, degrees);
  const blob = await canvasToBlob(canvas);
  const baseName = file.name.replace(/\.[^.]+$/, "") || "image";
  return new File([blob], `${baseName}_rotated_${degrees}.png`, {
    type: "image/png",
    lastModified: Date.now(),
  });
}

export async function rotateImageFile(
  file: File,
  sourceUrl: string,
  degrees: ImageRotationDegrees,
): Promise<File> {
  if (isSvgImageFile(file)) {
    return rotateSvgFile(file, degrees);
  }
  return rotateRasterImageFile(file, sourceUrl, degrees);
}
