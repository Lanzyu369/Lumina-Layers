import { createLuminaBoxSerialStore } from "./luminaBoxSerialStore";

export const useLuminaBoxBackedGradientSerialStore = createLuminaBoxSerialStore(undefined, {
  storageNamespace: "lumina-box-backed-gradient",
});
