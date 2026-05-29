# In-App Announcement Maintenance

Use this guide before editing `frontend/src/data/announcements.ts`, changing `useAnnouncement` / `AnnouncementDialog` history semantics, or preparing announcement updates for user-visible changes.

## Source Of Truth

- Source of truth: `frontend/src/data/announcements.ts`; rendered by `AnnouncementDialog` via `useAnnouncement` on first launch
- Announcement copy is the deliberate exception to the regular `frontend/src/i18n/translations.ts` UI-string rule
- Any PR merged to the default branch that introduces a user-visible change (new feature, behavior change, UX fix, notable stability fix) must be reflected in the announcement file in a follow-up commit or PR

## Rendering Contract

- `useAnnouncement` must return the latest daily announcement history entries, capped by `ANNOUNCEMENT_HISTORY_LIMIT`, in descending `version` order
- `AnnouncementDialog` must render every returned entry and must not collapse history to only the newest entry
- The version badge and dismiss key remain bound to the anchor entry (`ANNOUNCEMENTS[0].version`)
- If history semantics change, update the code, tests, and this rule together

## Versioning

- Versioning is by publish date in Beijing time (UTC+8), formatted `YYYY-MM-DD`
- Never use semver, never backdate, and never use a future date
- If the latest entry's `version` equals today's Beijing date, append new `items` to the appropriate existing `sections[].category`
- Otherwise prepend a new `AnnouncementEntry` whose `version` is today's Beijing date

## Localization

- Every user-facing string in `announcements.ts` is bilingual
- `title`, each `sections[].category`, and every item must be a `{ zh, en }` `LocalizedText`
- Both locales are mandatory and must describe the same change
- Keep `title` stable within a release cycle; only bump it when the marketing framing actually changes, and bump both zh and en together

## Categories

Use the canonical category vocabulary and keep order stable:

- zh `新功能` / en `New`
- zh `颜色工作站` / en `Color Workstation`
- zh `提取器（校色卡）` / en `Extractor (Calibration Card)`
- zh `校准 & 材料` / en `Calibration & Materials`
- zh `预览 & 交互` / en `Preview & Interaction`
- zh `矢量化` / en `Vectorisation`
- zh `稳定性` / en `Stability`

Add a new category only when no existing one fits, and introduce both zh and en at once.

## Writing Style

Audience is non-technical end users（普通消费者 / 打印玩家，基本不写代码，不了解本仓库的模块、术语、内部名词）. Every announcement item must read like a product changelog a friend would send, not like an engineering note.

- 一句话讲清楚用户看到什么变化，而不是代码改了什么
- 禁止内部模块名（如 `FileRegistry`、`SessionStore`、`coordinator.py`、`S01` 等）、PR/Issue 号、commit hash、堆栈关键词
- 禁止英文技术黑话（pipeline、hook、store、reducer、mock、stub、schema、endpoint 之类）；前端/后端/接口这种面向用户的词也尽量不用，必要时用"打开软件时""生成 3MF 时"这种使用场景语替换
- 避免缩写，除非是已经出现在 UI 上的缩写（如 LUT、3MF、RGB、CMYK）；首次出现时在后面用括号加一句人话解释
- Chinese 先写，英文自然镜像不是逐字翻译，两边讲的是同一件事但英文也要口语化；不要出现机翻痕迹
- 没有 emoji，没有感叹号堆叠，没有自我营销（"强大""震撼""全新升级"这类词）
- 正例：zh "之前打开颜色工作站有时会突然白屏，现在修好了。" en "Fixed a rare white-screen issue when opening the Color Workstation."
- 反例：zh "修复了 `ColorWorkstation` 组件在 `usePreviewStore` 初始化时 race condition 导致的白屏。"（内部名词 + 黑话 + 讲实现）

## Verification

After editing announcements:

- From `frontend/`, run `pnpm exec tsc --noEmit`
- From the repo root, run `python scripts/run_vitest.py run src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx`

Both commands must stay green.

## Follow-Up PR Workflow

When refreshing announcements after PRs are merged:

- Read the merged PR titles and bodies since the last announcement commit
- Convert each user-visible change into one plain-language bilingual bullet under the right category
- Keep Chinese first and mirror the same meaning naturally in English
- Update `frontend/src/data/announcements.ts` following this guide
- Open a small follow-up PR titled `docs(announcement): refresh YYYY-MM-DD updates`
