# Remembered-port recovery verification / 已记住端口冲突修复验收

Date: 2026-10-10. This is a source candidate, **not a production release**.

## Fixed inputs

- Studio base: `52302b52e78305094e53e3b15baa6cb6aff11b66`.
- Studio implementation: `ef35a9839d2f94815069fbb5caa94c145d1d18f0`.
- Published runtime used for comparison: `2.0.0-beta.20261001131515`, source
  `d9e58b64079b124a7fd875414ad05dfc6e47da99`.
- Launcher message-only candidate: `45a2574bb41b8daa32ea9d4e2a934e95fa6d6ed7`,
  based on `c3c951de950c1dcd812f7d7146b7f367704112e5`.
- Actual Electron: **35.7.5**, Mac arm64 and native Windows x64.

## Defect and behavior change

The published endpoint selector skipped occupied ports on a first launch, but
threw `port_in_use:stable_backend_port:8100` when the same occupied port had
already been saved. A native Windows probe of the published module reproduced
this with another free port; the foreign listener remained alive. The old
launcher additionally described every `startup_port_in_use` as literal 8000.
This establishes a product defect, not the exact port owner on the reporting
customer's computer.

Selection now leaves the saved version-1 origin unchanged, chooses a bounded
replacement, and allows the actual desktop to fall back to an OS-assigned
loopback port. After its own backend health succeeds, main runs ordinary legacy
gap filling, then an authoritative committed-origin transfer, checks backend
survival, commits the new port, and only then opens the usable window. Failed
handover/commit cannot silently select a blank profile. The old source is never
deleted. Returning to a stale origin preserves current revisions and deletions.

Only the handover can replace application settings and the three workshop
database stores; normal legacy import stays non-overwriting. The application
database remains version 2. Temporary HTTP interception serves two exact,
unpredictable inert migration URLs, denies other HTTP requests, and is removed
before opening the application. It does not proxy or execute a foreign service.
Production `webSecurity` remains enabled.

## Verification actually executed

| Scope | Result | Evidence and limits |
| --- | --- | --- |
| Mac Electron Node unit tests | 138 passed, 0 failed, 0 skipped | `node --test electron/__tests__/*.test.cjs`; main wiring fixtures are VM simulations, not actual desktop clicks. |
| Mac real Electron storage recovery | All five separate processes passed | `seed`, `recover`, `restart`, `return`, `empty`, using actual `IndexedDbWorkshopProjectStorage` and isolated userData. |
| Windows native unit tests | 137 passed, 0 failed, 1 skipped | The existing symlink-log-directory test is explicitly skipped on win32; this change did not add or widen the skip. |
| Windows real Electron storage recovery | All five separate processes passed | Ordinary SSH CI account; same actual storage interface and source input as Mac. Not current-login mouse automation. |
| Existing legacy real Electron regression | Mac and Windows passed | Partial import → edit target → retry fills missing project without overwriting edits, DB2 and structured types preserved. Window reopen only; full-process restart is proved by the separate port E2E. |
| Windows packaged main + frozen runtime | Passed to actual `ready` | Disposable copy of the published Windows package, unchanged frozen backend/frontend, three candidate Electron modules and a test-only observer/quit entry. No official package rebuilt. |
| Launcher frontend | 218 passed and build passed | Vitest wrapper with host `NODE_OPTIONS=--no-experimental-webstorage`; pnpm 10.33.2 TypeScript/Vite build. No native launcher rebuilt. |

The five-process E2E verifies Blob, ArrayBuffer, Uint8Array, Date, Map, Set,
BigInt and RegExp, actual project read/edit/save, snapshot restore, setting and
project deletions, authoritative empty data, and a genuine target DB3 import
failure followed by retry from the unchanged source. It fully exits Electron
before restart, rather than only reopening a window. Foreign owners stay alive
and receive zero HTTP requests; temporary interception is absent after success
and failure.

Independent quality review also ran Studio's 138 unit tests successfully. Its
Launcher full run hit one unchanged readiness-wait timing test (217 passed,
1 failed); the failed readiness case and the changed message case then passed
in a focused 2-test rerun. No application code, runner or timeout was altered
to hide this observation. The primary agent's complete Launcher run passed
218 tests.

### Native Windows packaged-main evidence

Job: `studio-port-recovery-20261010-r1`, 2026-10-10 11:50:41–11:51:16 UTC.

Before overlaying, official ASAR bytes for `main.cjs`, `backend-endpoint.cjs`, and
`storage-migration.cjs` were checked equal to the published source baseline.
The isolated synthetic profile's saved port **5442** was deliberately occupied.
Actual candidate main selected **8000**, completed data handover, loaded its own
frontend, showed the main window, and wrote the existing managed `ready`
handshake in about **9 seconds**. Foreign request count was **0** and the owned
test listener was still alive during acceptance. The observer only read the
handshake and approved the test's quit confirmation; it did not fake startup,
health, windows or storage success.

The non-interactive Windows session emitted Chromium OS-crypt/GPU warnings,
but actual readiness and data tests passed. This is not evidence about graphics
or system credential prompts on the customer's interactive desktop.

The controller completed with exit 0, `isAdministrator=false`, and
`remainingJobProcesses=0`. Mac test processes and local helper servers were
closed. No customer profile, activation token, production config or license
database was read or modified.

## Delivery boundaries

The primary fix belongs to the Studio Electron runtime; it must ship in a new
runtime after normal PR review/merge. An existing launcher can launch that new
runtime without a startup-protocol change. The separate launcher candidate only
corrects the misleading failure wording.

No merge, production deployment, catalog edit, official runtime/launcher build,
or release was performed. Current-login Windows mouse operations and the
original reporting customer's follow-up are not claimed. Existing published
packages, baselines and customer state remain untouched.

Reproduction commands and phase contracts are in
[`port-recovery-electron.e2e.md`](../electron/__tests__/port-recovery-electron.e2e.md).
Compact native evidence is retained on the private NAS under
`Lumina win 测试/端口规避排查-20261010/修复候选/`.

## 中文结论

这是程序里确实存在的漏洞：第一次安装会找空闲端口，记住端口后再遇到占用，
反而直接停止启动。修复后会自动换端口；设置、项目及快照迁好，后端正常，
才记住新位置并打开软件。失败会保留原资料供重试，不会清空项目或强关别的软件。

Mac 和 Windows 都完成了真实数据迁移、完全退出后重启及继续保存；Windows
还用原发布包的后端和前端验证了本体实际启动到 ready。故障用户尚未拿到新版
复测，所以不能说他那台电脑已经验收。当前只交源码和 PR，没有修改线上版本。
