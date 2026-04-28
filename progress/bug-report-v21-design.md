# Bug Report v2.1 — Design Document

> **Status**: Design (not implemented). v2.1 of the post-v2 product roadmap.
> **Author**: Cascade (planning).
> **Implementer**: GPT subagent (downstream).
> **Predecessor**: log-governance-v2 (tag `log-governance-v2`).
> **Constraint** (hard): **100% self-built. Zero third-party telemetry SDK** (Sentry / Bugsnag / DataDog / GA / Mixpanel / etc.). Driven by the upcoming crowdfunding cycle, where data sovereignty and "no third-party tracking" are explicit selling points and compliance asks.

---

## 1. Mission & Scope

### 1.1 What v2.1 delivers

A manual user-triggered bug report channel, integrated with the existing structured-logging infrastructure:

1. A globally-visible **Report Bug** button in the app header.
2. A modal dialog that captures user description + optional email + auto-collected runtime context.
3. A new backend endpoint `POST /api/feedback/bug-report` that:
   - emits a single `feedback_bug_report_submitted` INFO canary,
   - writes a structured JSON dump to `<repo>/feedback/<timestamp>_<session_id>.json`,
   - sends an email to the configured developer inbox (graceful degradation if SMTP not configured).
4. A graceful UX: toast confirmation with a short ticket id (first 8 chars of `session_id` or a generated id when no session exists).

### 1.2 What v2.1 does NOT include (deferred to v2.2/v2.3)

| Feature | Phase | Reason |
|---|---|---|
| `window.onerror` + `unhandledrejection` global capture | v2.2 | Manual reports first establish UX baseline; auto-capture risks flooding inbox before signal:noise is calibrated |
| Global `ErrorBoundary` covering whole app (currently only `SceneErrorBoundary` exists) | v2.2 | Same as above; needs careful fallback UX design |
| `devLog` ring buffer + auto-flush of recent client logs into the bug report | v2.2 | Requires `devLog` adoption first; v2.1 ships with empty `recent_client_logs: []` field as a forward-compat seam |
| In-Settings "My bug reports" history view | v2.3 | Pure UX polish; depends on local IndexedDB which we do not yet use |
| Server-side log slice extraction (`audit_logs.py --filter session_id=X` integration) | v2.2 | Best done after the json dump format stabilizes |
| Multi-recipient routing / per-error-class triage | out of scope | Premature; single inbox is fine until reports volume exceeds ~20/day |
| Anonymized analytics aggregation | out of scope | Crowdfunding-pitch position is "no analytics", do not break that |

### 1.3 Why this design

The v2 backend log-governance program already gives every backend action a `session_id`-bound trace in `<repo>/logs/lumina_<timestamp>.log`. v2.1 turns that asset into a user-facing channel: when a user reports a bug, the email contains `session_id`, and the developer can `Select-String -Pattern "<session_id>"` against the log file to reproduce the exact event sequence — without ever sending log data to a third party.

`frontend/src/utils/clientLog.ts` already POSTs frontend timing events to `/api/client-log` (the only `*_log` bucket event whitelisted in `AGENTS.md` L86). v2.2 will reuse that pipe for auto-capture; v2.1 only needs the manual channel.

---

## 2. Architecture

### 2.1 Data flow

```
+---------+   click    +-----------------+  submit  +-----------------------------+
| User in |----------->| BugReportButton |--------->| BugReportModal              |
| browser |            +-----------------+          | (description + optional email)|
+---------+                                         +--------------+--------------+
                                                                   |
                                       collectBugReportContext()   |
                                       (URL, UA, sessionId,        |
                                        color mode, recent logs)   |
                                                                   v
                                                        POST /api/feedback/bug-report
                                                                   |
                                                                   v
                                  +--------------------------------+--------------------------------+
                                  | api/routers/feedback.py: submit_bug_report()                    |
                                  |                                                                 |
                                  |  1. validate (Pydantic, size caps)                              |
                                  |  2. log:  INFO feedback_bug_report_submitted (canary)           |
                                  |  3. dump: <repo>/feedback/<ts>_<session_id>.json (FeedbackStore)|
                                  |  4. enqueue background task -> send_bug_report_email()          |
                                  |  5. return 200 {ticket_id, emailed: bool, dump_path}            |
                                  +-----------------------------------------------------------------+
                                                                   |
                                                                   v
                                            (background) aiosmtplib sends to LUMINA_FEEDBACK_TO
                                            graceful degradation if SMTP env vars missing:
                                            request still 200, emailed=false, log warns once.
```

### 2.2 Trust boundaries

- Browser -> backend: same-origin (Vite proxy in dev, reverse-proxy in prod). No CORS exposure beyond what the rest of the API already has.
- Backend -> SMTP: outbound only. Credentials are read from environment, never written to logs. `password` field of `aiosmtplib` calls must never appear in log records.
- Backend -> filesystem: dump directory is rooted at `LUMINA_FEEDBACK_DUMP_DIR` (default `<repo>/feedback/`). Path traversal must be impossible because filenames are `<utc_iso>_<safe_session_id>.json`, with `safe_session_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)`.

### 2.3 Failure modes (designed)

| Failure | Behavior |
|---|---|
| SMTP env vars unset | 200 with `emailed=false`; one `feedback_smtp_unconfigured` WARNING per process startup, not per request |
| SMTP authentication fails | 200 with `emailed=false`; ERROR `feedback_email_failed` with `error_type` / `error_message` / `dependency=aiosmtplib` |
| SMTP timeout (5s default) | Same as auth fail, `error_type=TimeoutError` |
| Dump directory unwritable | 500 with `feedback_dump_failed` ERROR; user gets toast "Internal error, please retry" |
| Description over 10000 chars | 422 from Pydantic; user sees inline validation message |
| Screenshot data URL > 5 MB | 413 with `feedback_screenshot_too_large` WARNING |
| Concurrent reports from same session | All accepted; each gets a unique `ticket_id` derived from monotonic timestamp |

---

## 3. File Inventory

### 3.1 New files

| File | Layer | Approx LOC | Purpose |
|---|---|---|---|
| `api/routers/feedback.py` | backend router | ~120 | `POST /api/feedback/bug-report` endpoint + Pydantic schemas |
| `api/feedback_email.py` | backend service | ~90 | `send_bug_report_email_async()` with aiosmtplib + env-var resolution + graceful degradation |
| `api/feedback_store.py` | backend service | ~70 | `dump_bug_report()` JSON serialization to disk; path sanitization |
| `frontend/src/api/feedback.ts` | frontend API client | ~50 | `submitBugReport()` axios POST wrapper + TS types |
| `frontend/src/components/BugReportButton.tsx` | frontend UI | ~70 | Header trigger button + i18n + a11y |
| `frontend/src/components/BugReportModal.tsx` | frontend UI | ~250 | Modal dialog with form, validation, submit, toast |
| `frontend/src/utils/bugReportContext.ts` | frontend util | ~120 | `collectBugReportContext()` reads from stores + browser env |
| `tests/test_feedback_router_unit.py` | backend test | ~180 | governance compliance + canary + Pydantic edge cases |
| `tests/test_feedback_email_unit.py` | backend test | ~120 | env-var resolution + graceful degradation + dependency-failure paths |
| `tests/test_feedback_store_unit.py` | backend test | ~80 | path sanitization + dump format |
| `tests/test_feedback_canary_integration_unit.py` | backend integration | ~140 | follows `tests/test_lut_canary_integration_unit.py` pattern |
| `frontend/src/components/__tests__/BugReportButton.test.tsx` | frontend test | ~80 | renders, opens modal, accessible name |
| `frontend/src/components/__tests__/BugReportModal.test.tsx` | frontend test | ~200 | form validation, submit, error states, screenshot capping |
| `frontend/src/api/__tests__/feedback.test.ts` | frontend test | ~80 | axios mock + payload shape |
| `frontend/src/utils/__tests__/bugReportContext.test.ts` | frontend test | ~150 | store reads + env collection + ring-buffer hook (empty for v2.1) |

**Total**: ~1820 LOC (frontend ~1000, backend ~800).

### 3.2 Modified files

| File | Change | LOC delta |
|---|---|---|
| `api/routers/__init__.py` | export `feedback_router` | +2 |
| `api/app.py` | `app.include_router(feedback_router)` in `create_app()` | +1 |
| `api/structured_logging.py` | nothing (existing infrastructure suffices) | 0 |
| `frontend/src/App.tsx` | mount `BugReportButton` in header right cluster (after `ThemeToggle`) and `BugReportModal` at root level | +5 |
| `frontend/src/i18n/translations.ts` | add 11 new keys (see §5.1) | +33 |
| `tests/test_logging_exception_governance_unit.py` | add `FEEDBACK_STRUCTURED_EVENTS = {"feedback_bug_report_submitted"}` to `REQUIRED_STRUCTURED_EVENTS` mapping; add `api/routers/feedback.py` to `TARGETS` | +6 |
| `scripts/log_quality_check.py` | add `feedback_submit` step to `WORKFLOW_ORDER` (ad-hoc, not canonical) + dispatcher branch + `_execute_feedback_submit_workflow()` runner with mocked SMTP | +60 |
| `.env.example` (new file if absent) | document SMTP env vars + dump dir | +14 |
| `requirements.txt` | add `aiosmtplib==3.0.2` | +1 |
| `.gitignore` | add `feedback/` (dump directory) and `.env.local` if absent | +2 |

---

## 4. Frontend Spec

### 4.1 Translation keys

Add to `frontend/src/i18n/translations.ts` immediately after the existing `app_panel_controls` block (alphabetical-ish neighborhood):

```ts
bug_report_button_label: {
  zh: "反馈问题",
  en: "Report a bug",
},
bug_report_button_tooltip: {
  zh: "向开发者发送 bug 反馈",
  en: "Send a bug report to the developer",
},
bug_report_modal_title: {
  zh: "反馈问题",
  en: "Report a bug",
},
bug_report_modal_description_label: {
  zh: "问题描述",
  en: "Describe the problem",
},
bug_report_modal_description_placeholder: {
  zh: "请详细描述发生了什么、你期望发生什么、复现步骤……",
  en: "What happened, what did you expect, and how can we reproduce it?",
},
bug_report_modal_email_label: {
  zh: "你的邮箱（可选，方便我们回复你）",
  en: "Your email (optional, so we can follow up)",
},
bug_report_modal_context_disclosure: {
  zh: "已自动收集的信息（点击展开）",
  en: "Automatically collected info (click to expand)",
},
bug_report_modal_privacy_note: {
  zh: "本反馈仅发送到 Lumina Studio 开发者邮箱，不经过任何第三方服务。",
  en: "This report is sent only to the Lumina Studio developer mailbox. No third-party services are involved.",
},
bug_report_modal_submit: {
  zh: "发送",
  en: "Send",
},
bug_report_modal_cancel: {
  zh: "取消",
  en: "Cancel",
},
bug_report_toast_success: {
  zh: "已收到，谢谢。工单号：{{ticket}}",
  en: "Thanks, we got it. Ticket: {{ticket}}",
},
bug_report_toast_error: {
  zh: "提交失败，请稍后再试。",
  en: "Submission failed, please retry.",
},
bug_report_validation_description_required: {
  zh: "请填写问题描述",
  en: "Please describe the problem",
},
```

> Per `AGENTS.md` L51-52, **all user-visible Chinese must come from this file**. Do not duplicate Chinese literals in `.tsx` files.

### 4.2 API client (`frontend/src/api/feedback.ts`)

```ts
import apiClient from "./client";

export interface BugReportContextPayload {
  url: string;
  user_agent: string;
  screen_width: number;
  screen_height: number;
  device_pixel_ratio: number;
  app_version: string;            // injected at build time via Vite define
  language: "zh" | "en";
  theme: "light" | "dark";
  active_tab: string;
  active_session_ids: {
    converter: string | null;
    single_stage: string | null;
  };
  color_mode: string | null;
  lut_name: string | null;
  recent_client_logs: ReadonlyArray<unknown>;  // empty in v2.1; v2.2 fills via devLog ring buffer
}

export interface BugReportRequestPayload {
  description: string;
  user_email: string | null;
  context: BugReportContextPayload;
  screenshot_data_url: string | null;  // base64 PNG; capped client-side at 5 MiB
}

export interface BugReportResponse {
  ticket_id: string;
  emailed: boolean;
  dump_path: string;  // server-relative
}

export async function submitBugReport(
  payload: BugReportRequestPayload,
): Promise<BugReportResponse> {
  const { data } = await apiClient.post<BugReportResponse>(
    "/feedback/bug-report",
    payload,
  );
  return data;
}
```

> Note: `apiClient` already prefixes `/api`; the path here is `/feedback/bug-report` not `/api/feedback/bug-report`.

### 4.3 Context collector (`frontend/src/utils/bugReportContext.ts`)

Reads from existing zustand stores + browser env. **Must not import any react-hook**, since this runs on submit (synchronous, outside render):

```ts
import { useConverterStore } from "../stores/converter";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";
import type { BugReportContextPayload } from "../api/feedback";

declare const __APP_VERSION__: string;  // Vite define; see vite.config.ts task in §4.7

export function collectBugReportContext(): BugReportContextPayload {
  const converter = useConverterStore.getState();
  const singleStage = useSingleStageStore.getState();
  const settings = useSettingsStore.getState();
  const widget = useWidgetStore.getState();

  return {
    url: typeof window !== "undefined" ? window.location.href : "",
    user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "",
    screen_width: typeof window !== "undefined" ? window.innerWidth : 0,
    screen_height: typeof window !== "undefined" ? window.innerHeight : 0,
    device_pixel_ratio: typeof window !== "undefined" ? window.devicePixelRatio : 1,
    app_version: typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "unknown",
    language: settings.language,
    theme: settings.theme,
    active_tab: widget.activeTab,
    active_session_ids: {
      converter: converter.sessionId ?? null,
      single_stage: singleStage.sessionId ?? null,
    },
    color_mode: settings.lastColorMode || null,
    lut_name: settings.lastLutName || null,
    recent_client_logs: [],  // v2.2 hook: replace with devLog ring buffer drain
  };
}
```

> The `recent_client_logs: []` field is the **forward-compat seam for v2.2**. Tests must assert it is an empty array in v2.1 (frozen), so v2.2 can detect compat regressions.

### 4.4 BugReportButton (`frontend/src/components/BugReportButton.tsx`)

Visual style must match the existing `ThemeToggle` / `LanguageToggle` cluster (rounded, similar size, tooltip via `title`). Lucide icon is `Bug` from `lucide-react` (already a dependency per `AGENTS.md` mention of Lucide).

```tsx
// PSEUDOCODE — implementer: write actual TSX matching existing toggle style
function BugReportButton({ onClick }: { onClick: () => void }) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      data-testid="bug-report-button"
      aria-label={t("bug_report_button_label")}
      title={t("bug_report_button_tooltip")}
      onClick={onClick}
      className="..." // same shape as ThemeToggle
    >
      <BugIcon className="h-4 w-4" />
    </button>
  );
}
```

Accessibility:
- `aria-label` is required.
- Keyboard activation (Enter / Space) must open modal.
- Focus ring must be visible (Tailwind `focus-visible:ring-2`).

### 4.5 BugReportModal (`frontend/src/components/BugReportModal.tsx`)

Layout (refer to existing `AnnouncementDialog` for modal patterns):

- Centered card, max-width 640px, dark/light theme via Tailwind tokens (no raw colors per `AGENTS.md` Frontend Rules).
- Header: title + close (X) button.
- Form fields:
  1. Description textarea (required, 1-10000 chars, autoFocus, 6 rows).
  2. Optional email input (`type="email"`, max 320 chars, browser-native validation).
  3. Optional screenshot capture button (uses `html2canvas`); if added, displays preview thumbnail + "Remove" button. **`html2canvas` already a dependency? -- VERIFY before implementing; if not, defer screenshot to v2.2 and ship v2.1 without screenshot.**
  4. Disclosure (collapsible) showing `JSON.stringify(context, null, 2)` so user can audit what is being sent. Privacy note copy is `bug_report_modal_privacy_note`.
- Footer: Cancel + Send buttons (`Send` disabled until description has at least 1 non-whitespace char).
- Submit flow:
  1. Disable buttons.
  2. Call `submitBugReport(payload)`.
  3. On success, show toast with ticket id (use existing toast system if present; otherwise inline confirmation banner).
  4. On error, show toast with `bug_report_toast_error`. Do not clear the form (so user can retry).
  5. Either way, close modal after toast (success: 1s delay; error: keep open for retry).

Validation:
- Description trimmed length 0 -> show inline `bug_report_validation_description_required`, do not submit.
- Description length > 10000 -> truncate at 10000 with a warning banner.

State management:
- Local component state for form values; **no zustand store**. Modal open/close state lifted into `App.tsx` (single boolean) so the button can toggle it.

### 4.6 App.tsx integration

Diff target: `frontend/src/App.tsx`, the header right cluster (lines 260-283 in current state, between `ThemeToggle` and the connected/checking badge):

```tsx
// existing
<LanguageToggle />
<ThemeToggle />
// ADD:
<BugReportButton onClick={() => setBugReportOpen(true)} />
// existing
{connected === null ? ...}
```

And mount the modal at the end of `AppContent`'s root div, after `AnnouncementDialog`:

```tsx
<BugReportModal
  open={bugReportOpen}
  onClose={() => setBugReportOpen(false)}
/>
```

`bugReportOpen` is a `useState<boolean>(false)` declared near the existing `connected` / `announcementReady` state.

### 4.7 Vite app version injection

`vite.config.ts` must have:

```ts
import { readFileSync } from "node:fs";
const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  // ...rest unchanged
});
```

If `vite.config.ts` already injects a different version constant, reuse that name and skip this step.

---

## 5. Backend Spec

### 5.1 Router (`api/routers/feedback.py`)

```python
"""Feedback router: bug-report intake.

反馈路由：Bug 反馈接收端点。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, EmailStr, Field, constr

from api.feedback_email import send_bug_report_email_async
from api.feedback_store import dump_bug_report
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
log = get_logger(__name__)


# ---- Schemas ----

class BugReportContext(BaseModel):
    url: constr(max_length=2048)
    user_agent: constr(max_length=1024)
    screen_width: int = Field(ge=0, le=100_000)
    screen_height: int = Field(ge=0, le=100_000)
    device_pixel_ratio: float = Field(ge=0.0, le=10.0)
    app_version: constr(max_length=64)
    language: constr(regex=r"^(zh|en)$")
    theme: constr(regex=r"^(light|dark)$")
    active_tab: constr(max_length=64)
    active_session_ids: dict        # {"converter": "...", "single_stage": "..."}
    color_mode: Optional[constr(max_length=64)] = None
    lut_name: Optional[constr(max_length=256)] = None
    recent_client_logs: list = Field(default_factory=list, max_items=100)


class BugReportRequest(BaseModel):
    description: constr(min_length=1, max_length=10_000)
    user_email: Optional[EmailStr] = None
    context: BugReportContext
    screenshot_data_url: Optional[constr(max_length=7_000_000)] = None  # ~5 MiB base64


class BugReportResponse(BaseModel):
    ticket_id: str
    emailed: bool
    dump_path: str


# ---- Endpoint ----

@router.post("/bug-report", response_model=BugReportResponse)
async def submit_bug_report(
    request: BugReportRequest,
    background: BackgroundTasks,
) -> BugReportResponse:
    """Receive a manual user bug report.

    接收用户主动提交的 Bug 反馈。

    Pipeline:
    1. Validate (Pydantic).
    2. Dump JSON to <feedback dir>/<ts>_<safe_session>.json.
    3. Emit single canary INFO `feedback_bug_report_submitted`.
    4. Schedule background email send.
    5. Return ticket id + status.
    """
    try:
        dump_path, ticket_id = dump_bug_report(request.dict())
    except OSError as exc:
        log.error(
            "Bug report dump failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": "<feedback_dump_dir>",
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    background.add_task(
        send_bug_report_email_async,
        ticket_id=ticket_id,
        request_payload=request.dict(),
        dump_path=str(dump_path),
    )

    log.info(
        "Bug report submitted.",
        extra={
            "event": "feedback_bug_report_submitted",
            "ticket_id": ticket_id,
            "session_id_converter": request.context.active_session_ids.get("converter"),
            "session_id_single_stage": request.context.active_session_ids.get("single_stage"),
            "description_length": len(request.description),
            "has_screenshot": request.screenshot_data_url is not None,
            "language": request.context.language,
            "active_tab": request.context.active_tab,
        },
    )

    # `emailed` is the *attempt* status; the actual delivery happens in the
    # background task and may still fail (logged separately as
    # `feedback_email_failed`). The endpoint reports whether email is
    # configured at all.
    from api.feedback_email import is_email_configured
    emailed = is_email_configured()

    return BugReportResponse(
        ticket_id=ticket_id,
        emailed=emailed,
        dump_path=str(dump_path.relative_to(dump_path.anchor.replace("\\", "/"))),
    )
```

> The canary event name is **`feedback_bug_report_submitted`** (specific, two-stage convention not strictly needed for sync request-scoped endpoints per `AGENTS.md` L92, but the name follows the `<family>_<action>_done`-equivalent pattern). Per the AGENTS.md L93 contributor rule, this event must be registered in §6 below.

### 5.2 Email service (`api/feedback_email.py`)

```python
"""SMTP-based bug-report email sender.

基于 SMTP 的 Bug 反馈邮件发送服务。

Environment variables (all optional; missing host disables email):
- LUMINA_FEEDBACK_SMTP_HOST       e.g. smtp.gmail.com
- LUMINA_FEEDBACK_SMTP_PORT       default 587
- LUMINA_FEEDBACK_SMTP_USER       SMTP login
- LUMINA_FEEDBACK_SMTP_PASSWORD   SMTP password / app-password (NEVER logged)
- LUMINA_FEEDBACK_SMTP_FROM       From: header (defaults to SMTP_USER)
- LUMINA_FEEDBACK_TO              recipient inbox (REQUIRED for emailing)
- LUMINA_FEEDBACK_SMTP_USE_TLS    default "true"
- LUMINA_FEEDBACK_SMTP_TIMEOUT_S  default 5
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import aiosmtplib
from email.message import EmailMessage

from api.structured_logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def is_email_configured() -> bool:
    """True iff the minimum SMTP env vars are present.

    最小 SMTP 环境变量是否齐全。

    Cached per-process so missing-config WARNING fires once at most.
    """
    has_host = bool(os.environ.get("LUMINA_FEEDBACK_SMTP_HOST"))
    has_to = bool(os.environ.get("LUMINA_FEEDBACK_TO"))
    if not (has_host and has_to):
        log.warning(
            "Bug-report email is unconfigured; reports will be logged only.",
            extra={
                "event": "feedback_smtp_unconfigured",
                "missing_host": not has_host,
                "missing_to": not has_to,
            },
        )
        return False
    return True


async def send_bug_report_email_async(
    *,
    ticket_id: str,
    request_payload: dict[str, Any],
    dump_path: str,
) -> None:
    """Send the bug report by email (background task).

    在后台任务中通过邮件发送 Bug 报告。
    """
    if not is_email_configured():
        return

    smtp_host = os.environ["LUMINA_FEEDBACK_SMTP_HOST"]
    smtp_port = int(os.environ.get("LUMINA_FEEDBACK_SMTP_PORT", "587"))
    smtp_user = os.environ.get("LUMINA_FEEDBACK_SMTP_USER")
    smtp_password = os.environ.get("LUMINA_FEEDBACK_SMTP_PASSWORD")
    smtp_from = os.environ.get("LUMINA_FEEDBACK_SMTP_FROM", smtp_user or "lumina@localhost")
    smtp_to = os.environ["LUMINA_FEEDBACK_TO"]
    use_tls = os.environ.get("LUMINA_FEEDBACK_SMTP_USE_TLS", "true").lower() == "true"
    timeout_s = float(os.environ.get("LUMINA_FEEDBACK_SMTP_TIMEOUT_S", "5"))

    message = _build_email_message(
        ticket_id=ticket_id,
        request_payload=request_payload,
        dump_path=dump_path,
        smtp_from=smtp_from,
        smtp_to=smtp_to,
    )

    try:
        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=use_tls,
            timeout=timeout_s,
        )
    except (aiosmtplib.SMTPException, TimeoutError, OSError) as exc:
        log.error(
            "Bug-report email failed.",
            extra={
                "event": "feedback_email_failed",
                "ticket_id": ticket_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "dependency": "aiosmtplib",
            },
        )
        # Do NOT re-raise; the request already succeeded from user's POV.


def _build_email_message(
    *,
    ticket_id: str,
    request_payload: dict[str, Any],
    dump_path: str,
    smtp_from: str,
    smtp_to: str,
) -> EmailMessage:
    """Build an EmailMessage with subject + body + json attachment.

    构造 EmailMessage：包含主题、正文、JSON 附件。
    """
    description = request_payload.get("description", "")
    short_desc = description[:50].replace("\n", " ")
    user_email = request_payload.get("user_email") or "(not provided)"
    ctx = request_payload.get("context", {})

    subject = f"[Lumina Bug] {ticket_id} - {short_desc}"
    body_lines = [
        f"Ticket:      {ticket_id}",
        f"User email:  {user_email}",
        f"App version: {ctx.get('app_version')}",
        f"Tab:         {ctx.get('active_tab')}",
        f"Color mode:  {ctx.get('color_mode')}",
        f"LUT:         {ctx.get('lut_name')}",
        f"Sessions:    {ctx.get('active_session_ids')}",
        f"UA:          {ctx.get('user_agent')}",
        f"URL:         {ctx.get('url')}",
        "",
        "Description:",
        description,
        "",
        f"Full payload (json) attached. Dump on disk: {dump_path}",
        "Search the structured log file for these session ids to reproduce.",
    ]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = smtp_to
    msg.set_content("\n".join(body_lines))

    import json
    payload_json = json.dumps(request_payload, ensure_ascii=False, indent=2)
    msg.add_attachment(
        payload_json.encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=f"{ticket_id}.json",
    )
    return msg
```

### 5.3 Storage (`api/feedback_store.py`)

```python
"""Feedback dump store: serializes bug reports to disk.

Bug 反馈持久化：将报告序列化到磁盘。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _resolve_dump_dir() -> Path:
    """Resolve dump directory from env, defaulting to <repo>/feedback.

    解析 dump 目录：优先使用环境变量，否则默认 <repo>/feedback。
    """
    override = os.environ.get("LUMINA_FEEDBACK_DUMP_DIR")
    if override:
        return Path(override).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "feedback"


def dump_bug_report(payload: dict[str, Any]) -> tuple[Path, str]:
    """Write payload to a stable JSON file and return (path, ticket_id).

    将 payload 落盘为 JSON 文件，返回 (路径, 工单号)。

    Filename format: <utc_iso>_<safe_session_id_or_uuid>.json
    The ticket id is the first 8 chars of the session id (preferred) or
    a fresh uuid4 hex.
    """
    dump_dir = _resolve_dump_dir()
    dump_dir.mkdir(parents=True, exist_ok=True)

    ctx = payload.get("context") or {}
    sessions = ctx.get("active_session_ids") or {}
    candidate = sessions.get("converter") or sessions.get("single_stage") or ""
    candidate = _SAFE_RE.sub("_", str(candidate))[:32]
    if not candidate:
        candidate = uuid4().hex[:16]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}_{candidate}.json"
    path = dump_dir / filename

    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(payload_json, encoding="utf-8")

    ticket_id = candidate[:8]
    return path, ticket_id
```

### 5.4 Router registration

In `api/routers/__init__.py`:

```python
from api.routers.feedback import router as feedback_router  # NEW
# ... existing imports ...

__all__ = [
    # ... existing ...
    "feedback_router",  # NEW (alphabetical order preserved)
]
```

In `api/app.py`, after the existing `app.include_router(...)` block (around line 283):

```python
from api.routers import feedback_router  # if not already imported via wildcard
app.include_router(feedback_router)
```

---

## 6. Logging Governance Compliance

This is **mandatory** per `AGENTS.md` L93. The new endpoint must be wired into all three governance surfaces:

### 6.1 `tests/test_logging_exception_governance_unit.py`

Append `api/routers/feedback.py` to `TARGETS`. Add a new whitelist set:

```python
FEEDBACK_STRUCTURED_EVENTS = {
    "feedback_bug_report_submitted",
}
```

And register it:

```python
REQUIRED_STRUCTURED_EVENTS = {
    # ... existing ...
    "api/routers/feedback.py": FEEDBACK_STRUCTURED_EVENTS,
}
```

### 6.2 `scripts/log_quality_check.py`

Add `feedback_submit` to `WORKFLOW_ORDER` (ad-hoc only; **do NOT add to canonical**). Add dispatcher branch in `_run_one_step()` and a new runner:

```python
def _execute_feedback_submit_workflow(verifier: WorkflowVerifier, env: dict[str, str]) -> WorkflowStepResult:
    """Ad-hoc gate for the feedback bug-report endpoint.

    Mocks SMTP via env vars (LUMINA_FEEDBACK_TO unset -> emailed=false path)
    so the runner exercises the canary INFO without sending real email.
    """
    payload = {
        "description": "log_quality_check synthetic report",
        "user_email": None,
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "log-quality-check",
            "screen_width": 1920,
            "screen_height": 1080,
            "device_pixel_ratio": 1.0,
            "app_version": "test",
            "language": "en",
            "theme": "light",
            "active_tab": "converter",
            "active_session_ids": {"converter": None, "single_stage": None},
            "color_mode": None,
            "lut_name": None,
            "recent_client_logs": [],
        },
        "screenshot_data_url": None,
    }
    response = verifier.session.post(
        f"{verifier.base_url}/api/feedback/bug-report",
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return WorkflowStepResult(
        step="feedback_submit",
        status="ok",
        info_lines_collected=verifier.collect_info_lines_since_last(),
        # acceptance: at least one feedback_bug_report_submitted INFO line
    )
```

The runner must **unset** `LUMINA_FEEDBACK_TO` before it spawns the test server, so the email path is skipped (graceful degradation), and the canary is still emitted on the INFO budget. The runner asserts:
- HTTP 200
- response.json contains `ticket_id` and `emailed: false`
- exactly 1 INFO line with `event=feedback_bug_report_submitted`

### 6.3 Per-PR INFO budget

This endpoint is **request-scoped sessionless** and emits exactly **1 INFO line** on the success path. Per `AGENTS.md` L91, the per-endpoint cap is 8 INFO; this is well under. The canonical workflow is FROZEN at 14/30 fast and must remain so — `feedback_submit` is ad-hoc only.

---

## 7. Required Tests

### 7.1 Backend

**`tests/test_feedback_router_unit.py`** (~180 LOC) — covers:

- 200 success path with all-optional fields filled (description + email + screenshot 1 KB).
- 200 success path with description-only (no email, no screenshot).
- 422 when description empty / over 10000 chars.
- 422 when user_email malformed.
- 413 when screenshot exceeds size cap.
- Response body shape (Pydantic).
- Canary INFO presence + discriminator fields (`ticket_id`, `description_length`, `language`).

**`tests/test_feedback_email_unit.py`** (~120 LOC) — covers:

- `is_email_configured()` returns False when host missing, when to missing, when both present.
- `is_email_configured()` only WARNs once per process (lru_cache behaviour).
- `send_bug_report_email_async` short-circuits when not configured (no aiosmtplib call).
- `send_bug_report_email_async` ERROR `feedback_email_failed` on `aiosmtplib.SMTPException`, `TimeoutError`, `OSError` (parametrized).
- `send_bug_report_email_async` does NOT re-raise on failure (background task safety).
- `_build_email_message` produces correct subject prefix, body fields, json attachment.

**`tests/test_feedback_store_unit.py`** (~80 LOC) — covers:

- `dump_bug_report` creates dir if absent.
- Filename uses UTC iso timestamp.
- Path traversal sanitization: session id with `../` / `\` / null bytes is sanitized.
- Returns ticket_id derived from session id (first 8 chars).
- Falls back to uuid4 hex when no session id.
- File contains exact json (idempotency).

**`tests/test_feedback_canary_integration_unit.py`** (~140 LOC) — follows `tests/test_lut_canary_integration_unit.py` pattern:

- Spins up FastAPI test client with monkey-patched env (no SMTP).
- Captures structured logger via `caplog` or a custom handler.
- Asserts exactly 1 INFO with `event=feedback_bug_report_submitted` on success.
- Asserts no canary INFO on 422 / 413 paths.

### 7.2 Frontend

**`frontend/src/api/__tests__/feedback.test.ts`** (~80 LOC):

- `submitBugReport` posts to `/feedback/bug-report` (note: `/api` is auto-prefixed by `apiClient`).
- Payload shape matches `BugReportRequestPayload`.
- Throws on non-2xx.

**`frontend/src/utils/__tests__/bugReportContext.test.ts`** (~150 LOC):

- Reads `sessionId` from converter store and single stage store; both null when no session active.
- Reads language / theme / lastColorMode / lastLutName from settings store.
- Reads activeTab from widget store.
- `recent_client_logs` is `[]` (frozen for v2.1; v2.2 changes this).
- App version comes from `__APP_VERSION__` define.
- Window-less environment fallback (jsdom): all browser fields default to safe values.

**`frontend/src/components/__tests__/BugReportButton.test.tsx`** (~80 LOC):

- Renders with correct aria-label.
- Click invokes `onClick` prop.
- Tooltip shown via `title` attribute.

**`frontend/src/components/__tests__/BugReportModal.test.tsx`** (~200 LOC):

- Submit disabled until description has content.
- Submit calls `submitBugReport` with built payload (mocked).
- Toast appears on success with ticket id.
- Toast on error keeps modal open for retry.
- Empty description shows inline validation message.
- Description over 10000 chars truncated with banner.
- Context disclosure expandable; reveals JSON of context.
- Cancel resets local form state.
- Modal closes on Esc / backdrop click.
- All user-visible text is read from `t(key)` (assert by translation key presence, not literal string).

---

## 8. Acceptance Matrix

GPT subagent must execute **all** of the following and report a green check:

### 8.1 Static checks

- [ ] `cd frontend && npx tsc --noEmit` — passes.
- [ ] `cd frontend && npm run lint` — passes.
- [ ] `python -m mypy api/routers/feedback.py api/feedback_email.py api/feedback_store.py` — passes (or matches baseline mypy strictness if not strict).

### 8.2 Unit & integration tests

- [ ] `python -m pytest tests/test_feedback_router_unit.py tests/test_feedback_email_unit.py tests/test_feedback_store_unit.py tests/test_feedback_canary_integration_unit.py -v` — all green.
- [ ] `python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v` — passes (count grows from 21 to ≥ 22).
- [ ] `cd frontend && npx vitest run src/api/__tests__/feedback.test.ts src/utils/__tests__/bugReportContext.test.ts src/components/__tests__/BugReportButton.test.tsx src/components/__tests__/BugReportModal.test.tsx` — all green.

### 8.3 Quality gates

- [ ] `python scripts/log_quality_check.py --mode fast` — RESULT: PASS, INFO 14/30 (UNCHANGED — must not regress canonical).
- [ ] `python scripts/log_quality_check.py --workflow feedback_submit` — RESULT: PASS, exactly 1 `feedback_bug_report_submitted` INFO captured.

### 8.4 End-to-end smoke

- [ ] Start `python api_server.py` with no SMTP env vars; click Report Bug in dev frontend; submit; verify:
  - 200 response with `emailed: false`.
  - `<repo>/feedback/<ts>_*.json` file exists with full payload.
  - `<repo>/logs/lumina_<ts>.log` has exactly 1 line with `feedback_bug_report_submitted`.
  - Toast shows ticket id.
- [ ] Repeat with `LUMINA_FEEDBACK_TO=test@example.com LUMINA_FEEDBACK_SMTP_HOST=localhost LUMINA_FEEDBACK_SMTP_PORT=11025` and a local `aiosmtpd` debugging server running; verify email arrives at the local SMTP capture.

### 8.5 Crowdfunding-readiness checks

- [ ] No new third-party network endpoint in `package.json` / `requirements.txt` other than `aiosmtplib`.
- [ ] Privacy note copy is present and displayed in modal.
- [ ] No data leaves `apiClient` / `aiosmtplib` paths (grep for `fetch("https?://(?!localhost)`).
- [ ] No tracking pixel / beacon / analytics SDK introduced.

---

## 9. Configuration Documentation

Add to `.env.example` (create if absent):

```bash
# Bug report email (v2.1). All optional; if unset, reports are
# logged + dumped to disk only.
LUMINA_FEEDBACK_SMTP_HOST=        # e.g. smtp.gmail.com
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=
LUMINA_FEEDBACK_SMTP_PASSWORD=    # use app-specific password, never main account password
LUMINA_FEEDBACK_SMTP_FROM=        # defaults to SMTP_USER
LUMINA_FEEDBACK_TO=               # required for emailing; recipient inbox
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5

# Bug report dump directory (default: <repo>/feedback)
LUMINA_FEEDBACK_DUMP_DIR=
```

Update `README.md` "Configuration" section (or create one) with a one-paragraph note pointing to `.env.example`. Include the explicit reminder: **never commit your real SMTP password; use `.env.local`** (which `.gitignore` must already cover; verify and add if not).

---

## 10. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Email auth fails silently in production | M | M | `feedback_email_failed` ERROR logged with `error_type` / `dependency`; ops checklist includes searching for this event |
| Inbox flooded by single user | M | L | Frontend dedupe (debounce by description hash; reject identical submissions within 60s — defer to v2.2 if needed) |
| Screenshot DoS (5 MB × N reports) | L | M | 5 MiB cap server-side via Pydantic; 413 response; consider rate limiting in v2.2 |
| Path traversal via session id | L | H | Sanitize via `_SAFE_RE` regex in `feedback_store.py`; unit-test |
| Secrets accidentally committed | L | H | `.env.local` in `.gitignore`; secret-scanning pre-commit hook (out of v2.1 scope but recommended) |
| Email provider rate limits (Gmail = ~500/day) | L | L | If reports volume exceeds free tier, switch to a transactional provider (Resend free tier 100/day, or self-host postfix). Document in v2.2 |
| user_email field used for spam | L | L | Optional + EmailStr validation; never echo back; document in privacy note |
| HTML injection in email body | L | M | Use plain-text `set_content()` only (no `add_alternative('html')`); verify in `_build_email_message` test |
| Crowdfunding backers audit `package.json` | M | L | The only new dep is `aiosmtplib` (clearly a self-hosted SMTP client); document in PR body |
| Concurrency on dump dir | L | L | `Path.write_text` is atomic on POSIX/Windows for small files; filenames include UTC timestamp + uuid suffix on collision (already designed) |

---

## 11. Forward-Compatibility Hooks for v2.2

These are seams left in v2.1 specifically so v2.2 does NOT require refactoring v2.1:

1. `BugReportContextPayload.recent_client_logs` is an empty array in v2.1; v2.2 will fill it from `devLog` ring buffer. The Pydantic schema already accepts up to 100 items.
2. `bugReportContext.ts` is a plain function (not a hook). v2.2's `window.onerror` handler can call it from a non-React context.
3. `BugReportModal` accepts an optional `presetDescription` prop (NOT yet used in v2.1; document the prop and add a snapshot test that renders with no preset). v2.2's auto-capture will preset description with a stack trace.
4. `submit_bug_report` endpoint's response includes `ticket_id`. v2.3's "my reports" history view can use this to link back to a local store.
5. `feedback_email.py` has no fixed message body schema — v2.2 can extend `_build_email_message` to embed log slice attachment (using `audit_logs.py --filter session_id`) without changing the wire protocol.

---

## 12. Out-of-Scope Confirmation

For absolute clarity to the implementer:

- **No** Sentry / Bugsnag / DataDog / New Relic integration.
- **No** Google Analytics / Plausible / Umami / any analytics tracking.
- **No** uncaught error global handler in v2.1 (that is v2.2).
- **No** screenshot if `html2canvas` is not already a dependency (defer to v2.2).
- **No** structural changes to existing `client_log` event or to `frontend/src/utils/clientLog.ts`.
- **No** changes to canonical workflow in `scripts/log_quality_check.py::WORKFLOW_ORDER`. Only ad-hoc `feedback_submit` is added.
- **No** new color mode, modeling mode, printer profile, or slicer integration.

---

## 13. Hand-off TL;DR for the GPT Subagent

You are implementing Bug Report v2.1 as specified in this document.

**Read first**: `AGENTS.md` (especially Engineering Rules, Logging Governance, Frontend Rules, Encoding & Text Safety, Tests sections) + `docs/logging-guide.md` §6 (debug recipes) + `progress/governance-roadmap.md` (v2 final coverage map).

**Constraints (hard, do not violate)**:

1. 100% self-built, zero third-party telemetry SDK.
2. UTF-8 encoding for all files (especially the new `translations.ts` keys); verify after save with explicit `Get-Content -Encoding UTF8` per `AGENTS.md` Encoding section.
3. All user-visible Chinese must come from `frontend/src/i18n/translations.ts`.
4. Light + dark theme via Tailwind tokens; no raw `#fff` / `bg-white` / `text-black`.
5. Canonical INFO budget 14/30 must NOT regress.
6. Governance trio test count must INCREASE by ≥ 1 (new whitelist entry).
7. Bilingual Google-style docstrings for all new public Python APIs.
8. New worker entry points (none expected here, but if any) must be top-level + picklable.

**Branch**: cut from `dev-refactor` HEAD; branch name `feat/bug-report-v21`.

**Commit cadence**: ≤ 5 commits, conventional-commits style:
- `feat(api): add feedback router for v2.1 bug-report intake`
- `feat(api): add feedback email + storage services`
- `feat(frontend): add bug-report button, modal, and context collector`
- `feat(test): add feedback unit + integration + frontend tests`
- `chore(governance): wire feedback into log governance trio + ad-hoc gate`

**PR**: open against `dev-refactor` with title `feat(feedback): add Bug Report v2.1 (manual user reports + email)`. PR body must include §8 acceptance matrix as a literal checklist.

**Do not**: skip tests, weaken thresholds, add Chinese literals to `.tsx` files, edit canonical workflow, ship without `.env.example` documentation, ship without privacy note copy.

**If anything in this spec is ambiguous**: ask first; do not guess.

---

## 14. Estimated Effort

- Backend: ~600 LOC (router + email + store + tests). 4-6 hours of focused implementation.
- Frontend: ~1000 LOC (component + modal + context + tests). 6-8 hours.
- Governance wiring: ~80 LOC. 1 hour.
- E2E manual verification: 30 minutes.
- PR description / acceptance matrix: 30 minutes.

**Total**: ~12-16 hours of GPT-subagent time at sustained pace; comfortable as a single PR within 1-2 days of wall-clock time.

---

## 15. Future v2.2 / v2.3 Outline (NOT to be implemented now)

- **v2.2** (~1-2 days): `window.onerror` + `unhandledrejection` global handlers wired through `clientLog.ts`; `devLog` ring buffer (50 entries); auto-fill `recent_client_logs`; global `ErrorBoundary` with bug-report fallback; log-slice attachment via `audit_logs.py --filter session_id=<id>`.
- **v2.3** (~1 day): Settings panel "My Bug Reports" history view (IndexedDB); copy-ticket-id button; deep-link from email back to user's local history.

These are tracked as separate design docs to be written when v2.1 ships and 1 week of real user reports has been observed.

---

*End of design document. Last updated: 2026-04-29 by Cascade.*
