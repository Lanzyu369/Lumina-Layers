import { translations } from "../i18n/translations";

export type CompletionNotificationKind =
  | "preview"
  | "generation"
  | "batch"
  | "calibration";

export type BrowserNotificationPermission =
  | NotificationPermission
  | "unsupported"
  | "error";

type CompletionNotificationMessageMap = {
  [Kind in CompletionNotificationKind]: {
    tag: `lumina-completion-${Kind}`;
    titleKey: `completion_notification.${Kind}.title`;
    bodyKey: `completion_notification.${Kind}.body`;
  };
};

type RenotifyNotificationOptions = NotificationOptions & {
  renotify: boolean;
};

const COMPLETION_NOTIFICATION_MESSAGES: CompletionNotificationMessageMap = {
  preview: {
    tag: "lumina-completion-preview",
    titleKey: "completion_notification.preview.title",
    bodyKey: "completion_notification.preview.body",
  },
  generation: {
    tag: "lumina-completion-generation",
    titleKey: "completion_notification.generation.title",
    bodyKey: "completion_notification.generation.body",
  },
  batch: {
    tag: "lumina-completion-batch",
    titleKey: "completion_notification.batch.title",
    bodyKey: "completion_notification.batch.body",
  },
  calibration: {
    tag: "lumina-completion-calibration",
    titleKey: "completion_notification.calibration.title",
    bodyKey: "completion_notification.calibration.body",
  },
};

export function getBrowserNotificationPermission(): BrowserNotificationPermission {
  try {
    if (typeof Notification === "undefined") {
      return "unsupported";
    }
    return Notification.permission;
  } catch {
    return "error";
  }
}

export async function requestBrowserNotificationPermission(): Promise<BrowserNotificationPermission> {
  const currentPermission = getBrowserNotificationPermission();
  if (currentPermission !== "default") {
    return currentPermission;
  }

  try {
    return await Notification.requestPermission();
  } catch {
    return "error";
  }
}

export function showBrowserCompletionNotification(
  kind: CompletionNotificationKind,
  language: "zh" | "en",
): boolean {
  if (getBrowserNotificationPermission() !== "granted") {
    return false;
  }

  const message = COMPLETION_NOTIFICATION_MESSAGES[kind];

  try {
    const title = translations[message.titleKey][language];
    const body = translations[message.bodyKey][language];
    const options: RenotifyNotificationOptions = {
      body,
      tag: message.tag,
      renotify: true,
    };
    new Notification(title, options);
    return true;
  } catch {
    return false;
  }
}
