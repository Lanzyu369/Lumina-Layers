import { useCallback, useEffect, useState } from "react";
import { getBugReportStatus, resubmitBugReport } from "../api/feedback";
import type {
  BugReportStatusResponse,
  BugReportSubmissionStatus,
} from "../api/feedback";

/** Delay between status polls while the background upload runs. */
export const BUG_REPORT_STATUS_POLL_MS = 1500;
/** Stop polling after about three minutes; the upload keeps running. */
export const BUG_REPORT_STATUS_MAX_POLLS = 120;

export interface BugReportUploadState {
  /** Latest known upload state, or ``null`` before a ticket exists. */
  status: BugReportSubmissionStatus | null;
  /** Full status payload from the most recent poll or retry. */
  details: BugReportStatusResponse | null;
  /** True when polling gave up while the upload was still pending. */
  timedOut: boolean;
  retrying: boolean;
  retryFailed: boolean;
  retry: () => Promise<void>;
}

/**
 * Follow a submitted ticket until the official feedback server accepts it.
 *
 * 跟踪已提交工单，直到官方反馈服务确认收到；失败时提供重试。
 */
export function useBugReportUploadStatus(
  ticketId: string | null,
  initialStatus: BugReportSubmissionStatus | null,
): BugReportUploadState {
  const [details, setDetails] = useState<BugReportStatusResponse | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryFailed, setRetryFailed] = useState(false);
  const [pollGeneration, setPollGeneration] = useState(0);

  useEffect(() => {
    setDetails(null);
    setTimedOut(false);
    setRetrying(false);
    setRetryFailed(false);
  }, [ticketId]);

  const status = details?.submission_status ?? initialStatus;

  useEffect(() => {
    if (!ticketId || status !== "pending") {
      return;
    }
    let cancelled = false;
    let polls = 0;
    let timer: number | undefined;
    const poll = async () => {
      polls += 1;
      try {
        const next = await getBugReportStatus(ticketId);
        if (cancelled) return;
        setDetails(next);
        if (next.submission_status !== "pending") return;
      } catch {
        if (cancelled) return;
      }
      if (polls >= BUG_REPORT_STATUS_MAX_POLLS) {
        setTimedOut(true);
        return;
      }
      timer = window.setTimeout(poll, BUG_REPORT_STATUS_POLL_MS);
    };
    timer = window.setTimeout(poll, BUG_REPORT_STATUS_POLL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
    // pollGeneration restarts polling after a retry leaves the ticket pending.
  }, [ticketId, status, pollGeneration]);

  const retry = useCallback(async () => {
    if (!ticketId) return;
    setRetrying(true);
    setRetryFailed(false);
    try {
      const next = await resubmitBugReport(ticketId);
      setDetails(next);
      setTimedOut(false);
      setPollGeneration((value) => value + 1);
      setRetryFailed(next.submission_status === "failed");
    } catch {
      setRetryFailed(true);
    } finally {
      setRetrying(false);
    }
  }, [ticketId]);

  return { status, details, timedOut, retrying, retryFailed, retry };
}
