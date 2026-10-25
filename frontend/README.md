# Frontend D1–D3

Node 22.22.0 (see ../.nvmrc), npm 11.6.2 (npm 10 can fail resolving optional peers; use npm 11).

From frontend/:

- npm ci
- npm run generate:api — regenerate src/api/generated.ts from the G0 OpenAPI
- npm run dev — http://127.0.0.1:5173, /api proxy to localhost:8000
- npm run typecheck
- npm test
- npm run build — same-origin API; output in dist/
- npx playwright install --no-shell chromium
- npm run test:e2e — D1–D3 MSW browser acceptance, NOT real-backend integration

No API keys belong in VITE_* variables.

## Explicit mock mode (PowerShell)

    $env:VITE_ENABLE_MSW = 'true'
    $env:VITE_MSW_SCENARIO = 'python'
    npm run dev

Scenarios: python (synthetic AI success), node (fallback), needs_input,
invalid (422), rate_limited (429), network (connection error),
diagnosis_fallback (AI timeout → local fallback), diagnosis_unknown (questions),
analysis_expired (404 on diagnosis), diagnosis_busy (429), diagnosis_network.
Restart Vite after changing environment variables.
To use the backend, remove VITE_ENABLE_MSW or set it to false.

Analysis mocks return normative examples unchanged, including their target, IDs,
dates and generation mode. They do not adapt the plan to form selections or use_ai.
The visible MSW banner distinguishes this from backend behavior. Payload shape
and selected target are verified separately in tests. Default diagnosis replays
diagnosis_python.json; the extra scenarios explicitly simulate failures/fallback
using the same analysis ID and synthetic data. Diagnosis mock accepts only the
Python example analysis ID. Unknown API paths fail loudly.

MSW starts only when DEV and VITE_ENABLE_MSW=true. The worker is served by a
development-only Vite middleware; production has neither worker nor mock code.
Never use these tests as evidence of live GitHub/AI or D4 integration.
D2/D3 implement the report and diagnosis UI; D4 will test the real backend.

The client never retries POST automatically. Cancel stops waiting, and does
not guarantee cancellation of server processing.

Playwright starts its own Vite server in global setup on port 5179 with
strictPort, and closes it in-process in teardown. It never reuses an existing
server. Chromium channel uses the full Chromium binary (--no-shell install).
This avoids relying on Windows taskkill in restricted sandboxes.

## D2 — report, evidence, commands and export

The report displays repository/commit/target, generation provenance and reason,
coverage/limitations, roots/manifests/dependencies/runtime/managers, findings,
assumptions, prerequisites, ordered commands and verification. `needs_input`
questions appear before commands; no claim is made that commands were executed.

Evidence references open and focus the corresponding excerpt. File/tree/log
sources remain distinct; missing references are visible. Only HTTPS github.com
links without credentials/nonstandard ports are allowed. Fixture evidence stays
local even if an old normative example contains a synthetic external URL.
All repository/model content is React text; no raw HTML or external Markdown renderer.

Commands can be copied, with success/failure feedback. Markdown export uses only
the current AnalysisResponse and matching DiagnosisResponse, never raw form inputs.
It includes provenance/SHA/coverage/facts/findings/plan/sources and the current
received diagnosis; escaping and variable-length code fences protect untrusted
content. Filename is sanitized; Blob object URLs are revoked after download.

## D3 — error log and diagnosis

The form is available after analysis, fixes OS/shell to that report and accepts
up to 30,000 log characters / 2,000 command characters. Whitespace-only input is
rejected. AI opt-out is explicit; input is sent only on submit. Raw inputs live
in React memory, never localStorage/sessionStorage, analytics or console logs.

Diagnosis has independent loading/error/success state, a 60-second timeout and
manual retry. Duplicate submits are blocked. New analysis unmounts the old log
form, cancels waiting and clears diagnosis; ID/sequence guards ignore late
responses, and a diagnosis for another analysis ID is rejected. Expired context
offers explicit reanalysis, without automatic POST or automatic resubmission of log.

Diagnosis uses its own evidence registry, causes/confidence/origin, fixes,
verification, questions, warnings and generation mode/reason. Error banners
explain validation, rate limits, busy server, upstream/network/timeout and 500,
display safe details and Request ID, and offer retry only where appropriate.

## Browser verification on Windows

Chromium is the default. If the downloaded browser cannot start due to Windows
SideBySide configuration, an installed Edge (Chromium engine) can be selected:

```powershell
$env:PLAYWRIGHT_BROWSER_CHANNEL = 'msedge'
npm run test:e2e
```

This changes only the test browser. The application and production build are
unchanged. D2/D3 were checked on Edge/Chromium at desktop and 375px width; the
tests include evidence focus, clipboard, diagnosis, Markdown download, raw-input
exclusion, clearing on new analysis and overflow checks. Screenshots are written
to ignored `test-results/`; these are MSW checks, not D4 or live acceptance.
