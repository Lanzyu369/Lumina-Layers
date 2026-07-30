import type {
  WorkshopPermissionName,
  WorkshopRpcMethod,
} from "../contracts";
import {
  isWorkshopPermissionName,
} from "../contracts";


export const METHOD_PERMISSION = {
  "image.pick": "image.pick",
  "project.save": "project.storage",
  "project.load": "project.storage",
  "project.latest": "project.storage",
  "project.remove": "project.storage",
  "colorLibrary.read": "color-library.read",
  "handoff.image": "handoff.image",
  "ui.getState": null,
  "status.progress": null,
  "status.error": null,
  "status.diagnostics": null,
  "lifecycle.ready": null,
} as const satisfies Record<
  WorkshopRpcMethod,
  WorkshopPermissionName | null
>;

export function normalizeWorkshopPermissions(
  values: ReadonlySet<string>,
): ReadonlySet<WorkshopPermissionName> {
  const permissions = new Set<WorkshopPermissionName>();
  for (const value of values) {
    if (!isWorkshopPermissionName(value)) {
      throw new TypeError(`Unknown Workshop permission: ${value}`);
    }
    permissions.add(value);
  }
  return permissions;
}

export function requiredPermission(
  method: WorkshopRpcMethod,
): WorkshopPermissionName | null {
  return METHOD_PERMISSION[method];
}

export function hasMethodPermission(
  permissions: ReadonlySet<WorkshopPermissionName>,
  method: WorkshopRpcMethod,
): boolean {
  const required = requiredPermission(method);
  return required === null || permissions.has(required);
}
