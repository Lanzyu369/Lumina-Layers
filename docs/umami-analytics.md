# Umami Analytics Deployment

Lumina Studio can report lightweight product analytics to an existing central
Umami deployment. Lumina does not deploy or manage Umami itself.

## Recommended topology

Use one Umami website for the Lumina product and distinguish deployments with
`data-tag`.

Example:

| Lumina instance | Umami website id | Tag |
| --- | --- | --- |
| Shanghai production A | same shared id | `prod-shanghai-a` |
| US demo | same shared id | `demo-us` |
| Customer on-prem B | same shared id | `client-b-onprem` |

This keeps one global dashboard while still allowing filters by hostname, tag,
and event name. Create separate Umami websites only when a customer or
environment requires hard data separation.

## Build-time configuration

These variables are read by Vite at frontend build time:

```env
VITE_UMAMI_ENABLED=true
VITE_UMAMI_SCRIPT_URL=https://umami.example.com/script.js
VITE_UMAMI_WEBSITE_ID=00000000-0000-0000-0000-000000000000
VITE_UMAMI_HOST_URL=https://umami.example.com
VITE_UMAMI_TAG=prod-shanghai-a
VITE_UMAMI_DOMAINS=lumina-a.example.com
VITE_UMAMI_DO_NOT_TRACK=true
VITE_UMAMI_EXCLUDE_SEARCH=true
VITE_UMAMI_EXCLUDE_HASH=true
VITE_UMAMI_PERFORMANCE=false
```

If `VITE_UMAMI_ENABLED` is false, or either `SCRIPT_URL` or `WEBSITE_ID` is
empty, analytics stays disabled and all event calls are no-ops.

## Runtime configuration for multi-instance deployments

Use runtime configuration when the same frontend build is deployed to multiple
Lumina instances. Inject this before `/src/main.tsx` in the served HTML, or from
the reverse proxy/template layer that owns per-instance settings:

```html
<script>
  window.__LUMINA_UMAMI_CONFIG__ = {
    enabled: true,
    scriptUrl: "https://umami.example.com/script.js",
    websiteId: "00000000-0000-0000-0000-000000000000",
    hostUrl: "https://umami.example.com",
    tag: "prod-shanghai-a",
    domains: ["lumina-a.example.com"],
    doNotTrack: true,
    excludeSearch: true,
    excludeHash: true,
    performance: false
  };
</script>
```

Runtime values override `VITE_UMAMI_*` values. This is the preferred setup for
distributed deployments because each server can set a different `tag` without
rebuilding frontend assets.

## Event policy

Lumina sends only low-cardinality workflow events:

- `lumina_app_open`
- `lumina_tab_view`
- `lumina_converter_preview_done`
- `lumina_converter_preview_failed`
- `lumina_converter_generate_done`
- `lumina_converter_generate_failed`
- `lumina_batch_convert_done`
- `lumina_batch_convert_failed`
- `lumina_bug_report_done`
- `lumina_bug_report_failed`
- `lumina_tutorial_offered` (first-run welcome shown; once per device)
- `lumina_tutorial_started` (`trigger`: `auto` | `manual`)
- `lumina_tutorial_step_view` (`trigger`, `step_id`, `step_index`,
  `total_steps`; at most one per tour step, only on user navigation)
- `lumina_tutorial_skipped` (`trigger`, `via`: `welcome` | `skip_button` |
  `escape`, `step_id`, `step_index`, `total_steps`, `elapsed_s`)
- `lumina_tutorial_completed` (`trigger`, `total_steps`, `elapsed_s`)

Payloads are sanitized in `frontend/src/analytics/umami.ts`. Fields whose keys
look like file names, paths, URLs, session IDs, tickets, email, descriptions,
tokens, secrets, query strings, hashes, or passwords are dropped before sending.
Do not add high-frequency UI events such as slider drags, panel toggles, hover
inspection, widget movement, or 3D camera movement.

## Network and CSP notes

- Browser clients must be able to load `VITE_UMAMI_SCRIPT_URL`.
- Browser clients must be able to send events to the Umami endpoint. If Umami is
  behind a different hostname, allow it in `script-src` and `connect-src`.
- Keep `VITE_UMAMI_DOMAINS` aligned with the actual public hostnames. Umami will
  ignore traffic from other domains when this is set.
- If a customer network blocks third-party analytics hosts, serve Umami through
  a customer-approved hostname or reverse proxy and point `scriptUrl`/`hostUrl`
  to that hostname.

## 中文说明

Lumina 前端只接入已有的 Umami，不负责部署 Umami。推荐多个 Lumina 实例共用
同一个 Umami website，并用 `tag` 区分实例；这样既能看全局趋势，也能按实例
过滤。异地部署时优先使用运行时配置 `window.__LUMINA_UMAMI_CONFIG__`，避免
为了不同实例重复构建前端。
