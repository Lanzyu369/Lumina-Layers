import LuminaBoxMaterialPanel from "./LuminaBoxMaterialPanel";

/** Public Lumina Box material capture entry.
 * Lumina Box 正式耗材采集入口。 */
export default function LuminaBoxWorkspace() {
  return <div className="h-full min-h-0" data-testid="lumina-box-workspace"><LuminaBoxMaterialPanel /></div>;
}
