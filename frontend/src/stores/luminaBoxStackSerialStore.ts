import { createLuminaBoxSerialStore } from "./luminaBoxSerialStore";

// Keep stack-sample receipts independent from single-material calibration capture.
export const useLuminaBoxStackSerialStore = createLuminaBoxSerialStore(undefined, {
  storageNamespace: "lumina-box-stack-samples",
});
