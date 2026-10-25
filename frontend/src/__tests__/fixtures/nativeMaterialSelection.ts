import type { ExportMaterialSelection } from "../../api/types";

/** A completed preflight for tests concerned with the subsequent export. */
export function readyMaterialSelection(): ExportMaterialSelection {
  return {
    ready: true,
    slicer_id: "BambuStudio",
    machine_uid: "bambu-lab:h2d",
    nozzle_uid: "nozzle:0.4mm",
    device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
    machine_profile_id: "BambuStudio:bbl:bambu-lab-h2d",
    build_plate_uid: "plate:textured-pei",
    materials: [],
    build_plates: [],
    issues: [],
  };
}
