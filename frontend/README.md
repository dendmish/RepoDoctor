# Frontend D1

Node 22.22.0 (see ../.nvmrc), npm 11.6.2 (npm 10 can fail resolving optional peers; use npm 11).

From frontend/:

- npm ci
- npm run generate:api — regenerate src/api/generated.ts from the G0 OpenAPI
- npm run dev — http://127.0.0.1:5173, /api proxy to localhost:8000
- npm run typecheck
- npm test
- npm run build — same-origin API; output in dist/
- npx playwright install --no-shell chromium
- npm run test:e2e — D1 MSW browser smoke only, NOT real-backend integration

No API keys belong in VITE_* variables.

## Explicit mock mode (PowerShell)

    $env:VITE_ENABLE_MSW = 'true'
    $env:VITE_MSW_SCENARIO = 'python'
    npm run dev

Scenarios: python (synthetic AI success), node (fallback), needs_input,
invalid (422), rate_limited (429), network (connection error).
Restart Vite after changing environment variables.
To use the backend, remove VITE_ENABLE_MSW or set it to false.

Mocks return normative examples unchanged, including their target, IDs, dates,
and generation mode. They do not adapt the plan to form selections or use_ai.
The visible MSW banner distinguishes this from backend behavior. Payload shape
and selected target are verified separately in tests. Diagnosis mock accepts
only the ID from diagnosis_python.json. Unknown API paths fail loudly.

MSW starts only when DEV and VITE_ENABLE_MSW=true. The worker is served by a
development-only Vite middleware; production has neither worker nor mock code.
Never use these smoke tests as evidence of live GitHub/AI or D4 integration.
D2 adds the full report, D3 adds diagnosis UI, D4 tests the real backend.

The client never retries POST automatically. Cancel stops waiting, and does
not guarantee cancellation of server processing.

D1 Playwright starts its own Vite server in global setup on port 5179 with
strictPort, and closes it in-process in teardown. It never reuses an existing
server. Chromium channel uses the full Chromium binary (--no-shell install).
This avoids relying on Windows taskkill in restricted sandboxes.
