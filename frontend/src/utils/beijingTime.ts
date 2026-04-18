const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function getBeijingNowParts(): {
  year: number;
  month: string;
  day: string;
  hour: string;
  minute: string;
  second: string;
} {
  const beijingNow = new Date(Date.now() + BEIJING_OFFSET_MS);

  return {
    year: beijingNow.getUTCFullYear(),
    month: pad2(beijingNow.getUTCMonth() + 1),
    day: pad2(beijingNow.getUTCDate()),
    hour: pad2(beijingNow.getUTCHours()),
    minute: pad2(beijingNow.getUTCMinutes()),
    second: pad2(beijingNow.getUTCSeconds()),
  };
}

/** 返回当前北京时间（UTC+8）的 ISO 风格字符串，形如 "2026-04-19T10:30:00+08:00"。 */
export function nowBeijingIso(): string {
  const { year, month, day, hour, minute, second } = getBeijingNowParts();
  return `${year}-${month}-${day}T${hour}:${minute}:${second}+08:00`;
}

/** 返回当前北京时间的日期部分，形如 "2026-04-19"。 */
export function todayBeijingDate(): string {
  const { year, month, day } = getBeijingNowParts();
  return `${year}-${month}-${day}`;
}
