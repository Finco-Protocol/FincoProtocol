# G-10 — all-in OPEX by year: decision packet

Status: per-line view `SHIPPED`; all-in figure `CONTRACT_BLOCKED_OWNER`.

What the Years view shows (U2b): each saved OPEX line by year, which is the Year 1 amount escalated by that line's own inflation. It also shows
technology-driver rows (read-only), group rows, contingency and totals from the existing projection, and the six group base amounts separately
(Year 1 only, marked "added when the model runs").

Why no all-in number:
* The Run adds the six base scalars. How the Run escalates them (if it does) is engine-owned. A browser or adapter sum would be a second,
  unreviewed OPEX methodology.
* There is no project-wide OPEX escalation input (G-2), so any assumed escalation for the bases would be invented.

Options for the owner:

| Option | Source of the all-in figure | Note |
|---|---|---|
| A | read the Run's OPEX by year from the last Run (immutable, labelled "Last Run") | true numbers, but shows a Run result, not the draft |
| B | an engine-owned preview that folds the bases exactly as the Run does | needs an engine contract |
| C | keep the two parts apart (today) | the user can see what is in and what is out |

Owner question: which option, and is the OPEX aggregation of the bases (escalated or flat) defined anywhere besides the engine?
