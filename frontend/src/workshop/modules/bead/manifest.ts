import { translations } from "../../../i18n/translations";
import type {
  WorkshopModuleDefinition,
  WorkshopModuleManifest,
} from "../../types";
import { BEAD_MODULE_ID, BEAD_MODULE_VERSION } from "./types";
import { BeadWorkshopModule } from "./BeadWorkshopModule";

export const BEAD_WORKSHOP_MANIFEST: WorkshopModuleManifest = {
  manifestSchemaVersion: 1,
  id: BEAD_MODULE_ID,
  name: translations["workshop.bead.name"],
  description: translations["workshop.bead.description"],
  author: "Lumina Studio",
  version: BEAD_MODULE_VERSION,
  icon: "bead-grid",
  minLuminaVersion: "2.0.0",
  inputKinds: ["image/png", "image/jpeg", "image/webp"],
  outputKinds: ["image/png"],
  capabilities: [
    "file.pick-image",
    "project.read-write",
    "handoff.image",
    "ui.theme",
    "ui.locale",
    "status.progress",
    "status.error",
  ],
};

export const BEAD_WORKSHOP_DEFINITION: WorkshopModuleDefinition = {
  manifest: BEAD_WORKSHOP_MANIFEST,
  Component: BeadWorkshopModule,
};

export const OFFICIAL_WORKSHOP_MODULES = [
  BEAD_WORKSHOP_DEFINITION,
] as const satisfies readonly WorkshopModuleDefinition[];

export const WORKSHOP_MODULE_WHITELIST = new Set<string>([
  BEAD_MODULE_ID,
]);
