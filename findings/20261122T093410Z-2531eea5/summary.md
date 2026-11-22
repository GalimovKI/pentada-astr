# Mobile mailbox/date layout

On baseline `513efcc`, a local Playwright WebKit 27.2 run with a 390×844 mobile viewport and ru-RU locale measured the mailbox select at 25 px high, while the date input was 44 px. Their top edges differed by 19 px despite the shared min-height rule. The supplied iPhone screenshot also showed the date control extending past the right edge; that overflow itself was not reproduced in desktop WebKit emulation.

`frontend/src/styles/main.css` now gives the context controls an explicit 44 px height and block layout, removes native date appearance, allows the field wrappers to shrink, and uses a single column through 480 px. On wider screens the existing arrangement remains.

Local browser measurements after the CSS fix: Chrome and WebKit, viewport widths 320, 375, 390, 430, 480, 700, 768, 1440; all controls were 44 px tall, no document horizontal overflow. At 390 px both controls were 366 px wide with 12 px left/right margins. The 390 px WebKit screenshot was visually inspected. These are browser-emulation checks with mocked HTTP responses, not a physical-iPhone verification.

The change was subsequently based on dev `5ec1fba`, which did not change this stylesheet. Validation commands from frontend: `npm run build`, `npm test`, `PLAYWRIGHT_CHANNEL=chrome MAIL_UI_PORT=5179 npm run test:browser`. No retrieval/eval logic changed; no quality experiment was run.

A small standalone measurement script is attached. From frontend, run `MAILSEARCH_FRONTEND_DIR="$PWD" node <path-to-record>/check-layout.mjs` with Vite on port 5179; set LAYOUT_BROWSER=chrome to use installed Chrome, otherwise install Playwright WebKit. It prints dimensions and saves a screenshot in /tmp. Original local measurements preceded the final commit; the same CSS is in the referenced published commit.

Final committed tree validation: production build/typecheck passed, 23 Vitest tests passed, all 36 Chrome Playwright desktop/mobile tests passed (22.7 s). Backend tests and real-API tests were not run for this CSS-only change.
