export type CompletionNotificationKind =
  | "preview"
  | "generation"
  | "batch"
  | "calibration";

export type BrowserNotificationPermission =
  | NotificationPermission
  | "unsupported"
  | "error";

interface CompletionNotificationMessage {
  tag: string;
  zh: {
    title: string;
    body: string;
  };
  en: {
    title: string;
    body: string;
  };
}

const COMPLETION_NOTIFICATION_MESSAGES: Record<
  CompletionNotificationKind,
  CompletionNotificationMessage
> = {
  preview: {
    tag: "lumina-completion-preview",
    zh: {
      title: "预览已完成",
      body: "预览已准备好，可以查看。",
    },
    en: {
      title: "Preview complete",
      body: "Your preview is ready to inspect.",
    },
  },
  generation: {
    tag: "lumina-completion-generation",
    zh: {
      title: "模型生成已完成",
      body: "模型已准备好，可以下载或发送到切片软件。",
    },
    en: {
      title: "Model generation complete",
      body: "Your model is ready to download or send to a slicer.",
    },
  },
  batch: {
    tag: "lumina-completion-batch",
    zh: {
      title: "批量生成已完成",
      body: "批量生成结果已准备好。",
    },
    en: {
      title: "Batch generation complete",
      body: "Your batch results are ready.",
    },
  },
  calibration: {
    tag: "lumina-completion-calibration",
    zh: {
      title: "校准生成已完成",
      body: "校准文件已准备好。",
    },
    en: {
      title: "Calibration generation complete",
      body: "Your calibration files are ready.",
    },
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
  const localizedMessage = message[language];

  try {
    new Notification(localizedMessage.title, {
      body: localizedMessage.body,
      tag: message.tag,
    });
    return true;
  } catch {
    return false;
  }
}
