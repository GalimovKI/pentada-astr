# Follow-up correction to mobile form controls

This finding qualifies the earlier record 20261122T093410Z-2531eea5. User screenshots after that fix showed the date value near the top of its box on iPhone, and the search-model select shorter than the adjacent threshold input. The earlier measurements covered the outer mailbox/date controls only and did not establish iOS inner-value alignment.

Baseline: `7ff40ca`. In desktop Playwright WebKit with mobile emulation, the model select was 25 px tall at 390 px viewport while the threshold input was 44 px. At 1440 px, model height was 24 px. The prior fix also set display:block on the date input. WebKit's native stylesheet uses inline-flex with align-items:center for date controls, so that override removed the native vertical alignment: https://github.com/WebKit/WebKit/blob/main/Source/WebCore/css/html.css (date-input rules and ::-webkit-date-and-time-value).

Fix in frontend/src/styles/main.css: explicit 44 px height for input/select globally, and display:flex plus align-items:center on the scenario date. Native pickers and date validation remain in place. The code is published on the task branch and dev at the record's code_commit.

Validation: production build/typecheck passed; 23 Vitest tests and 36 Chrome desktop/mobile Playwright tests passed. Commands from frontend: `npm run build`, `npm test`, `PLAYWRIGHT_CHANNEL=chrome MAIL_UI_PORT=5179 npm run test:browser`. No backend or real-API tests and no retrieval eval were run for the CSS change.

Attached measurements use mocked API responses: Chrome and WebKit at 320, 375, 390, 430, 480, 700, 768, 1440 px. All four controls are now 44 px high; model/threshold top coordinates match within 1 px; document width equals viewport. A 390 px WebKit screenshot was visually inspected. The CSS was tested before committing; no subsequent edits. Physical iPhone verification remains unavailable; desktop mobile emulation does not reproduce the full iOS native date renderer.

The attached script can be run from frontend with `MAILSEARCH_FRONTEND_DIR="$PWD" node <record>/check-layout.mjs` while Vite serves port 5179. Set LAYOUT_BROWSER=chrome to use installed Chrome; otherwise install Playwright WebKit. Width and control measurements are printed, a screenshot is saved under /tmp.
