# Short prompt — Addendum A (React-only navigation)

Continue on branch `integration/rc-ux-completion-v1` / draft PR #394 (no new PR, no merge, no deploy). Read `docs/react_migration/rc_ux_completion/ADDENDUM_A_REACT_ONLY_NAVIGATION.md` and `handover/HANDOVER.md` §6 first. First merge `origin/main` into the branch (it is conflicted; merge commit, no rebase) and get governance green.

Then deliver Addendum A:
1. Audit every React navigation path (tabs, cards, breadcrumbs, buttons, redirects after Create/Save/Run/Clone, route helpers, generated URLs) and write `NAVIGATION_MAP.md` (old target → React route).
2. Replace the remaining Legacy targets: build a React Trust view (certificate + validation) for the two classic `/v2/workbook/trust/*` links and remove the allow-list in `model_react_rcux_product_acceptance.py`; give Historical statements a React view or an honest "not released" state. No Legacy fallback may close a gap; deferred features get a React-native unavailable screen.
3. Add `tests/model_react_rcux_navigation_acceptance.py` (star-import into the consolidation role and the governance ACCEPTANCE tuple): walk every rendered nav target and reject `staging.finco.one` AND same-host classic routes (`/v2/workbook*`, `/library`, `/projects`, any non-React HTML); cover all main tabs and financing/analysis subtabs, Library→Project→Workspace, New Project→Working Copy, Save→Run→Results, Scenario→Compare→History, Financing→Sponsor→Reporting, deep link + refresh, Back/Forward, unsaved-changes guard, 320/390/768/1440 viewports, three themes, and gated/unavailable screens.
4. Do not add a second router; keep Save≠Run, CAS, CSRF; no engine edits. After any source change: rebuild bundle → `handover/tools/refresh_pins.py` → governance tests.
5. COMMIT → PUSH → update PR #394; fix exact-head CI on the same PR. Report honestly; no "READY FOR INDEPENDENT CHATGPT REVIEW" until the Addendum A gate in §7 of the addendum file holds.
