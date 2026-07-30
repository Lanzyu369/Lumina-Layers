import type {
  WorkshopFileServices,
  WorkshopPickedImage,
  WorkshopRaster,
} from "./types";

const WORKSHOP_IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";
const SUPPORTED_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
]);

export class WorkshopFileError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WorkshopFileError";
    this.code = code;
  }
}

export interface BrowserWorkshopFileAdapters {
  chooseImageFile(accept: string): Promise<File | null>;
  decodeImage(file: Blob): Promise<WorkshopRaster>;
  encodePng(raster: WorkshopRaster, filename: string): Promise<File>;
}

export function isSupportedWorkshopImage(file: File): boolean {
  return SUPPORTED_IMAGE_TYPES.has(file.type.toLowerCase());
}

function chooseImageFile(accept: string): Promise<File | null> {
  return new Promise<File | null>((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.multiple = false;
    input.hidden = true;

    let settled = false;
    const finish = (file: File | null) => {
      if (settled) {
        return;
      }
      settled = true;
      input.remove();
      resolve(file);
    };

    input.addEventListener(
      "change",
      () => finish(input.files?.item(0) ?? null),
      { once: true },
    );
    input.addEventListener("cancel", () => finish(null), { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

function createRasterCanvas(width: number, height: number): {
  canvas: HTMLCanvasElement;
  context: CanvasRenderingContext2D;
} {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    throw new WorkshopFileError(
      "canvas-unavailable",
      "Canvas 2D is unavailable.",
    );
  }
  return { canvas, context };
}

function rasterFromDrawable(
  drawable: CanvasImageSource,
  width: number,
  height: number,
): WorkshopRaster {
  if (
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width <= 0 ||
    height <= 0
  ) {
    throw new WorkshopFileError(
      "invalid-image-dimensions",
      "Image dimensions are invalid.",
    );
  }
  const { context } = createRasterCanvas(width, height);
  context.drawImage(drawable, 0, 0, width, height);
  const imageData = context.getImageData(0, 0, width, height);
  return {
    width,
    height,
    data: new Uint8ClampedArray(imageData.data),
  };
}

async function decodeWithHtmlImage(file: Blob): Promise<WorkshopRaster> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.decoding = "async";
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () =>
        reject(
          new WorkshopFileError(
            "image-decode-failed",
            "The selected image could not be decoded.",
          ),
        );
      image.src = objectUrl;
    });
    return rasterFromDrawable(
      image,
      image.naturalWidth,
      image.naturalHeight,
    );
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function decodeImage(file: Blob): Promise<WorkshopRaster> {
  if (typeof createImageBitmap !== "function") {
    return decodeWithHtmlImage(file);
  }

  try {
    const bitmap = await createImageBitmap(file);
    try {
      return rasterFromDrawable(bitmap, bitmap.width, bitmap.height);
    } finally {
      bitmap.close();
    }
  } catch (error) {
    if (error instanceof WorkshopFileError) {
      throw error;
    }
    return decodeWithHtmlImage(file);
  }
}

function validateRaster(raster: WorkshopRaster): void {
  if (
    !Number.isInteger(raster.width) ||
    !Number.isInteger(raster.height) ||
    raster.width <= 0 ||
    raster.height <= 0 ||
    raster.data.length !== raster.width * raster.height * 4
  ) {
    throw new WorkshopFileError(
      "invalid-raster",
      "Raster dimensions do not match its RGBA data.",
    );
  }
}

async function encodePng(
  raster: WorkshopRaster,
  filename: string,
): Promise<File> {
  validateRaster(raster);
  const { canvas, context } = createRasterCanvas(
    raster.width,
    raster.height,
  );
  context.putImageData(
    new ImageData(
      new Uint8ClampedArray(raster.data),
      raster.width,
      raster.height,
    ),
    0,
    0,
  );
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) {
        resolve(result);
      } else {
        reject(
          new WorkshopFileError(
            "png-encode-failed",
            "The rendered image could not be encoded as PNG.",
          ),
        );
      }
    }, "image/png");
  });
  return new File([blob], filename, { type: "image/png" });
}

const DEFAULT_ADAPTERS: BrowserWorkshopFileAdapters = {
  chooseImageFile,
  decodeImage,
  encodePng,
};

export function createBrowserWorkshopFileServices(
  adapters: BrowserWorkshopFileAdapters = DEFAULT_ADAPTERS,
): WorkshopFileServices {
  return {
    async pickImage(): Promise<WorkshopPickedImage | null> {
      const file = await adapters.chooseImageFile(WORKSHOP_IMAGE_ACCEPT);
      if (!file) {
        return null;
      }
      if (!isSupportedWorkshopImage(file)) {
        throw new WorkshopFileError(
          "unsupported-image-type",
          "Workshop supports PNG, JPEG, and WebP images.",
        );
      }
      return {
        file,
        raster: await adapters.decodeImage(file),
      };
    },
    decodeImage: (file) => adapters.decodeImage(file),
    encodePng: (raster, filename) =>
      adapters.encodePng(raster, filename),
  };
}
