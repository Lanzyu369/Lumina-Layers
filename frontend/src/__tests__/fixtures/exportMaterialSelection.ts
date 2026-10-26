import type { ExportMaterialSelection } from "../../api/types";

/** Generation tests use a resolved preflight unless material selection is their subject. */
export const READY_EXPORT_MATERIAL_SELECTION: ExportMaterialSelection = {
  ready: true,
  slicer_id: "BambuStudio",
  machine_uid: "fixture-machine",
  nozzle_uid: "fixture-nozzle",
  device_profile_id: "fixture-device",
  machine_profile_id: "fixture-profile",
  build_plate_uid: "fixture-plate",
  materials: [],
  build_plates: [],
  issues: [],
};
