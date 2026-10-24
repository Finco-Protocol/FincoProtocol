# Advanced Revenue V4 Candidate — Financial Owner Decision Packet (WF-04A)

Candidate branch: `feat/model-revenue-v4-candidate-v1` (base `93c549e160772acd8258c26556bd46ff9ca29156`).
Every decision below is **OPEN**. None is assumed by the candidate code: the
typed contracts and pure helpers in `app/revenue_v4_candidate/` implement only
the deterministic core each decision would operate on, and the whole package
stays release-closed (`REVENUE_V4_RELEASE_CLOSED`) until a Financial Owner
exact-content decision plus independent review approve a release path.

Reference note: the Harvest V4 observations (including the reference finding
that NPH=5% with no-settlement lowered NPV by $6.2M on one reference model)
are OBSERVATIONS of reference behaviour, not FINCO policy authority.

## D-01 — Negative-price accounting basis (hourly evidence vs declared period share)

Released behaviour: negative prices fail closed at every boundary
(`REVENUE_V2_VALUE`), so negative-priced hours cannot be expressed at all.

Candidate question: when a policy permits negative-priced hours, **how is the
negative-priced energy identified?** The canonical engine settles on
operating periods (e.g. semiannual), not hours. Options:

- (a) Hourly market-price evidence per period (typed hourly series; exact);
  requires an hourly price evidence authority that does not exist yet.
- (b) A declared period-level negative-priced energy share (e.g. NPH = 5% of
  period energy, from an evidence source the owner names); simpler, but
  averages away hour-level structure.

Physical delivery vs commercial settlement (applies to every option): with
**NO_SETTLEMENT** the generator still delivers the MWh (they flow to the
grid; only the negative-priced *settlement* is waived — revenue floor for
that bucket is zero). With **CURTAIL** the MWh are never delivered (physical
output removed; downstream energy balances change). SETTLE_NORMALLY keeps
the negative revenue line. The reference NPV impact of $6.2M was produced by
the no-settlement variant — i.e. by a *commercial* waiver, not by lost
energy.

Also decide: PLANT scope vs SINGLE_STREAM scope semantics for books with
several streams (the candidate forbids mixing a plant-scope and a
stream-scope policy in one book — confirm or specify a precedence rule).

## D-02 — Fixed annual MWh allocation basis

The candidate allocates a fixed annual quantity across post-COD operating
periods pro-rata by DECLARED period hours. Alternatives: equal per period,
equal per month, contractual seasonal split. Owner picks the basis and the
declared-hours source.

## D-03 — Fixed-MWh shortfall / buyback

If delivered energy < contracted fixed MWh (or the reverse), what settles?
Options: cash buyback at market, buyback at contract price, true-up next
period, penalty. The candidate intentionally implements NO shortfall
settlement — it would need its own typed contract plus owner approval.
Until decided, FIXED_ANNUAL_MWH remains a volume-description term only.

## D-04 — Monthly MW shape conventions

Units are pinned (MW × declared month-hours = MWh). Owner decisions:
- Timezone/DST: V1 candidate accepts only an explicitly UTC-declared shape;
  local-time shaping (and DST-short/long days) needs a rule.
- Month-hours source: calendar hours vs netzscheduled hours vs contract
  availability-weighted hours.
- Month→operating-period mapping: the candidate requires exact (year,
  month) membership per period and refuses gaps or double-claimed months.

## D-05 — Negative market prices vs merchant floor/cap/sharing

The released production authorities fail closed on negative prices. In the
candidate: MARKET_FLOOR floors a negative market price to the (non-negative)
floor; MARKET_CAP passes a negative market price through unchanged
(REVENUE_SHARING is unsupported, see D-10). Owner must decide, before any release: (a) may a negative market
price reach settlement at all (this is exactly the D-01 policy), and (b) if
yes, does a floor mode override the NPH policy or yield to it? The candidate
does NOT chain the two mechanisms.

## D-06 — Route-to-market review day

The harvest pins the exact review MONTH only. The candidate counts reviews
at the first day of the review month (no partial months, no interpolation).
Owner decides the contractual review day and whether partial-month fees are
pro-rated (currently they never are).

## D-07 — RTM fee order vs PPA-01 rounding

Released PPA-01 order: indexation → floor/cap → one contractual quantization
→ revenue. Where does the RTM fee (and its escalation) enter? Candidate
default ordering implemented: price resolution → RTM fee → net. Owner decides the authoritative order and whether the fee is
in/out of any contractual rounding.

## D-08 — Fee exceeding gross revenue

The candidate fails closed (`REVENUE_V4_VALUE: … exceeds gross revenue`).
Alternatives: clamp net at zero, carry the excess forward, settle the excess
as a cost line. Owner decides; the candidate will not silently clamp.

## D-09 — Unallocated energy under explicit contracts (cross-reference)

RC-7 recorded this open question (`REVENUE_PPA_V3_RC7.md` §5.1: reject at
Save vs require explicit merchant/curtailment stream vs keep as-is). It
interacts with D-01/D-02: a fixed-MWh contract on a book whose shares do not
cover 100% of production changes the unallocated-energy question. Recorded
here for one combined owner session; no code in this candidate.

## D-10 — Revenue Sharing formula (OPEN; mechanism currently UNSUPPORTED)

An earlier draft of this candidate resolved REVENUE_SHARING as
`market_price × project_share`, i.e. a participation in *market revenue*. The
Harvest V4 reference instead describes a seller share related to the
*difference between the contractual price and the market price*. These are
different financial contracts and the candidate must not present either as
accepted parity. Therefore `REVENUE_SHARING` is recognised but **UNSUPPORTED**:
it fails closed (`REVENUE_V4_UNSUPPORTED`) at rule validation, stream and book
parsing, serialization and price resolution, and produces no number.

Owner must define: the exact sharing formula (which price is the reference,
sign and direction of the difference, whether it applies only above/below the
contract price), the share's basis (price vs revenue vs volume), its interplay
with MARKET_FLOOR/CAP (D-05), and the rounding order (D-07). Only after an
exact-content decision and independent review may a mechanism be introduced.

## Correction D (PR #363) — fail-closed hardening, no policy change

Documented here for the reviewer; none of D-01..D-09 is decided or altered:
- REVENUE_SHARING unsupported (D-10 above); `project_share` is rejected in
  every supported price mode.
- `parse_route_to_market`/`parse_stream_candidate` apply defaults
  (`escalation_rate`=0, `escalation_timing`=NO_ESCALATION, `source_ref`="")
  only when the key is absent; explicit empty strings, booleans or null are
  rejected instead of repaired.
- `parse_candidate` requires the exact `_schema`, `schema_version` (integer
  1) and a recognised `activation` marker; markers are descriptive and can
  never enable the package.
- `resolve_market_mode_price`: missing evidence (`None`) → `None`
  (UNAVAILABLE); malformed evidence (NaN, ±Infinity, booleans, other types)
  → `REVENUE_V4_VALUE`, for every price mode including FIXED. The negative
  bucket price in `apply_negative_price_policy` now rejects booleans like
  every other numeric input.

## Required approvals for ANY release path

1. Financial Owner exact-content decision for the released slice (house
   style: `FINANCIAL_OWNER_*_DECISION_*.md` + exact JSON record + tests-side
   content pin — cf. `docs/model_v11/FINANCIAL_OWNER_RELEASE_DECISION_2026-10-24_V11_STAGE3.md`).
2. Independent review of every byte that would leave this package.
3. A governance successor slice in `tests/test_ci_acceptance.py` (exact
   path + exact blob map) if/when any `domain/`, `finco_core/` or
   `financial_engine/` protected file must change to wire a released policy.
4. Until then the package stays release-closed; product users never see it.
