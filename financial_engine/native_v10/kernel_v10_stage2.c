/*
 * FINCO V10 — Stage 2 EXPERIMENTAL kernel (research; default disabled; separate library so the
 * Stage 1 artifact is unchanged).
 *
 * Exact-replay transliteration of the operating-period roll of
 *   financial_engine.shl.production.compute_shareholder_loan_schedules
 *   financial_engine.shl.production._ShlOperatingChain.evaluate/advance
 *   financial_engine.shl.waterfall.compute_shl_waterfall_period
 * for the admitted configuration (construction-prefix axis, PERIOD_AXIS_ACTUAL_YEAR day count,
 * BULLET or CASH_SWEEP). Construction rows and the operating chain's opening balance are NOT
 * computed here: they are cash-independent and are taken from a canonical Python evaluation of the
 * same function (the "template"), so no construction formula is duplicated.
 *
 * Arithmetic: same operations, same order, IEEE binary64, -ffp-contract=off, no fast-math.
 * Python min(a,b) == (b < a ? b : a); max(a,b) == (b > a ? b : a).
 * Any condition under which the canonical code would raise returns FK2_DECLINE (the caller then
 * replays the canonical function, which raises its own exception). Never aborts, never allocates.
 */
#include <math.h>
#include <stddef.h>
#include <stdint.h>

#define FK2_ABI 20001
#define FK2_OK 0
#define FK2_DECLINE 1
#define FK2_INVALID_PLAN 5
#define FK2_ABI_MISMATCH 6
#define FK2_MODE_BULLET 1
#define FK2_MODE_SWEEP 2
#ifndef FK_BUILD_ID
#define FK_BUILD_ID "unset"
#endif

typedef struct {
    int64_t abi_version, struct_size;
    int64_t n, n_con;                 /* periods; construction prefix length (0 <= n_con <= n) */
    const int64_t *period_index;      /* n */
    const double *dcf;                /* n (operating rows used) */
    const double *t_open, *t_draw, *t_gross, *t_cint, *t_pik, *t_prin, *t_serv, *t_close; /* n_con */
    double opening0, rate, conv_tol;
    int64_t mode, repayment_start, maturity_index;
} ShlPlan;

typedef struct {
    double *open, *draw, *gross, *cint, *pik, *prin, *serv, *close, *cavail, *crem;  /* n each */
    int64_t shortfall_count, shortfall_period;
    double shortfall_closing;
} ShlOut;

int fk2_abi_version(void) { return FK2_ABI; }
int64_t fk2_plan_size(void) { return (int64_t)sizeof(ShlPlan); }
int64_t fk2_out_size(void) { return (int64_t)sizeof(ShlOut); }
const char *fk2_build_id(void) { return FK_BUILD_ID; }

static double py_min(double a, double b) { return (b < a) ? b : a; }
static double py_max(double a, double b) { return (b > a) ? b : a; }

/* compute_shl_waterfall_period argument checks (raise -> decline) */
static int wf_args_ok(double opening, double rate, double dcf, double cash) {
    if (!isfinite(opening) || !isfinite(rate) || !isfinite(dcf) || !isfinite(cash)) return 0;
    if (opening < 0.0 || rate < 0.0 || dcf <= 0.0 || cash < 0.0) return 0;
    return 1;
}

static int plan_ok(const ShlPlan *p, const ShlOut *o, int64_t n_cash, int64_t cap) {
    if (!p || !o) return 0;
    if (p->n < 0 || p->n_con < 0 || p->n_con > p->n || p->n != n_cash || p->n > cap) return 0;
    if (p->n > 0 && (!p->period_index || !p->dcf)) return 0;
    if (p->n_con > 0 && (!p->t_open || !p->t_draw || !p->t_gross || !p->t_cint || !p->t_pik ||
                         !p->t_prin || !p->t_serv || !p->t_close)) return 0;
    if (p->n > 0 && (!o->open || !o->draw || !o->gross || !o->cint || !o->pik || !o->prin ||
                     !o->serv || !o->close || !o->cavail || !o->crem)) return 0;
    if (p->mode != FK2_MODE_BULLET && p->mode != FK2_MODE_SWEEP) return 0;
    return 1;
}

/* enforce: 0 = no maturity residual check; 1 = check, record (provisional ledger); 2 = check, raise */
int fk2_shl_schedule(const ShlPlan *p, const double *cash, int64_t n_cash, ShlOut *o, int64_t cap,
                     int64_t enforce) {
    if (!p || p->abi_version != FK2_ABI || p->struct_size != (int64_t)sizeof(ShlPlan)) return FK2_ABI_MISMATCH;
    if (!plan_ok(p, o, n_cash, cap) || (p->n > 0 && !cash) || enforce < 0 || enforce > 2) return FK2_INVALID_PLAN;
    const double thr = p->conv_tol + 1e-9;
    double opening = p->opening0;
    int have_residual = 0;
    double residual = 0.0;
    o->shortfall_count = 0; o->shortfall_period = 0; o->shortfall_closing = 0.0;
    for (int64_t j = 0; j < p->n; ++j) {
        const double raw = cash[j];
        if (!isfinite(raw) || raw < 0.0) return FK2_DECLINE;     /* _check_finite / raw_cash < 0 */
        const int64_t idx = p->period_index[j];
        double op, dr, gr, ci, pk, pr, sv, cl;
        if (j < p->n_con) {
            op = p->t_open[j]; dr = p->t_draw[j]; gr = p->t_gross[j]; ci = p->t_cint[j];
            pk = p->t_pik[j]; pr = p->t_prin[j]; sv = p->t_serv[j]; cl = p->t_close[j];
        } else if (have_residual) {
            op = residual; dr = 0.0; gr = 0.0; ci = 0.0; pk = 0.0; pr = 0.0; sv = 0.0; cl = residual;
        } else {
            const double dcf = p->dcf[j];
            double eligible = raw;
            const int is_mat = (idx == p->maturity_index);
            if (p->mode == FK2_MODE_SWEEP && idx < p->repayment_start) {
                /* preliminary = chain.evaluate(...): evaluate checks + waterfall checks */
                if (!wf_args_ok(opening, p->rate, dcf, raw)) return FK2_DECLINE;
                const double pre_gross = opening * p->rate * dcf;
                eligible = py_min(raw, pre_gross);
            }
            /* chain.advance(op_input): evaluate checks (cash finite/>=0) + waterfall checks */
            if (!wf_args_ok(opening, p->rate, dcf, eligible)) return FK2_DECLINE;
            const double gross = opening * p->rate * dcf;
            const double cash_interest = py_min(eligible, gross);
            const double capitalised = gross - cash_interest;
            const double remaining = eligible - cash_interest;
            const double outstanding = opening + capitalised;
            double principal;
            if (p->mode == FK2_MODE_BULLET) principal = is_mat ? py_min(remaining, outstanding) : 0.0;
            else principal = py_max(0.0, py_min(remaining, outstanding));
            const double closing = py_max(outstanding - principal, 0.0);
            op = opening; dr = 0.0; gr = gross; ci = cash_interest; pk = capitalised; pr = principal;
            sv = cash_interest + principal; cl = closing;
            opening = closing;
            if (p->mode == FK2_MODE_BULLET && is_mat && closing > thr) { have_residual = 1; residual = closing; }
        }
        if (enforce && p->mode == FK2_MODE_SWEEP && idx == p->maturity_index && cl > thr) {
            if (enforce == 2) return FK2_DECLINE;                    /* canonical raises */
            if (o->shortfall_count) return FK2_DECLINE;              /* >1 record: let canonical do it */
            o->shortfall_count = 1; o->shortfall_period = idx; o->shortfall_closing = cl;
        }
        o->open[j] = op; o->draw[j] = dr; o->gross[j] = gr; o->cint[j] = ci; o->pik[j] = pk;
        o->prin[j] = pr; o->serv[j] = sv; o->close[j] = cl; o->cavail[j] = raw; o->crem[j] = raw - sv;
    }
    return FK2_OK;
}
