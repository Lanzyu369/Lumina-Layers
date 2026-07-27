import anycubicSlicerNextLogo from "../assets/slicer-logos/anycubic-slicer-next.png";
import bambuStudioLogo from "../assets/slicer-logos/bambu-studio.svg";
import elegooSlicerLogo from "../assets/slicer-logos/elegoo-slicer.png";
import flashStudioLogo from "../assets/slicer-logos/flash-studio.png";
import orcaSlicerLogo from "../assets/slicer-logos/orca-slicer.svg";
import prusaSlicerLogo from "../assets/slicer-logos/prusa-slicer.svg";
import snapmakerOrcaLogo from "../assets/slicer-logos/snapmaker-orca.png";
import curaLogo from "../assets/slicer-logos/ultimaker-cura.svg";
import {
  getSoftwareIdForDetectedSlicerId,
  normalizeSlicerOptionId,
} from "./settingsOptionIds";

const SLICER_LOGOS: Readonly<Record<string, string>> = {
  BambuStudio: bambuStudioLogo,
  OrcaSlicer: orcaSlicerLogo,
  SnapmakerOrca: snapmakerOrcaLogo,
  ElegooSlicer: elegooSlicerLogo,
  AnycubicSlicerNext: anycubicSlicerNextLogo,
  FlashStudio: flashStudioLogo,
  PrusaSlicer: prusaSlicerLogo,
  Cura: curaLogo,
};

export function resolveSlicerBrandingId(value: string): string {
  return getSoftwareIdForDetectedSlicerId(value) ?? normalizeSlicerOptionId(value);
}

export function getSlicerLogoSource(value: string): string | null {
  return SLICER_LOGOS[resolveSlicerBrandingId(value)] ?? null;
}
