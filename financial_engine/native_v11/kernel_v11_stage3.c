/*
 * FINCO V11 Stage 3 candidate kernel — RESEARCH CANDIDATE, DEFAULT OFF, NOT A FINANCIAL AUTHORITY.
 *
 * Separately versioned library (ABI 30001): the approved V10 Stage 1 (`_fk_v10.so`) and Stage 2
 * (`_fk_v10_stage2.so`) artifacts are not modified, resealed or loaded by this kernel.
 *
 * Exact replay, for the admitted configuration only, of the canonical Python senior-debt model
 * evaluation (financial_engine.orchestrator.run_senior_debt_model and
 * _run_senior_debt_model_with_shl):
 *   - Stage 3a: the full annual tax evaluation (financial_engine.tax.engine.calculate_tax with
 *     build_tax_year_bases, calculate_annual_atad / allocate_atad_to_periods, the FIFO
 *     taxable-income-after-loss series, cash-tax payment allocation and the per-period
 *     tax-year allocations) and the lean numeric tax twin used inside the solver iterations;
 *   - Stage 3b: the senior DSCR solver (_solve_dscr, _finalise_authoritative, _solve_combined,
 *     _dscr_sculpting_infeasibility), the financing-tax input merge (_merge_financing_tax_input
 *     interest components), the post-senior cash schedule, the SHL operating chain
 *     (compute_shareholder_loan_schedules operating rows, as the V10 Stage 2 transliteration) and
 *     the complete SHL -> tax -> CFADS -> senior fixed point with its convergence tests.
 *
 * Every iteration of every loop is executed: same iterates, same dependency chain, same
 * termination tests. Nothing is skipped, merged, reordered or approximated.
 *
 * Arithmetic: same IEEE-754 binary64 operations in the same order as the Python reference,
 * built with -O2 -fno-fast-math -ffp-contract=off. CPython >= 3.12 builtin sum()/max()/min()
 * semantics: sum() is Neumaier-compensated starting from int 0, max(a, b) == (b > a ? b : a),
 * min(a, b) == (b < a ? b : a).
 *
 * Safety contract (same as V10-01/V10-04):
 *   - every array crosses the ABI with an explicit length; every index read from an array is
 *     validated against the capacity of the array it addresses before any dereference;
 *   - all integer arithmetic that can grow uses checked builtins and declines when not
 *     representable;
 *   - the kernel never raises a financial exception and has no global mutable state; scratch is
 *     per call. Any status other than FK3_OK means "the canonical Python decides" (it runs and
 *     raises its own exception where the canonical code raises).
 */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define FK3_ABI 30001
#ifndef FK_BUILD_ID
#define FK_BUILD_ID "unset"
#endif

#define FK3_OK 0
#define FK3_DECLINE 1          /* the reference raises or takes another path */
#define FK3_NOT_CONVERGED 2    /* reference result would be non-authoritative -> it raises */
#define FK3_NONFINITE 3
#define FK3_NOMEM 4
#define FK3_INVALID_PLAN 5
#define FK3_ABI_MISMATCH 6
#define FK3_SHL_NOT_CONVERGED 7

#define FK3_MAX_ROWS 100000
#define FK3_MAX_SLOTS 1000000
#define FK3_MAX_YEARS 100000
#define FK3_MAX_OPEN 100000
#define FK3_MAX_ITER 10000000
#define FK3_MAX_SPAN 1000000

#define FK3_MODE_DSCR 1
#define FK3_MODE_COMBINED 2
#define FK3_SHL_BULLET 1
#define FK3_SHL_SWEEP 2

#ifdef FK_TEST_ALLOC
static long fk3_alloc_budget = -1;     /* test-only allocation-failure injection */
void fk3_test_set_alloc_budget(long n) { fk3_alloc_budget = n; }
static void *fk3_malloc(size_t n) {
    if (fk3_alloc_budget == 0) return NULL;
    if (fk3_alloc_budget > 0) fk3_alloc_budget--;
    return malloc(n ? n : 1);
}
#else
static void *fk3_malloc(size_t n) { return malloc(n ? n : 1); }
#endif

int fk3_abi_version(void) { return FK3_ABI; }
const char *fk3_build_id(void) { return FK_BUILD_ID; }

static inline double py_max2(double a, double b) { return (b > a) ? b : a; }
static inline double py_min2(double a, double b) { return (b < a) ? b : a; }

/* builtin sum(list_of_floats), CPython >= 3.12, int start 0. Empty -> int 0 (reported). */
static double py_sum(const double *x, int64_t n, int *is_int) {
    if (n == 0) { *is_int = 1; return 0.0; }
    *is_int = 0;
    double f = 0.0 + x[0];
    double c = 0.0;
    for (int64_t i = 1; i < n; i++) {
        double xi = x[i];
        double t = f + xi;
        if (fabs(f) >= fabs(xi)) c += (f - t) + xi;
        else c += (xi - t) + f;
        f = t;
    }
    if (c != 0.0 && isfinite(c)) f += c;
    return f;
}

double fk3_py_sum(const double *x, int64_t n) {
    int is_int;
    if (n < 0 || (n > 0 && x == NULL)) return NAN;
    return py_sum(x, n, &is_int);
}

static void *arr(int64_t n, size_t elem) {
    size_t bytes;
    if (n < 0 || __builtin_mul_overflow((size_t)n, elem, &bytes)) return NULL;
    return fk3_malloc(bytes);
}

static int in_range(int64_t v, int64_t lo, int64_t hi_excl) { return v >= lo && v < hi_excl; }

/* _field_converged (solver) and _field_converged_local (orchestrator) are the same predicate:
 * diff <= abs_tol, or (rel_tol > 0 and diff / max(|a|, |b|, 1.0) <= rel_tol). */
static inline int field_conv(double a, double b, double abs_tol, double rel_tol) {
    double diff = fabs(a - b);
    if (diff <= abs_tol) return 1;
    if (rel_tol > 0.0) {
        double ref = fabs(a), fb = fabs(b);
        if (fb > ref) ref = fb;
        if (1.0 > ref) ref = 1.0;
        if (diff / ref <= rel_tol) return 1;
    }
    return 0;
}

/* ===================================================================================== tax */

/* One period axis (`periods` order) as the canonical _TaxPlan describes it. */
typedef struct {
    int64_t n_rows, n_years, n_slots, n_sorted, idx_span, idx_min, max_idx;
    const int64_t *row_kind;        /* [n_rows] 0 pass-through, 1 single fragment, 2 multi */
    const int64_t *row_slot_start;  /* [n_rows] */
    const int64_t *row_slot_count;  /* [n_rows] */
    const int64_t *slot_pos;        /* [n_slots] year position */
    const double *slot_frac;        /* [n_slots] fragment allocation fraction */
    const double *y_ebitda;         /* [n_years] */
    const double *y_dep;            /* [n_years] */
    const int64_t *year_key;        /* [n_years] calendar year */
    const int64_t *payment_idx;     /* [n_years] TAX_YEAR_LAST_PERIOD base payment period */
    const int64_t *idx_to_sorted;   /* [idx_span] */
    const int64_t *row_sorted;      /* [n_rows] */
    const int64_t *row_period;      /* [n_rows] period_index */
    const double *row_ebitda;       /* [n_rows] p.ebitda_keur */
} TaxGeom;

typedef struct {
    int64_t atad_enabled; double atad_limit, atad_threshold;
    int64_t loss_gate; double corporate_rate; int64_t lcf_years, lag;
    int64_t n_open; const int64_t *open_last; const double *open_amount;
} TaxPol;

/* Static per-row interest components of the base TaxCalculationInput (merge source). */
typedef struct {
    const int64_t *e_has;     /* [n_rows] base period_interest has this period */
    const double *e_senior, *e_shl, *e_other;
    const double *reint, *fin;   /* adjustment / admitted financing income per row */
    double shl_frac;             /* policy.shl_tax_deductible_fraction() */
} IntCtx;

static int validate_geom(const TaxGeom *G) {
    if (!G) return FK3_INVALID_PLAN;
    if (!in_range(G->n_rows, 1, FK3_MAX_ROWS + 1) || !in_range(G->n_years, 1, FK3_MAX_YEARS + 1) ||
        !in_range(G->n_slots, 1, FK3_MAX_SLOTS + 1) || !in_range(G->n_sorted, 1, FK3_MAX_ROWS + 1) ||
        !in_range(G->idx_span, 1, FK3_MAX_SPAN + 1)) return FK3_INVALID_PLAN;
    const void *p[] = {G->row_kind, G->row_slot_start, G->row_slot_count, G->slot_pos, G->slot_frac,
                       G->y_ebitda, G->y_dep, G->year_key, G->payment_idx, G->idx_to_sorted, G->row_sorted,
                       G->row_period, G->row_ebitda};
    for (size_t i = 0; i < sizeof(p) / sizeof(p[0]); i++) if (!p[i]) return FK3_INVALID_PLAN;
    int64_t total = 0;
    for (int64_t r = 0; r < G->n_rows; r++) {
        int64_t kind = G->row_kind[r], s0 = G->row_slot_start[r], sc = G->row_slot_count[r], end;
        if (!in_range(kind, 0, 3) || s0 < 0 || sc < 1) return FK3_INVALID_PLAN;
        if (kind != 2 && sc != 1) return FK3_INVALID_PLAN;
        if (__builtin_add_overflow(s0, sc, &end) || end > G->n_slots) return FK3_INVALID_PLAN;
        if (s0 != total) return FK3_INVALID_PLAN;          /* slots are row-major and contiguous */
        if (__builtin_add_overflow(total, sc, &total)) return FK3_INVALID_PLAN;
        if (!in_range(G->row_sorted[r], 0, G->n_sorted)) return FK3_INVALID_PLAN;
        /* a period has at most one fragment per calendar year, in ascending year order */
        for (int64_t i = 1; i < sc; i++) if (!(G->slot_pos[s0 + i] > G->slot_pos[s0 + i - 1])) return FK3_INVALID_PLAN;
        if (!isfinite(G->row_ebitda[r])) return FK3_NONFINITE;
    }
    if (total != G->n_slots) return FK3_INVALID_PLAN;
    for (int64_t s = 0; s < G->n_slots; s++) {
        if (!in_range(G->slot_pos[s], 0, G->n_years)) return FK3_INVALID_PLAN;
        if (!isfinite(G->slot_frac[s])) return FK3_NONFINITE;
    }
    for (int64_t o = 0; o < G->idx_span; o++) if (!in_range(G->idx_to_sorted[o], -1, G->n_sorted)) return FK3_INVALID_PLAN;
    int64_t tmp;
    for (int64_t k = 0; k < G->n_years; k++) {
        if (!isfinite(G->y_ebitda[k]) || !isfinite(G->y_dep[k])) return FK3_NONFINITE;
        if (k > 0 && !(G->year_key[k] > G->year_key[k - 1])) return FK3_INVALID_PLAN;
        if (__builtin_sub_overflow(G->payment_idx[k], G->idx_min, &tmp)) return FK3_DECLINE;
    }
    return FK3_OK;
}

static int validate_pol(const TaxPol *T, const TaxGeom *G) {
    if (!T) return FK3_INVALID_PLAN;
    if ((T->atad_enabled != 0 && T->atad_enabled != 1) || (T->loss_gate != 0 && T->loss_gate != 1)) return FK3_INVALID_PLAN;
    if (!in_range(T->n_open, 0, FK3_MAX_OPEN + 1)) return FK3_INVALID_PLAN;
    if (T->n_open > 0 && (!T->open_last || !T->open_amount)) return FK3_INVALID_PLAN;
    if (!isfinite(T->atad_limit) || !isfinite(T->atad_threshold) || !isfinite(T->corporate_rate)) return FK3_NONFINITE;
    for (int64_t i = 0; i < T->n_open; i++) if (!isfinite(T->open_amount[i])) return FK3_NONFINITE;
    int64_t tmp;
    for (int64_t k = 0; k < G->n_years; k++) {
        if (__builtin_add_overflow(G->year_key[k], T->lcf_years, &tmp)) return FK3_DECLINE;
        if (__builtin_add_overflow(G->payment_idx[k], T->lag, &tmp)) return FK3_DECLINE;
        if (__builtin_sub_overflow(tmp, G->idx_min, &tmp)) return FK3_DECLINE;
    }
    return FK3_OK;
}

static int validate_ctx(const IntCtx *X, const TaxGeom *G) {
    if (!X || !X->e_has || !X->e_senior || !X->e_shl || !X->e_other || !X->reint || !X->fin) return FK3_INVALID_PLAN;
    if (!isfinite(X->shl_frac)) return FK3_NONFINITE;
    for (int64_t r = 0; r < G->n_rows; r++) {
        if (X->e_has[r] != 0 && X->e_has[r] != 1) return FK3_INVALID_PLAN;
        if (!isfinite(X->e_senior[r]) || !isfinite(X->e_shl[r]) || !isfinite(X->e_other[r]) ||
            !isfinite(X->reint[r]) || !isfinite(X->fin[r])) return FK3_NONFINITE;
    }
    return FK3_OK;
}

/*
 * _merge_financing_tax_input interest components + _resolve_shl_tax_eligible_interest (no
 * deductible override: limitation disabled and admission requires every base override None):
 *   entry exists iff base has the period, or it is a candidate (senior map) or a SHL-map period;
 *   senior = candidate value | base senior | 0.0;  shl = SHL map | base shl | 0.0;
 *   other  = base other | 0.0;  eligible = shl * fraction;  non_deductible = shl - eligible;
 *   abs((eligible + non_deductible) - shl) > 1e-10 raises ArithmeticError  -> decline;
 *   gross  = senior + other + eligible  (left to right).
 * Rows without an entry carry 0.0 for every component.
 */
static int row_components(const TaxGeom *G, const IntCtx *X, const int64_t *row_cand, const double *cand,
                          const int64_t *s_has, const double *s_val,
                          double *gross, double *nd, double *elig) {
    for (int64_t r = 0; r < G->n_rows; r++) {
        int64_t j = row_cand ? row_cand[r] : -1;
        int has_s = s_has ? (s_has[r] != 0) : 0;
        int has_e = X->e_has[r] != 0;
        if (has_e || has_s || j >= 0) {
            double shl = has_s ? s_val[r] : (has_e ? X->e_shl[r] : 0.0);
            double other = has_e ? X->e_other[r] : 0.0;
            double senior = (j >= 0) ? cand[j] : (has_e ? X->e_senior[r] : 0.0);
            double e = shl * X->shl_frac;
            double n = shl - e;
            if (fabs((e + n) - shl) > 1e-10) return FK3_DECLINE;
            gross[r] = senior + other + e; nd[r] = n; elig[r] = e;
        } else {
            gross[r] = 0.0; nd[r] = 0.0; elig[r] = 0.0;
        }
    }
    return FK3_OK;
}

typedef struct {
    double *frag_i, *frag_r, *frag_n, *frag_f, *ybuf;    /* [n_slots] */
    double *tb, *after, *liab, *cash_sorted;             /* [n_years] / [n_sorted] */
    int *allow;
    int64_t *pool_last, *npool_last; double *pool_amt, *npool_amt; int64_t pool_cap;
    double *gross, *nd, *elig;                           /* [n_rows] */
} TaxScratch;

static void free_tax_scratch(TaxScratch *S) {
    free(S->frag_i); free(S->frag_r); free(S->frag_n); free(S->frag_f); free(S->ybuf);
    free(S->tb); free(S->after); free(S->liab); free(S->cash_sorted); free(S->allow);
    free(S->pool_last); free(S->npool_last); free(S->pool_amt); free(S->npool_amt);
    free(S->gross); free(S->nd); free(S->elig);
    memset(S, 0, sizeof *S);
}

static int alloc_tax_scratch(const TaxGeom *G, const TaxPol *T, TaxScratch *S) {
    memset(S, 0, sizeof *S);
    if (__builtin_add_overflow(T->n_open, G->n_years, &S->pool_cap) ||
        __builtin_add_overflow(S->pool_cap, (int64_t)1, &S->pool_cap)) return FK3_INVALID_PLAN;
    S->frag_i = arr(G->n_slots, sizeof(double)); S->frag_r = arr(G->n_slots, sizeof(double));
    S->frag_n = arr(G->n_slots, sizeof(double)); S->frag_f = arr(G->n_slots, sizeof(double));
    S->ybuf = arr(G->n_slots, sizeof(double));
    S->tb = arr(G->n_years, sizeof(double)); S->after = arr(G->n_years, sizeof(double));
    S->liab = arr(G->n_years, sizeof(double)); S->allow = arr(G->n_years, sizeof(int));
    S->cash_sorted = arr(G->n_sorted, sizeof(double));
    S->pool_last = arr(S->pool_cap, sizeof(int64_t)); S->npool_last = arr(S->pool_cap, sizeof(int64_t));
    S->pool_amt = arr(S->pool_cap, sizeof(double)); S->npool_amt = arr(S->pool_cap, sizeof(double));
    S->gross = arr(G->n_rows, sizeof(double)); S->nd = arr(G->n_rows, sizeof(double));
    S->elig = arr(G->n_rows, sizeof(double));
    if (!S->frag_i || !S->frag_r || !S->frag_n || !S->frag_f || !S->ybuf || !S->tb || !S->after || !S->liab ||
        !S->allow || !S->cash_sorted || !S->pool_last || !S->npool_last || !S->pool_amt || !S->npool_amt ||
        !S->gross || !S->nd || !S->elig) { free_tax_scratch(S); return FK3_NOMEM; }
    return FK3_OK;
}

/* Fragment amounts of one row (tax_year._split_period / the lean twin): multi-fragment rows take
 * amount * fraction with the remainder in the last fragment, single fragments amount - 0.0,
 * zero-length periods pass the amount through unchanged. */
static void split_row(const TaxGeom *G, int64_t r, double amount, double *out) {
    int64_t kind = G->row_kind[r], s0 = G->row_slot_start[r], sc = G->row_slot_count[r];
    if (kind == 2) {
        double acc = 0.0;
        for (int64_t i = 0; i < sc; i++) {
            if (i < sc - 1) { double f = amount * G->slot_frac[s0 + i]; acc += f; out[s0 + i] = f; }
            else out[s0 + i] = amount - acc;
        }
    } else if (kind == 1) out[s0] = amount - 0.0;
    else out[s0] = amount;
}

/* Sum (builtin sum over the fragments of year k, in row order) of a per-slot vector. */
static double year_sum(const TaxGeom *G, const double *slot_vals, int64_t k, double *ybuf, int *is_int) {
    int64_t m = 0;
    for (int64_t s = 0; s < G->n_slots; s++) if (G->slot_pos[s] == k) ybuf[m++] = slot_vals[s];
    return py_sum(ybuf, m, is_int);
}

/* Annual taxable income before LCF (+ the EBT gate), shared by the lean and the full evaluation. */
typedef struct { double y_interest, y_reint, y_nd, y_fin, capacity, deductible, disallowed; int64_t rule; } YearTax;

static int taxable_before(const TaxGeom *G, const TaxPol *T, TaxScratch *S, YearTax *Y) {
    for (int64_t k = 0; k < G->n_years; k++) {
        int i1, i2, i3, i4;
        double y_interest = year_sum(G, S->frag_i, k, S->ybuf, &i1);
        double y_reint = year_sum(G, S->frag_r, k, S->ybuf, &i2);
        double y_nd = year_sum(G, S->frag_n, k, S->ybuf, &i3);
        double y_fin = year_sum(G, S->frag_f, k, S->ybuf, &i4);
        if (i1 || i2 || i3 || i4) return FK3_DECLINE;         /* int sum: another path */
        double ye = G->y_ebitda[k], yd = G->y_dep[k];
        double total = y_interest, capacity, deductible, disallowed;
        int64_t rule;
        if (!T->atad_enabled || total <= 0) {
            capacity = T->atad_enabled ? 0.0 : INFINITY;
            deductible = total; disallowed = 0.0; rule = T->atad_enabled ? 1 : 0;
        } else {
            double ebitda_based = ye * T->atad_limit;
            double threshold = T->atad_threshold;
            if (ebitda_based >= threshold) { capacity = ebitda_based; rule = 2; }
            else { capacity = threshold; rule = 3; }
            deductible = py_min2(total, py_max2(0.0, capacity));
            disallowed = total - deductible;
        }
        S->tb[k] = ye + y_fin - yd - deductible + y_reint;
        if (T->loss_gate) S->allow[k] = (ye + y_fin - yd - y_interest - y_nd + y_reint) > 0.0;
        if (Y) {
            Y[k].y_interest = y_interest; Y[k].y_reint = y_reint; Y[k].y_nd = y_nd; Y[k].y_fin = y_fin;
            Y[k].capacity = capacity; Y[k].deductible = deductible; Y[k].disallowed = disallowed; Y[k].rule = rule;
        }
    }
    return FK3_OK;
}

/* loss_ledger.taxable_income_after_lcf_series (numeric twin of run_annual_fifo_ledger). */
static int lcf_series(const TaxGeom *G, const TaxPol *T, TaxScratch *S) {
    int64_t np = 0;
    for (int64_t i = 0; i < T->n_open; i++) { S->pool_last[np] = T->open_last[i]; S->pool_amt[np] = T->open_amount[i]; np++; }
    for (int64_t k = 0; k < G->n_years; k++) {
        int64_t year = G->year_key[k], w = 0;
        for (int64_t i = 0; i < np; i++)
            if (!(S->pool_last[i] < year)) { S->pool_last[w] = S->pool_last[i]; S->pool_amt[w] = S->pool_amt[i]; w++; }
        np = w;
        double tbk = S->tb[k];
        if (tbk <= 0.0) {
            double generated = (tbk < 0.0) ? -tbk : 0.0;
            if (generated > 1e-12) {
                int64_t last;
                if (np >= S->pool_cap) return FK3_INVALID_PLAN;
                if (__builtin_add_overflow(year, T->lcf_years, &last)) return FK3_DECLINE;
                S->pool_last[np] = last; S->pool_amt[np] = generated; np++;
            }
            S->after[k] = 0.0;
            continue;
        }
        if (T->loss_gate && !S->allow[k]) { S->after[k] = tbk; continue; }
        double remaining = tbk;
        int64_t w2 = 0;
        for (int64_t i = 0; i < np; i++) {
            if (remaining <= 1e-12) { S->npool_last[w2] = S->pool_last[i]; S->npool_amt[w2] = S->pool_amt[i]; w2++; continue; }
            double amt = S->pool_amt[i];
            double consume = py_min2(amt, remaining);
            remaining -= consume;
            double residual = amt - consume;
            if (residual > 1e-12) { S->npool_last[w2] = S->pool_last[i]; S->npool_amt[w2] = residual; w2++; }
        }
        if (w2 > 0) {
            memcpy(S->pool_last, S->npool_last, sizeof(int64_t) * (size_t)w2);
            memcpy(S->pool_amt, S->npool_amt, sizeof(double) * (size_t)w2);
        }
        np = w2;
        S->after[k] = py_max2(0.0, remaining);
    }
    for (int64_t k = 0; k < G->n_years; k++) S->liab[k] = T->corporate_rate * py_max2(0.0, S->after[k]);
    return FK3_OK;
}

/* TAX_YEAR_LAST_PERIOD / MODEL_YEAR_PAYMENT_PERIOD cash allocation (dict KeyError -> decline). */
static int cash_allocation(const TaxGeom *G, const TaxPol *T, TaxScratch *S, double *terminal) {
    for (int64_t s = 0; s < G->n_sorted; s++) S->cash_sorted[s] = 0.0;
    double term = 0.0;
    for (int64_t k = 0; k < G->n_years; k++) {
        int64_t pp, o;
        if (__builtin_add_overflow(G->payment_idx[k], T->lag, &pp)) return FK3_DECLINE;
        if (pp > G->max_idx) { term += S->liab[k]; continue; }
        if (__builtin_sub_overflow(pp, G->idx_min, &o)) return FK3_DECLINE;
        if (o < 0 || o >= G->idx_span) return FK3_DECLINE;
        int64_t sp = G->idx_to_sorted[o];
        if (sp < 0) return FK3_DECLINE;
        S->cash_sorted[sp] = S->cash_sorted[sp] + S->liab[k];
    }
    if (terminal) *terminal = term;
    return FK3_OK;
}

/* Lean evaluation (calculate_cfads_and_cash_tax numeric kernel) from row components. */
static int lean_tax(const TaxGeom *G, const TaxPol *T, const IntCtx *X, TaxScratch *S,
                    const double *gross, const double *nd, double *cfads_row, double *cash_row) {
    for (int64_t r = 0; r < G->n_rows; r++) {
        split_row(G, r, gross[r], S->frag_i); split_row(G, r, X->reint[r], S->frag_r);
        split_row(G, r, nd[r], S->frag_n); split_row(G, r, X->fin[r], S->frag_f);
    }
    int st = taxable_before(G, T, S, NULL);
    if (st) return st;
    st = lcf_series(G, T, S);
    if (st) return st;
    st = cash_allocation(G, T, S, NULL);
    if (st) return st;
    for (int64_t r = 0; r < G->n_rows; r++) {
        double cash = S->cash_sorted[G->row_sorted[r]];
        cfads_row[r] = G->row_ebitda[r] + X->fin[r] - cash;
        cash_row[r] = cash;
    }
    return FK3_OK;
}

/*
 * Stage 3a: full calculate_tax numerics. Outputs (capacities checked by the caller):
 *   per year [n_years]: y_interest, y_reint, y_nd(unused by results), y_fin, capacity, deductible,
 *     disallowed, rule, ti_before, ti_after, liability;
 *   per slot [n_slots] (fragment of a row in a year): period interest (ATAD allocation input),
 *     ATAD period deductible/disallowed, normalised allocation fraction, and the allocation
 *     amounts (ebitda, reintegration, SHL eligible, SHL non-deductible, financing income);
 *   per row [n_rows]: primary tax year, deductible/disallowed totals, taxable-income share,
 *     CIT accrual share, SHL eligible/non-deductible totals, cash tax, CFADS (EBITDA +
 *     financing income - cash tax) and the after-LCF taxable share of the tax-and-CFADS audit;
 *   terminal unpaid tax.
 */
typedef struct {
    double *y_interest, *y_reint, *y_fin, *capacity, *deductible, *disallowed, *ti_before, *ti_after, *liability;
    int64_t *rule, *allow;
    double *s_interest, *s_ded, *s_dis, *s_norm, *s_ebitda, *s_reint, *s_elig, *s_nd, *s_fin;
    int64_t *r_primary_year;
    double *r_ded, *r_dis, *r_ti_share, *r_cit, *r_elig, *r_nd, *r_cash, *r_cfads, *r_ti_after_share;
    double terminal_unpaid;
} FullTaxOut;

static int full_tax(const TaxGeom *G, const TaxPol *T, const IntCtx *X, TaxScratch *S,
                    const double *gross, const double *nd, const double *elig, FullTaxOut *O) {
    int64_t ny = G->n_years, nr = G->n_rows, ns = G->n_slots;
    double *f_e = arr(ns, sizeof(double)), *f_se = arr(ns, sizeof(double));
    YearTax *Y = arr(ny, sizeof(YearTax));
    double *yalloc = arr(ny, sizeof(double)), *ybuf2 = arr(ns, sizeof(double));
    int st = FK3_OK;
    if (!f_e || !f_se || !Y || !yalloc || !ybuf2) { st = FK3_NOMEM; goto done; }
    for (int64_t r = 0; r < nr; r++) {
        split_row(G, r, gross[r], S->frag_i); split_row(G, r, X->reint[r], S->frag_r);
        split_row(G, r, nd[r], S->frag_n); split_row(G, r, X->fin[r], S->frag_f);
        split_row(G, r, G->row_ebitda[r], f_e); split_row(G, r, elig[r], f_se);
    }
    st = taxable_before(G, T, S, Y);
    if (st) goto done;
    st = lcf_series(G, T, S);
    if (st) goto done;
    st = cash_allocation(G, T, S, &O->terminal_unpaid);
    if (st) goto done;
    for (int64_t k = 0; k < ny; k++) {
        O->y_interest[k] = Y[k].y_interest; O->y_reint[k] = Y[k].y_reint; O->y_fin[k] = Y[k].y_fin;
        O->capacity[k] = Y[k].capacity; O->deductible[k] = Y[k].deductible; O->disallowed[k] = Y[k].disallowed;
        O->rule[k] = Y[k].rule; O->allow[k] = T->loss_gate ? S->allow[k] : 1; O->ti_before[k] = S->tb[k]; O->ti_after[k] = S->after[k]; O->liability[k] = S->liab[k];
    }
    /* per slot: fragment amounts summed per (period, year) = sum([x]) = 0.0 + x */
    for (int64_t s = 0; s < ns; s++) {
        O->s_interest[s] = 0.0 + S->frag_i[s];          /* period_int.get(idx, 0.0) + frag.total_interest */
        O->s_ebitda[s] = 0.0 + f_e[s]; O->s_reint[s] = 0.0 + S->frag_r[s];
        O->s_elig[s] = 0.0 + f_se[s]; O->s_nd[s] = 0.0 + S->frag_n[s]; O->s_fin[s] = 0.0 + S->frag_f[s];
    }
    /* ATAD period allocation (allocate_atad_to_periods), chronological per year */
    for (int64_t k = 0; k < ny; k++) {
        double cap = Y[k].capacity;
        if (cap == INFINITY) {
            for (int64_t s = 0; s < ns; s++) if (G->slot_pos[s] == k) { O->s_ded[s] = O->s_interest[s]; O->s_dis[s] = 0.0; }
        } else {
            double remaining = cap;
            for (int64_t s = 0; s < ns; s++) {
                if (G->slot_pos[s] != k) continue;
                double interest = O->s_interest[s];
                double ded = py_min2(interest, py_max2(0.0, remaining));
                O->s_ded[s] = ded; O->s_dis[s] = interest - ded;
                remaining -= ded;
            }
        }
    }
    /* normalised allocation fractions: raw = sum([frac]); year sum over the year's periods; denom or 1.0 */
    for (int64_t k = 0; k < ny; k++) {
        int64_t m = 0;
        for (int64_t s = 0; s < ns; s++) if (G->slot_pos[s] == k) ybuf2[m++] = 0.0 + G->slot_frac[s];
        int is_int;
        double ys = py_sum(ybuf2, m, &is_int);
        if (is_int) { st = FK3_DECLINE; goto done; }      /* a tax year without periods */
        yalloc[k] = (ys == 0.0) ? 1.0 : ys;
    }
    for (int64_t s = 0; s < ns; s++) O->s_norm[s] = (0.0 + G->slot_frac[s]) / yalloc[G->slot_pos[s]];
    /* per period */
    for (int64_t r = 0; r < nr; r++) {
        int64_t s0 = G->row_slot_start[r], sc = G->row_slot_count[r];
        double ded = 0.0, dis = 0.0;
        double ti[64], cit[64], el[64], nn[64], ta[64];
        double *ti_p = ti, *cit_p = cit, *el_p = el, *nn_p = nn, *ta_p = ta;
        double *heap = NULL;
        if (sc > 64) {
            heap = arr(5 * sc, sizeof(double));
            if (!heap) { st = FK3_NOMEM; goto done; }
            ti_p = heap; cit_p = heap + sc; el_p = heap + 2 * sc; nn_p = heap + 3 * sc; ta_p = heap + 4 * sc;
        }
        int64_t best = -1; double best_frac = 0.0; int64_t best_year = 0;
        for (int64_t i = 0; i < sc; i++) {
            int64_t s = s0 + i, k = G->slot_pos[s];
            ded = ded + O->s_ded[s]; dis = dis + O->s_dis[s];
            double nf = O->s_norm[s];
            ti_p[i] = S->tb[k] * nf; cit_p[i] = S->liab[k] * nf;
            el_p[i] = O->s_elig[s]; nn_p[i] = O->s_nd[s];
            ta_p[i] = S->after[k] * nf;
            int64_t yk = G->year_key[k];
            if (best < 0 || nf > best_frac || (nf == best_frac && yk > best_year)) { best = i; best_frac = nf; best_year = yk; }
        }
        int a1, a2, a3, a4, a5;
        O->r_ti_share[r] = py_sum(ti_p, sc, &a1); O->r_cit[r] = py_sum(cit_p, sc, &a2);
        O->r_elig[r] = py_sum(el_p, sc, &a3); O->r_nd[r] = py_sum(nn_p, sc, &a4);
        O->r_ti_after_share[r] = py_sum(ta_p, sc, &a5);
        free(heap);
        if (a1 || a2 || a3 || a4 || a5) { st = FK3_DECLINE; goto done; }
        O->r_ded[r] = ded; O->r_dis[r] = dis;
        O->r_primary_year[r] = best_year;
        double cash = S->cash_sorted[G->row_sorted[r]];
        O->r_cash[r] = cash;
        O->r_cfads[r] = G->row_ebitda[r] + X->fin[r] - cash;
    }
done:
    free(f_e); free(f_se); free(Y); free(yalloc); free(ybuf2);
    return st;
}

/* ================================================================================ solver */

typedef struct {
    int64_t n_d;
    const double *rates, *dfs, *dscr, *avail;   /* [n_d] (dscr/avail read only in repayment) */
    const int64_t *in_rep;                       /* [n_d] */
    const int64_t *d_row;                        /* [n_d] row of each debt period on the bank axis */
    const int64_t *row_cand;                     /* [n_rows bank] debt position or -1 */
    double alpha, abs_tol, rel_tol, d0, gearing_cap;
    int64_t max_iter, max_fin_iter, mode, permit_balloon;
} DebtGeom;

static int validate_debt(const DebtGeom *D, const TaxGeom *G) {
    if (!D || !in_range(D->n_d, 1, FK3_MAX_ROWS + 1) || !in_range(D->max_iter, 0, FK3_MAX_ITER + 1) ||
        !in_range(D->max_fin_iter, 0, FK3_MAX_ITER + 1)) return FK3_INVALID_PLAN;
    if (!D->rates || !D->dfs || !D->dscr || !D->avail || !D->in_rep || !D->d_row || !D->row_cand) return FK3_INVALID_PLAN;
    if (D->mode != FK3_MODE_DSCR && D->mode != FK3_MODE_COMBINED) return FK3_INVALID_PLAN;
    if (D->permit_balloon != 0 && D->permit_balloon != 1) return FK3_INVALID_PLAN;
    for (int64_t r = 0; r < G->n_rows; r++) if (!in_range(D->row_cand[r], -1, D->n_d)) return FK3_INVALID_PLAN;
    for (int64_t j = 0; j < D->n_d; j++) {
        int64_t r = D->d_row[j];
        if (!in_range(r, 0, G->n_rows) || D->row_cand[r] != j) return FK3_INVALID_PLAN;
        if (D->in_rep[j] != 0 && D->in_rep[j] != 1) return FK3_INVALID_PLAN;
        if (!isfinite(D->rates[j]) || !isfinite(D->dfs[j])) return FK3_NONFINITE;
        if (D->in_rep[j] && (!isfinite(D->dscr[j]) || !isfinite(D->avail[j]))) return FK3_NONFINITE;
    }
    int64_t ncand = 0;
    for (int64_t r = 0; r < G->n_rows; r++) if (D->row_cand[r] >= 0) ncand++;
    if (ncand != D->n_d) return FK3_INVALID_PLAN;
    if (!isfinite(D->alpha) || !isfinite(D->abs_tol) || !isfinite(D->rel_tol) || !isfinite(D->d0) ||
        !isfinite(D->gearing_cap)) return FK3_NONFINITE;
    return FK3_OK;
}

/* _forward_roll_numeric / _forward_roll (dscr_sculpted, scale 1.0) */
static void roll(const DebtGeom *D, double opening, const double *cf_d, double *op, double *in, double *pr, double *cl) {
    double balance = opening;
    for (int64_t i = 0; i < D->n_d; i++) {
        double interest = balance * D->rates[i] * D->dfs[i];
        double principal;
        if (D->in_rep[i]) {
            double cfads = cf_d[i], target = D->dscr[i], ds;
            if (target > 0) ds = py_max2(0.0, cfads / target) * D->avail[i];
            else ds = 0.0;
            ds = ds * 1.0;
            principal = py_max2(0.0, ds - interest);
            principal = py_min2(principal, balance);
        } else principal = 0.0;
        double closing = py_max2(0.0, balance - principal);
        op[i] = balance; in[i] = interest; pr[i] = principal; cl[i] = closing;
        balance = closing;
    }
}

static double backward(const DebtGeom *D, const double *cf_d) {
    double closing = 0.0;
    int any = 0;
    for (int64_t i = D->n_d - 1; i >= 0; i--) {
        if (!D->in_rep[i]) continue;
        any = 1;
        double target = D->dscr[i], availability = D->avail[i], cfads = cf_d[i];
        double ds = (target > 0) ? py_max2(0.0, cfads / target) * availability : 0.0;
        double f = D->rates[i] * D->dfs[i];
        if (f > 1e-15) closing = py_min2(closing, ds / f);
        double denom = 1.0 + f;
        double opening = (denom > 1e-15) ? (closing + ds) / denom : closing + ds;
        closing = py_max2(0.0, opening);
    }
    return any ? closing : 0.0;
}

static int sched_conv(const DebtGeom *D, const double *oa, const double *ia, const double *pa, const double *ca,
                      const double *ob, const double *ib, const double *pb, const double *cb,
                      const double *cfa, const double *cfb, const double *txa, const double *txb, double Da, double Db) {
    double at = D->abs_tol, rt = D->rel_tol;
    if (!field_conv(Da, Db, at, rt)) return 0;
    for (int64_t i = 0; i < D->n_d; i++) {
        if (!field_conv(oa[i], ob[i], at, rt) || !field_conv(ia[i], ib[i], at, rt) ||
            !field_conv(pa[i], pb[i], at, rt) || !field_conv(ca[i], cb[i], at, rt) ||
            !field_conv(cfa[i], cfb[i], at, rt) || !field_conv(txa[i], txb[i], at, rt)) return 0;
    }
    return 1;
}

static double max_abs_diff(const DebtGeom *D, const double *oa, const double *ia, const double *pa, const double *ca,
                           const double *ob, const double *ib, const double *pb, const double *cb,
                           const double *cfa, const double *cfb, const double *txa, const double *txb, double Da, double Db) {
    double m = fabs(Da - Db);
    for (int64_t i = 0; i < D->n_d; i++) {
        m = py_max2(m, fabs(oa[i] - ob[i])); m = py_max2(m, fabs(ia[i] - ib[i]));
        m = py_max2(m, fabs(pa[i] - pb[i])); m = py_max2(m, fabs(ca[i] - cb[i]));
        m = py_max2(m, fabs(cfa[i] - cfb[i])); m = py_max2(m, fabs(txa[i] - txb[i]));
    }
    return m;
}

/* The solver's tax callback for one interest context: bank-axis lean tax of the merged input
 * whose senior components are the candidate interest (debt order). */
typedef struct {
    const TaxGeom *G; const TaxPol *T; const IntCtx *X; const DebtGeom *D;
    const int64_t *s_has; const double *s_val;     /* SHL map of the context (NULL = none) */
    TaxScratch *S; double *cf_row, *tx_row;
    int64_t evals;
} TaxFn;

static int tax_fn(TaxFn *F, const double *cand, double *ncf, double *ntx) {
    int st = row_components(F->G, F->X, F->D->row_cand, cand, F->s_has, F->s_val, F->S->gross, F->S->nd, F->S->elig);
    if (st) return st;
    st = lean_tax(F->G, F->T, F->X, F->S, F->S->gross, F->S->nd, F->cf_row, F->tx_row);
    F->evals++;
    if (st) return st;
    for (int64_t i = 0; i < F->D->n_d; i++) { ncf[i] = F->cf_row[F->D->d_row[i]]; ntx[i] = F->tx_row[F->D->d_row[i]]; }
    return FK3_OK;
}

typedef struct { double *v[12]; } Bufs;
static int bufs_alloc(Bufs *B, int count, int64_t n) {
    memset(B, 0, sizeof *B);
    for (int i = 0; i < count; i++) { B->v[i] = arr(n, sizeof(double)); if (!B->v[i]) return FK3_NOMEM; }
    return FK3_OK;
}
static void bufs_free(Bufs *B) { for (int i = 0; i < 12; i++) free(B->v[i]); memset(B, 0, sizeof *B); }

/* _finalise_authoritative (dscr_sculpted, authentic numeric roll). On FK3_OK: cf_final = the CFADS the
 * returned rows are rolled with; fcf/ftx = the last tax response (debt order); fcf_row = its bank rows. */
static int finalise(TaxFn *F, double D0, const double *cf_in, double *cf_final, double *fcf, double *ftx) {
    const DebtGeom *D = F->D;
    int64_t n = D->n_d;
    Bufs B; int st = bufs_alloc(&B, 12, n);
    if (st) { bufs_free(&B); return st; }
    double *cf = B.v[0], *prev_tx = B.v[1], *o1 = B.v[2], *i1 = B.v[3], *p1 = B.v[4], *c1 = B.v[5];
    double *o2 = B.v[6], *i2 = B.v[7], *p2 = B.v[8], *c2 = B.v[9], *ncf = B.v[10], *ntx = B.v[11];
    st = FK3_NOT_CONVERGED;
    memcpy(cf, cf_in, sizeof(double) * (size_t)n);
    for (int64_t i = 0; i < n; i++) prev_tx[i] = 0.0;
    for (int64_t it = 0; it < D->max_fin_iter; it++) {
        roll(D, D0, cf, o1, i1, p1, c1);
        int s2 = tax_fn(F, i1, ncf, ntx);
        if (s2) { st = s2; break; }
        roll(D, D0, ncf, o2, i2, p2, c2);
        if (sched_conv(D, o1, i1, p1, c1, o2, i2, p2, c2, cf, ncf, prev_tx, ntx, D0, D0)) {
            memcpy(cf_final, cf, sizeof(double) * (size_t)n);
            memcpy(fcf, ncf, sizeof(double) * (size_t)n);
            memcpy(ftx, ntx, sizeof(double) * (size_t)n);
            st = FK3_OK; break;
        }
        memcpy(prev_tx, ntx, sizeof(double) * (size_t)n);
        memcpy(cf, ncf, sizeof(double) * (size_t)n);
    }
    bufs_free(&B);
    return st;
}

/* _dscr_sculpting_infeasibility on the authoritative rows roll(D, cf_final) against cfads fcf. */
static int infeasible(const DebtGeom *D, double Dv, const double *cf_final, const double *fcf, double *scratch4) {
    int64_t n = D->n_d;
    double *op = scratch4, *in = scratch4 + n, *pr = scratch4 + 2 * n, *cl = scratch4 + 3 * n;
    roll(D, Dv, cf_final, op, in, pr, cl);
    int64_t last = -1;
    for (int64_t i = 0; i < n; i++) {
        if (!D->in_rep[i]) continue;
        last = i;
        double target = D->dscr[i], availability = D->avail[i], cfads = fcf[i];
        double allowed = (target > 0) ? py_max2(0.0, cfads / target) * availability : 0.0;
        double ds = in[i] + pr[i];
        if (ds > allowed && !field_conv(ds, allowed, D->abs_tol, D->rel_tol)) return 1;
    }
    if (!D->permit_balloon && last >= 0 && !field_conv(cl[last], 0.0, D->abs_tol, D->rel_tol)) return 1;
    return 0;
}

typedef struct {
    double debt;            /* final debt size (SeniorDebtSchedules.debt_size_keur) */
    double dscr_capacity;   /* DSCR solve debt (combined) */
    double max_abs_diff;
    int64_t iteration;
    int64_t binding;        /* 1 DSCR, 2 BOTH, 3 GEARING */
    int64_t tax_evals;
} SolveRes;

/*
 * solve_senior_debt for DSCR_SCULPTED (_solve_dscr) and COMBINED_MINIMUM (_solve_combined).
 * FK3_OK only when the canonical result is authoritative (CONVERGED, feasible).
 * Outputs (debt order): cf_final (CFADS the authoritative rows are rolled with), fcf (CFADS response
 * used by the feasibility check), rows interest and debt service of the authoritative schedule.
 */
static int solve(TaxFn *F, SolveRes *R, double *cf_final, double *fcf, double *row_in, double *row_ds) {
    const DebtGeom *D = F->D;
    int64_t n = D->n_d;
    Bufs B; int st = bufs_alloc(&B, 12, n);
    double *s4 = arr(4 * n, sizeof(double)), *ftx = arr(n, sizeof(double));
    if (st || !s4 || !ftx) { st = FK3_NOMEM; goto done; }
    double *cf = B.v[0], *tx = B.v[1], *ro = B.v[2], *ri = B.v[3], *rp = B.v[4], *rc = B.v[5];
    double *ko = B.v[6], *ki = B.v[7], *kp = B.v[8], *kc = B.v[9], *ncf = B.v[10], *ntx = B.v[11];
    for (int64_t i = 0; i < n; i++) { cf[i] = 0.0; tx[i] = 0.0; }
    double Dv = D->d0, alpha = D->alpha;
    int have_prev = 0, have_cached = 0, done_dscr = 0;
    double new_D = 0.0, mad = 0.0;
    int64_t iteration = 0;
    st = FK3_NOT_CONVERGED;
    for (iteration = 1; iteration <= D->max_iter; iteration++) {
        if (have_cached) {
            memcpy(ro, ko, sizeof(double) * (size_t)n); memcpy(ri, ki, sizeof(double) * (size_t)n);
            memcpy(rp, kp, sizeof(double) * (size_t)n); memcpy(rc, kc, sizeof(double) * (size_t)n);
            have_cached = 0;
        } else roll(D, Dv, cf, ro, ri, rp, rc);
        int s2 = tax_fn(F, ri, ncf, ntx);
        if (s2) { st = s2; goto done; }
        double cap = backward(D, ncf);
        if (cap == 0.0 && Dv > 0.0 && iteration == 1) { st = FK3_NOT_CONVERGED; goto done; }
        new_D = alpha * cap + (1.0 - alpha) * Dv;
        new_D = py_max2(0.0, new_D);
        int checked = 0;
        if (have_prev) {
            roll(D, new_D, ncf, ko, ki, kp, kc);
            checked = 1;
            int conv = sched_conv(D, ro, ri, rp, rc, ko, ki, kp, kc, cf, ncf, tx, ntx, Dv, new_D);
            mad = max_abs_diff(D, ro, ri, rp, rc, ko, ki, kp, kc, cf, ncf, tx, ntx, Dv, new_D);
            if (conv) {
                int sf = finalise(F, new_D, ncf, cf_final, fcf, ftx);
                if (sf) { st = sf; goto done; }
                if (infeasible(D, new_D, cf_final, fcf, s4)) { st = FK3_NOT_CONVERGED; goto done; }
                done_dscr = 1;
                break;
            }
        }
        have_prev = 1;
        Dv = new_D;
        memcpy(cf, ncf, sizeof(double) * (size_t)n); memcpy(tx, ntx, sizeof(double) * (size_t)n);
        if (checked) have_cached = 1;
    }
    if (!done_dscr) { st = FK3_NOT_CONVERGED; goto done; }   /* MAX_ITERATIONS_REACHED */
    R->iteration = iteration; R->max_abs_diff = mad; R->dscr_capacity = new_D;
    if (D->mode == FK3_MODE_DSCR) {
        R->debt = new_D; R->binding = 1;
    } else {
        double gearing = D->gearing_cap, dcap = new_D;
        if (fabs(dcap - gearing) <= D->abs_tol) R->binding = 2;
        else if (dcap < gearing) R->binding = 1;
        else R->binding = 3;
        double final_d = py_min2(dcap, gearing);
        for (int64_t i = 0; i < n; i++) cf[i] = 0.0;
        int sf = finalise(F, final_d, cf, cf_final, fcf, ftx);
        if (sf) { st = sf; goto done; }
        if (infeasible(D, final_d, cf_final, fcf, s4)) { st = FK3_NOT_CONVERGED; goto done; }
        R->debt = final_d;
    }
    /* authoritative rows: roll(debt, cf_final) */
    {
        double *op = s4, *in = s4 + n, *pr = s4 + 2 * n, *cl = s4 + 3 * n;
        roll(D, R->debt, cf_final, op, in, pr, cl);
        for (int64_t i = 0; i < n; i++) { row_in[i] = in[i]; row_ds[i] = in[i] + pr[i]; }
    }
    R->tax_evals = F->evals;
    st = FK3_OK;
done:
    bufs_free(&B); free(s4); free(ftx);
    return st;
}

/* =================================================================================== SHL */

/* Transliteration of the V10 Stage 2 operating roll (compute_shareholder_loan_schedules operating
 * rows; construction rows and the chain opening are taken from the canonical cash-independent
 * template). enforce: 0 = no maturity residual check (fixed-point iterations). */
typedef struct {
    int64_t n, n_con;
    const int64_t *period_index;   /* [n] */
    const int64_t *is_con;         /* [n] construction flag (construction rows form a prefix) */
    const double *dcf;             /* [n] */
    const double *t_gross, *t_close;  /* [n_con] template construction rows */
    double opening0, rate, conv_tol;
    int64_t mode, repayment_start, maturity_index;
} ShlGeom;

static int wf_ok(double opening, double rate, double dcf, double cash) {
    if (!isfinite(opening) || !isfinite(rate) || !isfinite(dcf) || !isfinite(cash)) return 0;
    if (opening < 0.0 || rate < 0.0 || dcf <= 0.0 || cash < 0.0) return 0;
    return 1;
}

static int validate_shl(const ShlGeom *H, int64_t n_rows) {
    if (!H || H->n != n_rows || H->n_con < 0 || H->n_con > H->n) return FK3_INVALID_PLAN;
    if (!H->period_index || !H->is_con || !H->dcf) return FK3_INVALID_PLAN;
    if (H->n_con > 0 && (!H->t_gross || !H->t_close)) return FK3_INVALID_PLAN;
    if (H->mode != FK3_SHL_BULLET && H->mode != FK3_SHL_SWEEP) return FK3_INVALID_PLAN;
    for (int64_t j = 0; j < H->n; j++) if ((H->is_con[j] != 0) != (j < H->n_con)) return FK3_INVALID_PLAN;
    if (!isfinite(H->opening0) || !isfinite(H->rate) || !isfinite(H->conv_tol)) return FK3_NONFINITE;
    for (int64_t j = 0; j < H->n_con; j++) if (!isfinite(H->t_gross[j]) || !isfinite(H->t_close[j])) return FK3_NONFINITE;
    return FK3_OK;
}

static int shl_roll(const ShlGeom *H, const double *cash, double *gross_out, double *close_out) {
    const double thr = H->conv_tol + 1e-9;
    double opening = H->opening0;
    int have_residual = 0;
    double residual = 0.0;
    for (int64_t j = 0; j < H->n; ++j) {
        const double raw = cash[j];
        if (!isfinite(raw) || raw < 0.0) return FK3_DECLINE;
        const int64_t idx = H->period_index[j];
        double gr, cl;
        if (j < H->n_con) { gr = H->t_gross[j]; cl = H->t_close[j]; }
        else if (have_residual) { gr = 0.0; cl = residual; }
        else {
            const double dcf = H->dcf[j];
            double eligible = raw;
            const int is_mat = (idx == H->maturity_index);
            if (H->mode == FK3_SHL_SWEEP && idx < H->repayment_start) {
                if (!wf_ok(opening, H->rate, dcf, raw)) return FK3_DECLINE;
                const double pre_gross = opening * H->rate * dcf;
                eligible = py_min2(raw, pre_gross);
            }
            if (!wf_ok(opening, H->rate, dcf, eligible)) return FK3_DECLINE;
            const double gross = opening * H->rate * dcf;
            const double cash_interest = py_min2(eligible, gross);
            const double capitalised = gross - cash_interest;
            const double remaining = eligible - cash_interest;
            const double outstanding = opening + capitalised;
            double principal;
            if (H->mode == FK3_SHL_BULLET) principal = is_mat ? py_min2(remaining, outstanding) : 0.0;
            else principal = py_max2(0.0, py_min2(remaining, outstanding));
            const double closing = py_max2(outstanding - principal, 0.0);
            gr = gross; cl = closing;
            opening = closing;
            if (H->mode == FK3_SHL_BULLET && is_mat && closing > thr) { have_residual = 1; residual = closing; }
        }
        gross_out[j] = gr; close_out[j] = cl;
    }
    return FK3_OK;
}

/* ======================================================================= entry points */

typedef struct {
    int64_t abi_version, struct_size;
    /* bank (debt-sizing) tax axis = solver callback axis, base tax axis */
    TaxGeom bank, base;
    TaxPol pol;
    IntCtx bank_ctx, base_ctx;
    DebtGeom debt;
    ShlGeom shl;
    int64_t shl_max_iter; double shl_abs_tol, shl_rel_tol;
    int64_t use_shl;
} Stage3Plan;

int64_t fk3_plan_size(void) { return (int64_t)sizeof(Stage3Plan); }
int64_t fk3_geom_size(void) { return (int64_t)sizeof(TaxGeom); }

typedef struct {
    int64_t abi_version, status_detail;
    int64_t shl_iterations;               /* fixed-point iteration count at convergence */
    double last_closing_delta, last_interest_delta;
    SolveRes solve;                       /* final solve (the only solve of the plain path) */
    int64_t loop_solves, loop_tax_evals;  /* native coverage counters */
} Stage3Out;

int64_t fk3_out_size(void) { return (int64_t)sizeof(Stage3Out); }

static int validate_plan(const Stage3Plan *P) {
    if (!P) return FK3_INVALID_PLAN;
    if (P->abi_version != FK3_ABI || P->struct_size != (int64_t)sizeof(Stage3Plan)) return FK3_ABI_MISMATCH;
    int st;
    if ((st = validate_geom(&P->bank))) return st;
    if ((st = validate_pol(&P->pol, &P->bank))) return st;
    if ((st = validate_ctx(&P->bank_ctx, &P->bank))) return st;
    if ((st = validate_debt(&P->debt, &P->bank))) return st;
    if (P->use_shl != 0 && P->use_shl != 1) return FK3_INVALID_PLAN;
    if (P->use_shl) {
        if ((st = validate_geom(&P->base))) return st;
        if ((st = validate_pol(&P->pol, &P->base))) return st;
        if ((st = validate_ctx(&P->base_ctx, &P->base))) return st;
        if (P->base.n_rows != P->bank.n_rows) return FK3_INVALID_PLAN;
        for (int64_t r = 0; r < P->bank.n_rows; r++) if (P->base.row_period[r] != P->bank.row_period[r]) return FK3_INVALID_PLAN;
        if ((st = validate_shl(&P->shl, P->base.n_rows))) return st;
        for (int64_t r = 0; r < P->base.n_rows; r++) if (P->shl.period_index[r] != P->base.row_period[r]) return FK3_INVALID_PLAN;
        if (!in_range(P->shl_max_iter, 0, FK3_MAX_ITER + 1)) return FK3_INVALID_PLAN;
        if (!isfinite(P->shl_abs_tol) || !isfinite(P->shl_rel_tol)) return FK3_NONFINITE;
    }
    return FK3_OK;
}

/*
 * Senior debt model without SHL: solve_senior_debt with the run_senior_debt_model.<locals>.tax_cfads_fn
 * context (merge of base tax input and candidate senior interest, bank axis).
 * Outputs (debt order, capacity >= n_d): cf_final, fcf, row interest, row debt service.
 */
int fk3_plain(const Stage3Plan *P, Stage3Out *O, double *cf_final, double *fcf, double *row_in, double *row_ds, int64_t cap) {
    int st = validate_plan(P);
    if (st) return st;
    if (!O || !cf_final || !fcf || !row_in || !row_ds || cap < P->debt.n_d || P->use_shl) return FK3_INVALID_PLAN;
    memset(O, 0, sizeof *O);
    O->abi_version = FK3_ABI;
    TaxScratch S; st = alloc_tax_scratch(&P->bank, &P->pol, &S);
    if (st) return st;
    double *cf_row = arr(P->bank.n_rows, sizeof(double)), *tx_row = arr(P->bank.n_rows, sizeof(double));
    if (!cf_row || !tx_row) { st = FK3_NOMEM; goto done; }
    TaxFn F = {&P->bank, &P->pol, &P->bank_ctx, &P->debt, NULL, NULL, &S, cf_row, tx_row, 0};
    st = solve(&F, &O->solve, cf_final, fcf, row_in, row_ds);
done:
    free(cf_row); free(tx_row); free_tax_scratch(&S);
    return st;
}

/*
 * _run_senior_debt_model_with_shl fixed point (dynamic interest limitation disabled):
 *   for iteration in 1..max: solve(bank, SHL map = guess) ; base lean tax(senior, guess) ->
 *   post-senior cash -> SHL operating roll -> bank lean tax(senior, guess) (fail-closed checks; its
 *   result is discarded by the reference too) -> convergence on the closing / interest deltas;
 *   then the final solve with the converged SHL interest.
 * Outputs: shl_gross [n_rows] (final SHL gross interest), shl_close [n_rows] (closing of the converged
 * schedule), and the final solve vectors as fk3_plain.
 */
int fk3_shl_fixed_point(const Stage3Plan *P, Stage3Out *O, double *shl_gross, double *shl_close, int64_t cap_rows,
                        double *cf_final, double *fcf, double *row_in, double *row_ds, int64_t cap) {
    int st = validate_plan(P);
    if (st) return st;
    if (!O || !shl_gross || !shl_close || !cf_final || !fcf || !row_in || !row_ds || !P->use_shl ||
        cap < P->debt.n_d || cap_rows < P->base.n_rows) return FK3_INVALID_PLAN;
    memset(O, 0, sizeof *O);
    O->abi_version = FK3_ABI;
    const int64_t nr = P->base.n_rows, nd_ = P->debt.n_d;
    TaxScratch Sb, Sk;
    st = alloc_tax_scratch(&P->bank, &P->pol, &Sb);
    if (st) return st;
    st = alloc_tax_scratch(&P->base, &P->pol, &Sk);
    if (st) { free_tax_scratch(&Sb); return st; }
    double *cf_row = arr(nr, sizeof(double)), *tx_row = arr(nr, sizeof(double));
    double *bcf = arr(nr, sizeof(double)), *btx = arr(nr, sizeof(double));
    double *cash = arr(nr, sizeof(double)), *guess = arr(nr, sizeof(double)), *prev_close = arr(nr, sizeof(double));
    double *gross = arr(nr, sizeof(double)), *close = arr(nr, sizeof(double));
    double *ds_row = arr(nr, sizeof(double));
    int64_t *s_has = arr(nr, sizeof(int64_t)), *base_cand = arr(nr, sizeof(int64_t));
    double *l_cf = arr(nd_, sizeof(double)), *l_fcf = arr(nd_, sizeof(double));
    double *l_in = arr(nd_, sizeof(double)), *l_ds = arr(nd_, sizeof(double));
    if (!cf_row || !tx_row || !bcf || !btx || !cash || !guess || !prev_close || !gross || !close || !ds_row ||
        !s_has || !base_cand || !l_cf || !l_fcf || !l_in || !l_ds) { st = FK3_NOMEM; goto done; }
    for (int64_t r = 0; r < nr; r++) { s_has[r] = 0; guess[r] = 0.0; base_cand[r] = P->debt.row_cand[r]; }
    double last_closing = INFINITY, last_interest = INFINITY;
    int have_prev = 0, converged = 0;
    int64_t iteration;
    for (iteration = 1; iteration <= P->shl_max_iter; iteration++) {
        TaxFn F = {&P->bank, &P->pol, &P->bank_ctx, &P->debt, s_has, guess, &Sb, cf_row, tx_row, 0};
        SolveRes R;
        st = solve(&F, &R, l_cf, l_fcf, l_in, l_ds);
        O->loop_solves++; O->loop_tax_evals += F.evals;
        if (st) goto done;                                   /* non-authoritative -> reference raises */
        /* base iteration tax: merge(base, senior interest, guess) on the base axis */
        st = row_components(&P->base, &P->base_ctx, base_cand, l_in, s_has, guess, Sk.gross, Sk.nd, Sk.elig);
        if (st) goto done;
        st = lean_tax(&P->base, &P->pol, &P->base_ctx, &Sk, Sk.gross, Sk.nd, bcf, btx);
        O->loop_tax_evals++;
        if (st) goto done;
        /* post-senior cash: after = base CFADS - senior DS (0.0 outside the debt tenor) */
        for (int64_t r = 0; r < nr; r++) ds_row[r] = 0.0;
        for (int64_t j = 0; j < nd_; j++) ds_row[P->debt.d_row[j]] = l_ds[j];
        for (int64_t r = 0; r < nr; r++) {
            double after = bcf[r] - ds_row[r];
            cash[r] = P->shl.is_con[r] ? 0.0 : py_max2(0.0, after);
        }
        st = shl_roll(&P->shl, cash, gross, close);
        if (st) goto done;
        /* bank iteration tax (same merge on the bank axis): evaluated for its fail-closed checks */
        st = row_components(&P->bank, &P->bank_ctx, P->debt.row_cand, l_in, s_has, guess, Sb.gross, Sb.nd, Sb.elig);
        if (st) goto done;
        st = lean_tax(&P->bank, &P->pol, &P->bank_ctx, &Sb, Sb.gross, Sb.nd, cf_row, tx_row);
        O->loop_tax_evals++;
        if (st) goto done;
        if (have_prev) {
            double mc = fabs(prev_close[0] - close[0]);
            for (int64_t r = 1; r < nr; r++) mc = py_max2(mc, fabs(prev_close[r] - close[r]));
            double gi0 = s_has[0] ? guess[0] : 0.0;
            double mi = fabs(gi0 - gross[0]);
            for (int64_t r = 1; r < nr; r++) mi = py_max2(mi, fabs((s_has[r] ? guess[r] : 0.0) - gross[r]));
            last_closing = mc; last_interest = mi;
            if (field_conv(mc, 0.0, P->shl_abs_tol, P->shl_rel_tol) && field_conv(mi, 0.0, P->shl_abs_tol, P->shl_rel_tol) &&
                field_conv(0.0, 0.0, P->shl_abs_tol, P->shl_rel_tol) && 0.0 <= P->shl_rel_tol) {
                memcpy(prev_close, close, sizeof(double) * (size_t)nr);
                memcpy(guess, gross, sizeof(double) * (size_t)nr);
                for (int64_t r = 0; r < nr; r++) s_has[r] = 1;
                converged = 1;
                break;
            }
        }
        memcpy(prev_close, close, sizeof(double) * (size_t)nr);
        memcpy(guess, gross, sizeof(double) * (size_t)nr);
        for (int64_t r = 0; r < nr; r++) s_has[r] = 1;
        have_prev = 1;
    }
    if (!converged) { st = FK3_SHL_NOT_CONVERGED; goto done; }
    O->shl_iterations = iteration; O->last_closing_delta = last_closing; O->last_interest_delta = last_interest;
    memcpy(shl_gross, guess, sizeof(double) * (size_t)nr);
    memcpy(shl_close, prev_close, sizeof(double) * (size_t)nr);
    {
        TaxFn F = {&P->bank, &P->pol, &P->bank_ctx, &P->debt, s_has, guess, &Sb, cf_row, tx_row, 0};
        st = solve(&F, &O->solve, cf_final, fcf, row_in, row_ds);
    }
done:
    free(cf_row); free(tx_row); free(bcf); free(btx); free(cash); free(guess); free(prev_close);
    free(gross); free(close); free(ds_row); free(s_has); free(base_cand);
    free(l_cf); free(l_fcf); free(l_in); free(l_ds);
    free_tax_scratch(&Sb); free_tax_scratch(&Sk);
    return st;
}

/*
 * Stage 3a entry: the full calculate_tax numerics for one typed tax input, given as row components
 * (gross interest, SHL non-deductible, SHL eligible, reintegration, financing income — extracted from
 * the canonical typed input by the canonical helpers).
 */
typedef struct {
    int64_t abi_version, struct_size;
    TaxGeom geom; TaxPol pol;
    const double *gross, *nd, *elig, *reint, *fin;     /* [n_rows] */
} FullTaxPlan;

int64_t fk3_full_tax_plan_size(void) { return (int64_t)sizeof(FullTaxPlan); }

/* Output layout (all lengths from the validated plan; the caller passes exact capacities):
 *   out_d [9 * n_years + 9 * n_slots + 9 * n_rows + 1] doubles:
 *     year vectors y_interest, y_reint, y_fin, capacity, deductible, disallowed, ti_before, ti_after, liability;
 *     slot vectors s_interest, s_ded, s_dis, s_norm, s_ebitda, s_reint, s_elig, s_nd, s_fin;
 *     row vectors  r_ded, r_dis, r_ti_share, r_cit, r_elig, r_nd, r_cash, r_cfads, r_ti_after_share;
 *     terminal unpaid tax;
 *   out_i [2 * n_years + n_rows] int64: rule, allow (per year), primary tax year (per row). */
int fk3_full_tax(const FullTaxPlan *Q, double *out_d, int64_t cap_d, int64_t *out_i, int64_t cap_i) {
    if (!Q || Q->abi_version != FK3_ABI || Q->struct_size != (int64_t)sizeof(FullTaxPlan)) return FK3_ABI_MISMATCH;
    int st = validate_geom(&Q->geom);
    if (st) return st;
    if ((st = validate_pol(&Q->pol, &Q->geom))) return st;
    if (!out_d || !out_i || !Q->gross || !Q->nd || !Q->elig || !Q->reint || !Q->fin) return FK3_INVALID_PLAN;
    const int64_t ny = Q->geom.n_years, ns = Q->geom.n_slots, nr = Q->geom.n_rows;
    int64_t need_d = 9 * ny + 9 * ns + 9 * nr + 1, need_i = 2 * ny + nr;     /* bounded by validate_geom caps */
    if (cap_d != need_d || cap_i != need_i) return FK3_INVALID_PLAN;
    for (int64_t r = 0; r < nr; r++)
        if (!isfinite(Q->gross[r]) || !isfinite(Q->nd[r]) || !isfinite(Q->elig[r]) || !isfinite(Q->reint[r]) ||
            !isfinite(Q->fin[r])) return FK3_NONFINITE;
    FullTaxOut O;
    double *d = out_d;
    double **yv[] = {&O.y_interest, &O.y_reint, &O.y_fin, &O.capacity, &O.deductible, &O.disallowed, &O.ti_before,
                     &O.ti_after, &O.liability};
    double **sv[] = {&O.s_interest, &O.s_ded, &O.s_dis, &O.s_norm, &O.s_ebitda, &O.s_reint, &O.s_elig, &O.s_nd, &O.s_fin};
    double **rv[] = {&O.r_ded, &O.r_dis, &O.r_ti_share, &O.r_cit, &O.r_elig, &O.r_nd, &O.r_cash, &O.r_cfads,
                     &O.r_ti_after_share};
    for (int k = 0; k < 9; k++) { *yv[k] = d; d += ny; }
    for (int k = 0; k < 9; k++) { *sv[k] = d; d += ns; }
    for (int k = 0; k < 9; k++) { *rv[k] = d; d += nr; }
    O.rule = out_i; O.allow = out_i + ny; O.r_primary_year = out_i + 2 * ny;
    O.terminal_unpaid = 0.0;
    IntCtx X = {NULL, NULL, NULL, NULL, Q->reint, Q->fin, 0.0};
    TaxScratch S; st = alloc_tax_scratch(&Q->geom, &Q->pol, &S);
    if (st) return st;
    st = full_tax(&Q->geom, &Q->pol, &X, &S, Q->gross, Q->nd, Q->elig, &O);
    free_tax_scratch(&S);
    if (st == FK3_OK) out_d[need_d - 1] = O.terminal_unpaid;
    return st;
}
