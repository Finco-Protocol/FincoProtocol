/*
 * FINCO V10 Stage 1 candidate kernel — RESEARCH CANDIDATE, DEFAULT OFF, NOT A FINANCIAL AUTHORITY.
 *
 * Exact replay of the canonical Python Senior DSCR solver (_solve_dscr / _finalise_authoritative,
 * dscr_sculpted, authentic numeric roll) and of the numeric calendar-year tax kernel
 * (_evaluate_numeric_tax_vectors_uncached, taxable_income_after_lcf_series,
 * calculate_canonical_cfads_value). Same IEEE-754 binary64 operations in the same order; CPython
 * >= 3.12 builtin sum()/max()/min() semantics.
 *
 * Safety contract (V10-01, V10-04):
 *  - Every array crosses the ABI with an explicit int64 length. Every length is range-checked and
 *    every index read from an array is validated against the capacity of the array it addresses
 *    BEFORE any dereference. Nested ranges (slot/contribution start+count) use checked addition.
 *  - All integer arithmetic that can grow (year + carry-forward, payment + lag, index - min, size
 *    products) uses checked 64-bit builtins. An unrepresentable value returns FK_ST_DECLINE: the
 *    caller runs the canonical Python, it never clamps or wraps.
 *  - The kernel never raises a financial exception and has no global mutable state; scratch is
 *    per call. Any non-OK status means "canonical Python decides".
 * Build flags (see build.py): -O2 -fno-fast-math -ffp-contract=off (never -ffast-math/-fwrapv).
 */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define FK_ABI_VERSION 10001
#ifndef FK_BUILD_ID
#define FK_BUILD_ID "unset"
#endif

#define FK_ST_OK 0
#define FK_ST_DECLINE 1          /* reference would take another path (e.g. int sum, KeyError) */
#define FK_ST_NOT_CONVERGED 2    /* MAX_ITERATIONS / FINALISATION / NO_DEBT_CAPACITY -> replay */
#define FK_ST_NONFINITE 3
#define FK_ST_NOMEM 4
#define FK_ST_INVALID_PLAN 5     /* ABI/plan contract violated: never dereferenced */
#define FK_ST_ABI_MISMATCH 6

/* hard caps, far above any real model, keep every size product small */
#define FK_MAX_ROWS 100000
#define FK_MAX_SLOTS 1000000
#define FK_MAX_YEARS 100000
#define FK_MAX_OPEN 100000
#define FK_MAX_ITER 10000000
#define FK_MAX_SPAN 1000000

#ifdef FK_TEST_ALLOC
static long fk_alloc_budget = -1;     /* test-only allocation-failure injection */
void fk_test_set_alloc_budget(long n) { fk_alloc_budget = n; }
static void *fk_malloc(size_t n) { if (fk_alloc_budget == 0) return NULL; if (fk_alloc_budget > 0) fk_alloc_budget--; return malloc(n ? n : 1); }
#else
static void *fk_malloc(size_t n) { return malloc(n ? n : 1); }
#endif

int fk_abi_version(void) { return FK_ABI_VERSION; }
const char *fk_build_id(void) { return FK_BUILD_ID; }

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

double fk_py_sum(const double *x, int64_t n) {
    int is_int;
    if (n < 0 || (n > 0 && x == NULL)) return NAN;
    return py_sum(x, n, &is_int);
}

typedef struct {
    int64_t abi_version;
    int64_t struct_size;
    /* ---- tax plan, rows in `periods` order ---- */
    int64_t n_rows, n_years, n_slots, n_sp, n_sorted, n_open, idx_span;
    const int64_t *row_kind;          /* [n_rows]  0 pass-through, 1 single, 2 multi */
    const int64_t *row_slot_start;    /* [n_rows] */
    const int64_t *row_slot_count;    /* [n_rows] */
    const int64_t *slot_pos;          /* [n_slots] year position */
    const double *slot_frac;          /* [n_slots] */
    const double *y_ebitda;           /* [n_years] */
    const double *y_dep;              /* [n_years] */
    const int64_t *year_key;          /* [n_years] */
    const int64_t *payment_idx;       /* [n_years] */
    int64_t timing_payment, lag, max_idx;
    const int64_t *sp_start;          /* [n_sorted] */
    const int64_t *sp_count;          /* [n_sorted] */
    const int64_t *sp_k;              /* [n_sp] */
    const double *sp_nf;              /* [n_sp] */
    int64_t idx_min;
    const int64_t *idx_to_sorted;     /* [idx_span] sorted pos or -1 */
    const int64_t *row_sorted;        /* [n_rows] sorted pos of each row's period or -1 */
    int64_t atad_enabled; double atad_limit, atad_threshold;
    int64_t loss_gate; double corporate_rate; int64_t lcf_years;
    const int64_t *open_last;         /* [n_open] */
    const double *open_amount;        /* [n_open] */
    const int64_t *row_cand;          /* [n_rows] candidate (debt) position or -1 */
    const double *row_other, *row_elig, *row_nd, *row_static_gross, *row_static_nd;  /* [n_rows] */
    const double *row_reint, *row_fin, *row_ebitda;                                   /* [n_rows] */
    /* ---- solver geometry, debt periods ---- */
    int64_t n_d;
    const double *rates, *dfs, *dscr, *avail;   /* [n_d] */
    const int64_t *in_rep;                       /* [n_d] */
    const int64_t *d_row;                        /* [n_d] tax row of each debt period */
    double alpha; int64_t max_iter; double abs_tol, rel_tol;
    int64_t max_fin_iter;
} Plan;

int64_t fk_plan_size(void) { return (int64_t)sizeof(Plan); }

static int in_range(int64_t v, int64_t lo, int64_t hi_excl) { return v >= lo && v < hi_excl; }

/* Full structural validation: everything the kernel will dereference is checked here once. */
static int validate_plan(const Plan *P) {
    if (P == NULL) return FK_ST_INVALID_PLAN;
    if (P->abi_version != FK_ABI_VERSION || P->struct_size != (int64_t)sizeof(Plan)) return FK_ST_ABI_MISMATCH;
    if (!in_range(P->n_rows, 1, FK_MAX_ROWS + 1) || !in_range(P->n_years, 1, FK_MAX_YEARS + 1) ||
        !in_range(P->n_slots, 1, FK_MAX_SLOTS + 1) || !in_range(P->n_sp, 0, FK_MAX_SLOTS + 1) ||
        !in_range(P->n_sorted, 1, FK_MAX_ROWS + 1) || !in_range(P->n_open, 0, FK_MAX_OPEN + 1) ||
        !in_range(P->idx_span, 1, FK_MAX_SPAN + 1) || !in_range(P->n_d, 1, FK_MAX_ROWS + 1) ||
        !in_range(P->max_iter, 0, FK_MAX_ITER + 1) || !in_range(P->max_fin_iter, 0, FK_MAX_ITER + 1))
        return FK_ST_INVALID_PLAN;
    const void *ptrs[] = {P->row_kind, P->row_slot_start, P->row_slot_count, P->slot_pos, P->slot_frac,
        P->y_ebitda, P->y_dep, P->year_key, P->payment_idx, P->sp_start, P->sp_count, P->idx_to_sorted,
        P->row_sorted, P->row_cand, P->row_other, P->row_elig, P->row_nd, P->row_static_gross,
        P->row_static_nd, P->row_reint, P->row_fin, P->row_ebitda, P->rates, P->dfs, P->dscr, P->avail,
        P->in_rep, P->d_row};
    for (size_t i = 0; i < sizeof(ptrs) / sizeof(ptrs[0]); i++) if (ptrs[i] == NULL) return FK_ST_INVALID_PLAN;
    if (P->n_sp > 0 && (P->sp_k == NULL || P->sp_nf == NULL)) return FK_ST_INVALID_PLAN;
    if (P->n_open > 0 && (P->open_last == NULL || P->open_amount == NULL)) return FK_ST_INVALID_PLAN;
    /* rows: kind, slot ranges (checked), candidate map, sorted map */
    int64_t frag_total = 0;
    for (int64_t r = 0; r < P->n_rows; r++) {
        int64_t kind = P->row_kind[r], s0 = P->row_slot_start[r], sc = P->row_slot_count[r], end;
        if (!in_range(kind, 0, 3) || s0 < 0 || sc < 1) return FK_ST_INVALID_PLAN;
        if (kind != 2 && sc != 1) return FK_ST_INVALID_PLAN;
        if (__builtin_add_overflow(s0, sc, &end) || end > P->n_slots) return FK_ST_INVALID_PLAN;
        if (__builtin_add_overflow(frag_total, sc, &frag_total) || frag_total > FK_MAX_SLOTS) return FK_ST_INVALID_PLAN;
        if (!in_range(P->row_cand[r], -1, P->n_d)) return FK_ST_INVALID_PLAN;
        if (!in_range(P->row_sorted[r], -1, P->n_sorted)) return FK_ST_INVALID_PLAN;
    }
    for (int64_t s = 0; s < P->n_slots; s++) if (!in_range(P->slot_pos[s], 0, P->n_years)) return FK_ST_INVALID_PLAN;
    for (int64_t s = 0; s < P->n_sorted; s++) {
        int64_t a = P->sp_start[s], c = P->sp_count[s], end;
        if (a < 0 || c < 0 || __builtin_add_overflow(a, c, &end) || end > P->n_sp) return FK_ST_INVALID_PLAN;
    }
    for (int64_t t = 0; t < P->n_sp; t++) if (!in_range(P->sp_k[t], 0, P->n_years)) return FK_ST_INVALID_PLAN;
    for (int64_t o = 0; o < P->idx_span; o++) if (!in_range(P->idx_to_sorted[o], -1, P->n_sorted)) return FK_ST_INVALID_PLAN;
    /* debt <-> row bijection: d_row[j] = r  <=>  row_cand[r] = j */
    for (int64_t j = 0; j < P->n_d; j++) {
        int64_t r = P->d_row[j];
        if (!in_range(r, 0, P->n_rows) || P->row_cand[r] != j) return FK_ST_INVALID_PLAN;
        if (P->in_rep[j] != 0 && P->in_rep[j] != 1) return FK_ST_INVALID_PLAN;
    }
    int64_t ncand = 0;
    for (int64_t r = 0; r < P->n_rows; r++) if (P->row_cand[r] >= 0) ncand++;
    if (ncand != P->n_d) return FK_ST_INVALID_PLAN;
    if (P->timing_payment != 0 && P->timing_payment != 1) return FK_ST_INVALID_PLAN;
    if (P->atad_enabled != 0 && P->atad_enabled != 1) return FK_ST_INVALID_PLAN;
    if (P->loss_gate != 0 && P->loss_gate != 1) return FK_ST_INVALID_PLAN;
    /* integer arithmetic the kernel performs must be representable (checked, never wrapped) */
    int64_t tmp;
    for (int64_t k = 0; k < P->n_years; k++) {
        if (__builtin_add_overflow(P->year_key[k], P->lcf_years, &tmp)) return FK_ST_DECLINE;
        if (__builtin_add_overflow(P->payment_idx[k], P->lag, &tmp)) return FK_ST_DECLINE;
        if (__builtin_sub_overflow(tmp, P->idx_min, &tmp)) return FK_ST_DECLINE;
    }
    for (int64_t i = 0; i < P->n_open; i++) if (__builtin_add_overflow(P->open_last[i], 0, &tmp)) return FK_ST_DECLINE;
    /* finiteness of every float input (the reference never sees non-finite here either) */
    for (int64_t r = 0; r < P->n_rows; r++)
        if (!isfinite(P->row_other[r]) || !isfinite(P->row_elig[r]) || !isfinite(P->row_nd[r]) ||
            !isfinite(P->row_static_gross[r]) || !isfinite(P->row_static_nd[r]) || !isfinite(P->row_reint[r]) ||
            !isfinite(P->row_fin[r]) || !isfinite(P->row_ebitda[r])) return FK_ST_NONFINITE;
    for (int64_t s = 0; s < P->n_slots; s++) if (!isfinite(P->slot_frac[s])) return FK_ST_NONFINITE;
    for (int64_t t = 0; t < P->n_sp; t++) if (!isfinite(P->sp_nf[t])) return FK_ST_NONFINITE;
    for (int64_t k = 0; k < P->n_years; k++) if (!isfinite(P->y_ebitda[k]) || !isfinite(P->y_dep[k])) return FK_ST_NONFINITE;
    for (int64_t i = 0; i < P->n_open; i++) if (!isfinite(P->open_amount[i])) return FK_ST_NONFINITE;
    for (int64_t j = 0; j < P->n_d; j++) {
        if (!isfinite(P->rates[j]) || !isfinite(P->dfs[j])) return FK_ST_NONFINITE;
        if (P->in_rep[j] && (!isfinite(P->dscr[j]) || !isfinite(P->avail[j]))) return FK_ST_NONFINITE;
    }
    if (!isfinite(P->alpha) || !isfinite(P->abs_tol) || !isfinite(P->rel_tol) || !isfinite(P->corporate_rate) ||
        !isfinite(P->atad_limit) || !isfinite(P->atad_threshold)) return FK_ST_NONFINITE;
    return FK_ST_OK;
}

typedef struct {
    double *gross, *nd;
    double *frag_i, *frag_r, *frag_n, *frag_f; int64_t *frag_year;
    double *ybuf, *tb, *after, *liab, *cash_sorted;
    int *allow;
    int64_t *pool_last, *npool_last; double *pool_amt, *npool_amt; int64_t pool_cap;
} Scratch;

static void free_scratch(Scratch *S) {
    free(S->gross); free(S->nd); free(S->frag_i); free(S->frag_r); free(S->frag_n); free(S->frag_f);
    free(S->frag_year); free(S->ybuf); free(S->tb); free(S->after); free(S->liab); free(S->cash_sorted);
    free(S->allow); free(S->pool_last); free(S->npool_last); free(S->pool_amt); free(S->npool_amt);
    memset(S, 0, sizeof *S);
}

static void *arr(int64_t n, size_t elem) {
    size_t bytes;
    if (n < 0 || __builtin_mul_overflow((size_t)n, elem, &bytes)) return NULL;
    return fk_malloc(bytes);
}

static int alloc_scratch(const Plan *P, Scratch *S) {
    memset(S, 0, sizeof *S);
    int64_t nfrag = 0;
    for (int64_t r = 0; r < P->n_rows; r++) nfrag += P->row_slot_count[r];   /* bounded by validate_plan */
    if (__builtin_add_overflow(P->n_open, P->n_years, &S->pool_cap) ||
        __builtin_add_overflow(S->pool_cap, (int64_t)1, &S->pool_cap)) return FK_ST_INVALID_PLAN;
    S->gross = arr(P->n_rows, sizeof(double)); S->nd = arr(P->n_rows, sizeof(double));
    S->frag_i = arr(nfrag, sizeof(double)); S->frag_r = arr(nfrag, sizeof(double));
    S->frag_n = arr(nfrag, sizeof(double)); S->frag_f = arr(nfrag, sizeof(double));
    S->frag_year = arr(nfrag, sizeof(int64_t)); S->ybuf = arr(nfrag, sizeof(double));
    S->tb = arr(P->n_years, sizeof(double)); S->after = arr(P->n_years, sizeof(double));
    S->liab = arr(P->n_years, sizeof(double)); S->allow = arr(P->n_years, sizeof(int));
    S->cash_sorted = arr(P->n_sorted, sizeof(double));
    S->pool_last = arr(S->pool_cap, sizeof(int64_t)); S->npool_last = arr(S->pool_cap, sizeof(int64_t));
    S->pool_amt = arr(S->pool_cap, sizeof(double)); S->npool_amt = arr(S->pool_cap, sizeof(double));
    if (!S->gross || !S->nd || !S->frag_i || !S->frag_r || !S->frag_n || !S->frag_f || !S->frag_year || !S->ybuf ||
        !S->tb || !S->after || !S->liab || !S->allow || !S->cash_sorted || !S->pool_last || !S->npool_last ||
        !S->pool_amt || !S->npool_amt) { free_scratch(S); return FK_ST_NOMEM; }
    return FK_ST_OK;
}

/* one tax + CFADS evaluation for a candidate senior-interest vector (debt order) */
static int tax_cfads(const Plan *P, Scratch *S, const double *cand, double *cfads_row, double *cash_row) {
    int64_t nr = P->n_rows;
    for (int64_t r = 0; r < nr; r++) {
        int64_t j = P->row_cand[r];
        if (j >= 0) { S->gross[r] = cand[j] + P->row_other[r] + P->row_elig[r]; S->nd[r] = P->row_nd[r]; }
        else { S->gross[r] = P->row_static_gross[r]; S->nd[r] = P->row_static_nd[r]; }
    }
    int64_t nf = 0;
    for (int64_t r = 0; r < nr; r++) {
        double gi = S->gross[r], re = P->row_reint[r], sn = S->nd[r], fi = P->row_fin[r];
        int64_t kind = P->row_kind[r], s0 = P->row_slot_start[r], sc = P->row_slot_count[r];
        if (kind == 2) {
            double ai = 0.0, ar = 0.0, an = 0.0, af = 0.0;
            int64_t last = sc - 1;
            for (int64_t i = 0; i < sc; i++) {
                double f_i, f_r, f_n, f_f, frac = P->slot_frac[s0 + i];
                if (i < last) {
                    f_i = gi * frac; f_r = re * frac; f_n = sn * frac; f_f = fi * frac;
                    ai += f_i; ar += f_r; an += f_n; af += f_f;
                } else { f_i = gi - ai; f_r = re - ar; f_n = sn - an; f_f = fi - af; }
                S->frag_i[nf] = f_i; S->frag_r[nf] = f_r; S->frag_n[nf] = f_n; S->frag_f[nf] = f_f;
                S->frag_year[nf] = P->slot_pos[s0 + i]; nf++;
            }
        } else if (kind == 1) {
            S->frag_i[nf] = gi - 0.0; S->frag_r[nf] = re - 0.0; S->frag_n[nf] = sn - 0.0; S->frag_f[nf] = fi - 0.0;
            S->frag_year[nf] = P->slot_pos[s0]; nf++;
        } else {
            S->frag_i[nf] = gi; S->frag_r[nf] = re; S->frag_n[nf] = sn; S->frag_f[nf] = fi;
            S->frag_year[nf] = P->slot_pos[s0]; nf++;
        }
    }
    int64_t ny = P->n_years;
    for (int64_t k = 0; k < ny; k++) {
        double ys[4]; int isint[4];
        const double *src[4] = {S->frag_i, S->frag_r, S->frag_n, S->frag_f};
        for (int q = 0; q < 4; q++) {
            int64_t m = 0;
            for (int64_t t = 0; t < nf; t++) if (S->frag_year[t] == k) S->ybuf[m++] = src[q][t];
            ys[q] = py_sum(S->ybuf, m, &isint[q]);
        }
        if (isint[0] || isint[1] || isint[2] || isint[3]) return FK_ST_DECLINE;
        double y_interest = ys[0], y_reint = ys[1], y_shl_nd = ys[2], y_fin = ys[3];
        double ye = P->y_ebitda[k], yd = P->y_dep[k];
        double total = y_interest, deductible;
        if (!P->atad_enabled || total <= 0) deductible = total;
        else {
            double ebitda_based = ye * P->atad_limit;
            double threshold = P->atad_threshold;
            double capacity = (ebitda_based >= threshold) ? ebitda_based : threshold;
            deductible = py_min2(total, py_max2(0.0, capacity));
        }
        S->tb[k] = ye + y_fin - yd - deductible + y_reint;
        if (P->loss_gate) S->allow[k] = (ye + y_fin - yd - y_interest - y_shl_nd + y_reint) > 0.0;
    }
    int64_t np = 0;
    for (int64_t i = 0; i < P->n_open; i++) { S->pool_last[np] = P->open_last[i]; S->pool_amt[np] = P->open_amount[i]; np++; }
    for (int64_t k = 0; k < ny; k++) {
        int64_t year = P->year_key[k], w = 0;
        for (int64_t i = 0; i < np; i++)
            if (!(S->pool_last[i] < year)) { S->pool_last[w] = S->pool_last[i]; S->pool_amt[w] = S->pool_amt[i]; w++; }
        np = w;
        double tbk = S->tb[k];
        if (tbk <= 0.0) {
            double generated = (tbk < 0.0) ? -tbk : 0.0;
            if (generated > 1e-12) {
                int64_t last;
                if (np >= S->pool_cap) return FK_ST_INVALID_PLAN;
                if (__builtin_add_overflow(year, P->lcf_years, &last)) return FK_ST_DECLINE;
                S->pool_last[np] = last; S->pool_amt[np] = generated; np++;
            }
            S->after[k] = 0.0;
            continue;
        }
        if (P->loss_gate && !S->allow[k]) { S->after[k] = tbk; continue; }
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
        if (w2 > 0) { memcpy(S->pool_last, S->npool_last, sizeof(int64_t) * (size_t)w2); memcpy(S->pool_amt, S->npool_amt, sizeof(double) * (size_t)w2); }
        np = w2;
        S->after[k] = py_max2(0.0, remaining);
    }
    for (int64_t k = 0; k < ny; k++) S->liab[k] = P->corporate_rate * py_max2(0.0, S->after[k]);
    for (int64_t s = 0; s < P->n_sorted; s++) S->cash_sorted[s] = 0.0;
    if (P->timing_payment) {
        for (int64_t k = 0; k < ny; k++) {
            int64_t pp, o;
            if (__builtin_add_overflow(P->payment_idx[k], P->lag, &pp)) return FK_ST_DECLINE;
            if (pp <= P->max_idx) {
                if (__builtin_sub_overflow(pp, P->idx_min, &o)) return FK_ST_DECLINE;
                if (o < 0 || o >= P->idx_span) return FK_ST_DECLINE;          /* reference: KeyError */
                int64_t sp = P->idx_to_sorted[o];
                if (sp < 0) return FK_ST_DECLINE;
                S->cash_sorted[sp] = S->cash_sorted[sp] + S->liab[k];
            }
        }
    } else {
        for (int64_t s = 0; s < P->n_sorted; s++) {
            int64_t a = P->sp_start[s], c = P->sp_count[s];
            for (int64_t t = 0; t < c; t++) S->cash_sorted[s] = S->cash_sorted[s] + S->liab[P->sp_k[a + t]] * P->sp_nf[a + t];
        }
    }
    for (int64_t r = 0; r < nr; r++) {
        int64_t sp = P->row_sorted[r];
        double cash = (sp >= 0) ? S->cash_sorted[sp] : 0.0;
        cfads_row[r] = P->row_ebitda[r] + P->row_fin[r] - cash;
        cash_row[r] = cash;
    }
    return FK_ST_OK;
}

static void roll(const Plan *P, double D, const double *cf_d, double *op, double *in, double *pr, double *cl) {
    double balance = D;
    for (int64_t i = 0; i < P->n_d; i++) {
        double interest = balance * P->rates[i] * P->dfs[i];
        double principal;
        if (P->in_rep[i]) {
            double cfads = cf_d[i], target = P->dscr[i], ds;
            if (target > 0) ds = py_max2(0.0, cfads / target) * P->avail[i];
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

static double backward(const Plan *P, const double *cf_d) {
    double closing = 0.0;
    int any = 0;
    for (int64_t i = P->n_d - 1; i >= 0; i--) {
        if (!P->in_rep[i]) continue;
        any = 1;
        double target = P->dscr[i], availability = P->avail[i], cfads = cf_d[i];
        double ds = (target > 0) ? py_max2(0.0, cfads / target) * availability : 0.0;
        double f = P->rates[i] * P->dfs[i];
        if (f > 1e-15) closing = py_min2(closing, ds / f);
        double denom = 1.0 + f;
        double opening = (denom > 1e-15) ? (closing + ds) / denom : closing + ds;
        closing = py_max2(0.0, opening);
    }
    return any ? closing : 0.0;
}

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

static int sched_conv(const Plan *P, const double *oa, const double *ia, const double *pa, const double *ca,
                      const double *ob, const double *ib, const double *pb, const double *cb,
                      const double *cfa, const double *cfb, const double *txa, const double *txb, double Da, double Db) {
    double at = P->abs_tol, rt = P->rel_tol;
    if (!field_conv(Da, Db, at, rt)) return 0;
    for (int64_t i = 0; i < P->n_d; i++) {
        if (!field_conv(oa[i], ob[i], at, rt) || !field_conv(ia[i], ib[i], at, rt) ||
            !field_conv(pa[i], pb[i], at, rt) || !field_conv(ca[i], cb[i], at, rt) ||
            !field_conv(cfa[i], cfb[i], at, rt) || !field_conv(txa[i], txb[i], at, rt)) return 0;
    }
    return 1;
}

static double max_abs_diff(const Plan *P, const double *oa, const double *ia, const double *pa, const double *ca,
                           const double *ob, const double *ib, const double *pb, const double *cb,
                           const double *cfa, const double *cfb, const double *txa, const double *txb, double Da, double Db) {
    double m = fabs(Da - Db);
    for (int64_t i = 0; i < P->n_d; i++) {
        m = py_max2(m, fabs(oa[i] - ob[i])); m = py_max2(m, fabs(ia[i] - ib[i]));
        m = py_max2(m, fabs(pa[i] - pb[i])); m = py_max2(m, fabs(ca[i] - cb[i]));
        m = py_max2(m, fabs(cfa[i] - cfb[i])); m = py_max2(m, fabs(txa[i] - txb[i]));
    }
    return m;
}

typedef struct {
    int64_t abi_version;
    int64_t iteration;
    double new_D;
    double max_abs_diff;
    int64_t tax_evals;
} SolveOut;

typedef struct { double *v[16]; } Bufs;
static int bufs_alloc(Bufs *B, int count, int64_t n) {
    memset(B, 0, sizeof *B);
    for (int i = 0; i < count; i++) { B->v[i] = arr(n, sizeof(double)); if (!B->v[i]) return FK_ST_NOMEM; }
    return FK_ST_OK;
}
static void bufs_free(Bufs *B) { for (int i = 0; i < 16; i++) free(B->v[i]); memset(B, 0, sizeof *B); }

static int finalise(const Plan *P, Scratch *S, double D, const double *cf_d_in,
                    double *cf_final_d, double *new_cf_row, double *new_tx_row, int64_t *tax_evals) {
    int64_t n = P->n_d;
    Bufs B; int st = bufs_alloc(&B, 12, n);
    if (st) { bufs_free(&B); return st; }
    double *cf = B.v[0], *prev_tx = B.v[1], *o1 = B.v[2], *i1 = B.v[3], *p1 = B.v[4], *c1 = B.v[5];
    double *o2 = B.v[6], *i2 = B.v[7], *p2 = B.v[8], *c2 = B.v[9], *ncf = B.v[10], *ntx = B.v[11];
    st = FK_ST_NOT_CONVERGED;
    memcpy(cf, cf_d_in, sizeof(double) * (size_t)n);
    for (int64_t i = 0; i < n; i++) prev_tx[i] = 0.0;
    for (int64_t it = 0; it < P->max_fin_iter; it++) {
        roll(P, D, cf, o1, i1, p1, c1);
        int s2 = tax_cfads(P, S, i1, new_cf_row, new_tx_row);
        (*tax_evals)++;
        if (s2) { st = s2; break; }
        for (int64_t i = 0; i < n; i++) { ncf[i] = new_cf_row[P->d_row[i]]; ntx[i] = new_tx_row[P->d_row[i]]; }
        roll(P, D, ncf, o2, i2, p2, c2);
        if (sched_conv(P, o1, i1, p1, c1, o2, i2, p2, c2, cf, ncf, prev_tx, ntx, D, D)) {
            memcpy(cf_final_d, cf, sizeof(double) * (size_t)n);
            st = FK_ST_OK; break;
        }
        memcpy(prev_tx, ntx, sizeof(double) * (size_t)n);
        memcpy(cf, ncf, sizeof(double) * (size_t)n);
    }
    bufs_free(&B);
    return st;
}

/* Output capacities are explicit (V10-04): cf_final_d >= n_d, new rows >= n_rows. */
int fk_solve_dscr(const Plan *P, double D0, SolveOut *out,
                  double *cf_final_d, int64_t cap_final, double *new_cf_row, double *new_tx_row, int64_t cap_rows) {
    int st = validate_plan(P);
    if (st) return st;
    if (out == NULL || cf_final_d == NULL || new_cf_row == NULL || new_tx_row == NULL ||
        cap_final < P->n_d || cap_rows < P->n_rows) return FK_ST_INVALID_PLAN;
    if (!isfinite(D0)) return FK_ST_NONFINITE;
    Scratch S; st = alloc_scratch(P, &S);
    if (st) return st;
    int64_t n = P->n_d, evals = 0;
    Bufs B; st = bufs_alloc(&B, 12, n);
    double *ncf_row = arr(P->n_rows, sizeof(double)), *ntx_row = arr(P->n_rows, sizeof(double));
    if (st || !ncf_row || !ntx_row) { st = FK_ST_NOMEM; goto done; }
    double *cf = B.v[0], *tx = B.v[1], *ro = B.v[2], *ri = B.v[3], *rp = B.v[4], *rc = B.v[5];
    double *ko = B.v[6], *ki = B.v[7], *kp = B.v[8], *kc = B.v[9], *ncf = B.v[10], *ntx = B.v[11];
    for (int64_t i = 0; i < n; i++) { cf[i] = 0.0; tx[i] = 0.0; }
    double D = D0, alpha = P->alpha;
    int have_prev = 0, have_cached = 0;
    st = FK_ST_NOT_CONVERGED;
    for (int64_t iteration = 1; iteration <= P->max_iter; iteration++) {
        if (have_cached) {
            memcpy(ro, ko, sizeof(double) * (size_t)n); memcpy(ri, ki, sizeof(double) * (size_t)n);
            memcpy(rp, kp, sizeof(double) * (size_t)n); memcpy(rc, kc, sizeof(double) * (size_t)n);
            have_cached = 0;
        } else roll(P, D, cf, ro, ri, rp, rc);
        int s2 = tax_cfads(P, &S, ri, ncf_row, ntx_row);
        evals++;
        if (s2) { st = s2; goto done; }
        for (int64_t i = 0; i < n; i++) { ncf[i] = ncf_row[P->d_row[i]]; ntx[i] = ntx_row[P->d_row[i]]; }
        double cap = backward(P, ncf);
        if (cap == 0.0 && D > 0.0 && iteration == 1) { st = FK_ST_NOT_CONVERGED; goto done; }
        double new_D = alpha * cap + (1.0 - alpha) * D;
        new_D = py_max2(0.0, new_D);
        int checked = 0;
        if (have_prev) {
            roll(P, new_D, ncf, ko, ki, kp, kc);
            checked = 1;
            int conv = sched_conv(P, ro, ri, rp, rc, ko, ki, kp, kc, cf, ncf, tx, ntx, D, new_D);
            double mad = max_abs_diff(P, ro, ri, rp, rc, ko, ki, kp, kc, cf, ncf, tx, ntx, D, new_D);
            if (conv) {
                int64_t fe = 0;
                int sf = finalise(P, &S, new_D, ncf, cf_final_d, new_cf_row, new_tx_row, &fe);
                evals += fe;
                if (sf) { st = sf; goto done; }
                out->abi_version = FK_ABI_VERSION; out->iteration = iteration; out->new_D = new_D;
                out->max_abs_diff = mad; out->tax_evals = evals;
                st = FK_ST_OK; goto done;
            }
        }
        have_prev = 1;
        D = new_D;
        memcpy(cf, ncf, sizeof(double) * (size_t)n); memcpy(tx, ntx, sizeof(double) * (size_t)n);
        if (checked) have_cached = 1;
    }
done:
    free(ncf_row); free(ntx_row);
    bufs_free(&B);
    free_scratch(&S);
    return st;
}

int fk_finalise(const Plan *P, double D, const double *cf_d_in, int64_t n_in,
                double *cf_final_d, int64_t cap_final, double *new_cf_row, double *new_tx_row, int64_t cap_rows,
                int64_t *tax_evals) {
    int st = validate_plan(P);
    if (st) return st;
    if (cf_d_in == NULL || cf_final_d == NULL || new_cf_row == NULL || new_tx_row == NULL || tax_evals == NULL ||
        n_in != P->n_d || cap_final < P->n_d || cap_rows < P->n_rows) return FK_ST_INVALID_PLAN;
    if (!isfinite(D)) return FK_ST_NONFINITE;
    for (int64_t i = 0; i < P->n_d; i++) if (!isfinite(cf_d_in[i])) return FK_ST_NONFINITE;
    Scratch S; st = alloc_scratch(P, &S);
    if (st) return st;
    *tax_evals = 0;
    st = finalise(P, &S, D, cf_d_in, cf_final_d, new_cf_row, new_tx_row, tax_evals);
    free_scratch(&S);
    return st;
}

int fk_tax(const Plan *P, const double *cand, int64_t n_cand, double *cf_row, double *tx_row, int64_t cap_rows) {
    int st = validate_plan(P);
    if (st) return st;
    if (cand == NULL || cf_row == NULL || tx_row == NULL || n_cand != P->n_d || cap_rows < P->n_rows) return FK_ST_INVALID_PLAN;
    for (int64_t i = 0; i < n_cand; i++) if (!isfinite(cand[i])) return FK_ST_NONFINITE;
    Scratch S; st = alloc_scratch(P, &S);
    if (st) return st;
    st = tax_cfads(P, &S, cand, cf_row, tx_row);
    free_scratch(&S);
    return st;
}
