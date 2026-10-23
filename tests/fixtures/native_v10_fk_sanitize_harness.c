/* Sanitizer / boundary / allocation-failure harness for kernel_v10.c (Linux; driven by tests/test_native_v10_sanitizers.py).
 * Build: gcc -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -DFK_TEST_ALLOC \
 *        -fno-fast-math -ffp-contract=off -I<kernel dir> fk_sanitize_harness.c -lm
 * Modes:  replay <corpus>      every real plan: status + all outputs bit-equal to the release kernel
 *         malformed <corpus>   take the first plan and apply each malformation -> must return a
 *                              non-OK status with no sanitizer diagnostic
 *         alloc <corpus>       for each allocation index k: fail allocation k -> NOMEM, no leak
 */
#include "kernel_v10.c"
#include <stdio.h>
#include <stdint.h>
#include <limits.h>

typedef struct { void *p[256]; int n; } Owned;
static Owned owned;
static void *own(size_t bytes) { void *p = malloc(bytes ? bytes : 1); owned.p[owned.n++] = p; return p; }
static void free_owned(void) { for (int i = 0; i < owned.n; i++) free(owned.p[i]); owned.n = 0; }

static int rd(FILE *f, void *b, size_t n) { return fread(b, 1, n, f) == n; }
static int64_t rq(FILE *f) { int64_t v = 0; rd(f, &v, 8); return v; }
static double rdd(FILE *f) { double v = 0; rd(f, &v, 8); return v; }
static int64_t *rqa(FILE *f) { int64_t n = rq(f); int64_t *a = own(sizeof(int64_t) * (size_t)(n > 0 ? n : 1)); rd(f, a, 8 * (size_t)n); return a; }
static double *rda(FILE *f) { int64_t n = rq(f); double *a = own(sizeof(double) * (size_t)(n > 0 ? n : 1)); rd(f, a, 8 * (size_t)n); return a; }

typedef struct { Plan P; double d0; int64_t st, it; double newD, mad; double *cf, *ncf, *ntx; } Rec;

static int read_rec(FILE *f, Rec *R) {
    char magic[4];
    if (!rd(f, magic, 4)) return 0;
    if (memcmp(magic, "FKV1", 4)) { fprintf(stderr, "bad magic\n"); exit(2); }
    Plan *P = &R->P; memset(P, 0, sizeof *P);
    P->abi_version = rq(f); P->struct_size = rq(f);
    P->n_rows = rq(f); P->n_years = rq(f); P->n_slots = rq(f); P->n_sp = rq(f); P->n_sorted = rq(f);
    P->n_open = rq(f); P->idx_span = rq(f);
    P->row_kind = rqa(f); P->row_slot_start = rqa(f); P->row_slot_count = rqa(f);
    P->slot_pos = rqa(f); P->slot_frac = rda(f); P->y_ebitda = rda(f); P->y_dep = rda(f);
    P->year_key = rqa(f); P->payment_idx = rqa(f);
    P->timing_payment = rq(f); P->lag = rq(f); P->max_idx = rq(f);
    P->sp_start = rqa(f); P->sp_count = rqa(f); P->sp_k = rqa(f); P->sp_nf = rda(f);
    P->idx_min = rq(f); P->idx_to_sorted = rqa(f); P->row_sorted = rqa(f);
    P->atad_enabled = rq(f); P->atad_limit = rdd(f); P->atad_threshold = rdd(f);
    P->loss_gate = rq(f); P->corporate_rate = rdd(f); P->lcf_years = rq(f);
    P->open_last = rqa(f); P->open_amount = rda(f);
    P->row_cand = rqa(f); P->row_other = rda(f); P->row_elig = rda(f); P->row_nd = rda(f);
    P->row_static_gross = rda(f); P->row_static_nd = rda(f); P->row_reint = rda(f); P->row_fin = rda(f);
    P->row_ebitda = rda(f);
    P->n_d = rq(f); P->rates = rda(f); P->dfs = rda(f); P->dscr = rda(f); P->avail = rda(f);
    P->in_rep = rqa(f); P->d_row = rqa(f);
    P->alpha = rdd(f); P->max_iter = rq(f); P->abs_tol = rdd(f); P->rel_tol = rdd(f); P->max_fin_iter = rq(f);
    P->struct_size = (int64_t)sizeof(Plan);          /* layout of this build */
    R->d0 = rdd(f);
    R->st = rq(f); R->it = rq(f); R->newD = rdd(f); R->mad = rdd(f);
    R->cf = own(8 * (size_t)P->n_d); R->ncf = own(8 * (size_t)P->n_rows); R->ntx = own(8 * (size_t)P->n_rows);
    rd(f, R->cf, 8 * (size_t)P->n_d); rd(f, R->ncf, 8 * (size_t)P->n_rows); rd(f, R->ntx, 8 * (size_t)P->n_rows);
    return 1;
}

static int run_solve(const Plan *P, double d0, SolveOut *o, double **cf, double **ncf, double **ntx) {
    *cf = malloc(8 * (size_t)(P->n_d > 0 ? P->n_d : 1)); *ncf = malloc(8 * (size_t)(P->n_rows > 0 ? P->n_rows : 1));
    *ntx = malloc(8 * (size_t)(P->n_rows > 0 ? P->n_rows : 1));
    memset(o, 0, sizeof *o);
    return fk_solve_dscr(P, d0, o, *cf, P->n_d, *ncf, *ntx, P->n_rows);
}

static int bits_eq(const double *a, const double *b, int64_t n) { return memcmp(a, b, 8 * (size_t)n) == 0; }

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: replay|malformed|alloc corpus\n"); return 2; }
    FILE *f = fopen(argv[2], "rb");
    if (!f) { perror("corpus"); return 2; }
    Rec R; long n = 0, ok = 0, bad = 0;
    if (!strcmp(argv[1], "replay")) {
        while (read_rec(f, &R)) {
            SolveOut o; double *cf, *ncf, *ntx;
            int st = run_solve(&R.P, R.d0, &o, &cf, &ncf, &ntx);
            int eq = st == R.st;
            if (eq && st == 0) eq = o.iteration == R.it && memcmp(&o.new_D, &R.newD, 8) == 0 &&
                                    memcmp(&o.max_abs_diff, &R.mad, 8) == 0 && bits_eq(cf, R.cf, R.P.n_d) &&
                                    bits_eq(ncf, R.ncf, R.P.n_rows) && bits_eq(ntx, R.ntx, R.P.n_rows);
            /* also exercise the standalone tax entry */
            double *c2 = malloc(8 * (size_t)R.P.n_rows), *t2 = malloc(8 * (size_t)R.P.n_rows), *cand = calloc((size_t)R.P.n_d, 8);
            fk_tax(&R.P, cand, R.P.n_d, c2, t2, R.P.n_rows);
            free(c2); free(t2); free(cand); free(cf); free(ncf); free(ntx);
            n++; if (eq) ok++; else bad++;
            free_owned();
        }
        printf("{\"mode\":\"replay\",\"records\":%ld,\"bit_equal\":%ld,\"mismatch\":%ld}\n", n, ok, bad);
        return bad ? 1 : 0;
    }
    if (!read_rec(f, &R)) return 2;
    if (!strcmp(argv[1], "malformed")) {
        const char *names[] = {"bad_row_cand", "bad_row_sorted", "bad_sp_k", "bad_d_row", "n_open_INT64_MAX",
            "lcf_years_INT64_MAX", "lag_INT64_MAX", "slot_start_overflow", "slot_count_zero", "slot_pos_oob",
            "sp_range_overflow", "idx_to_sorted_oob", "null_pointer", "abi_version", "struct_size", "n_rows_negative",
            "n_rows_huge", "idx_span_huge", "cap_rows_too_small", "d_row_not_bijective", "row_kind_invalid",
            "year_key_INT64_MIN_lcf", "nonfinite_rate", "max_iter_huge"};
        int nn = (int)(sizeof(names) / sizeof(names[0]));
        int all_rejected = 1;
        printf("[");
        for (int k = 0; k < nn; k++) {
            Plan P = R.P;
            int64_t mx = P.n_rows; int64_t lens[] = {P.n_sp, P.idx_span, P.n_d, P.n_years, P.n_sorted, P.n_slots};
            for (int q = 0; q < 6; q++) if (lens[q] > mx) mx = lens[q];
            int64_t *tmp_i = malloc(sizeof(int64_t) * (size_t)(mx + 8));
            double *tmp_d = malloc(sizeof(double) * (size_t)(P.n_d + 8));
            int64_t cap_rows = P.n_rows;
            switch (k) {
            case 0: memcpy(tmp_i, P.row_cand, 8 * (size_t)P.n_rows); tmp_i[0] = P.n_d + 1000; P.row_cand = tmp_i; break;
            case 1: memcpy(tmp_i, P.row_sorted, 8 * (size_t)P.n_rows); tmp_i[0] = P.n_sorted + 1000; P.row_sorted = tmp_i; break;
            case 2: if (P.n_sp) { memcpy(tmp_i, P.sp_k, 8 * (size_t)P.n_sp); tmp_i[0] = P.n_years + 1000; P.sp_k = tmp_i; }
                    else { P.n_sp = 1; tmp_i[0] = 1000000; P.sp_k = tmp_i; tmp_d[0] = 1.0; P.sp_nf = tmp_d; } break;
            case 3: memcpy(tmp_i, P.d_row, 8 * (size_t)P.n_d); tmp_i[0] = P.n_rows + 1000; P.d_row = tmp_i; break;
            case 4: P.n_open = INT64_MAX; break;
            case 5: P.lcf_years = INT64_MAX; break;
            case 6: P.lag = INT64_MAX; break;
            case 7: memcpy(tmp_i, P.row_slot_start, 8 * (size_t)P.n_rows); tmp_i[0] = INT64_MAX - 1; P.row_slot_start = tmp_i; break;
            case 8: memcpy(tmp_i, P.row_slot_count, 8 * (size_t)P.n_rows); tmp_i[0] = 0; P.row_slot_count = tmp_i; break;
            case 9: memcpy(tmp_i, P.slot_pos, 8 * (size_t)(P.n_slots < P.n_rows ? P.n_slots : P.n_rows)); tmp_i[0] = -5; P.slot_pos = tmp_i; P.n_slots = P.n_slots < P.n_rows ? P.n_slots : P.n_rows; break;
            case 10: memcpy(tmp_i, P.sp_start, 8 * (size_t)P.n_sorted); tmp_i[0] = INT64_MAX; P.sp_start = tmp_i; break;
            case 11: memcpy(tmp_i, P.idx_to_sorted, 8 * (size_t)P.idx_span); tmp_i[0] = P.n_sorted + 7; P.idx_to_sorted = tmp_i; break;
            case 12: P.row_other = NULL; break;
            case 13: P.abi_version = 1; break;
            case 14: P.struct_size = 8; break;
            case 15: P.n_rows = -1; break;
            case 16: P.n_rows = INT64_MAX; break;
            case 17: P.idx_span = INT64_MAX; break;
            case 18: cap_rows = P.n_rows - 1; break;
            case 19: memcpy(tmp_i, P.d_row, 8 * (size_t)P.n_d); if (P.n_d > 1) tmp_i[1] = tmp_i[0]; P.d_row = tmp_i; break;
            case 20: memcpy(tmp_i, P.row_kind, 8 * (size_t)P.n_rows); tmp_i[0] = 7; P.row_kind = tmp_i; break;
            case 21: memcpy(tmp_i, P.year_key, 8 * (size_t)P.n_years); tmp_i[0] = INT64_MAX; P.year_key = tmp_i; P.lcf_years = 5; break;
            case 22: memcpy(tmp_d, P.rates, 8 * (size_t)P.n_d); tmp_d[0] = NAN; P.rates = tmp_d; break;
            case 23: P.max_iter = INT64_MAX; break;
            }
            SolveOut o; double cf[4096], ncf[4096], ntx[4096];
            int st = fk_solve_dscr(&P, R.d0, &o, cf, P.n_d > 0 && P.n_d < 4096 ? P.n_d : 0, ncf, ntx, cap_rows < 4096 ? cap_rows : 0);
            int st2 = fk_tax(&P, cf, P.n_d, ncf, ntx, cap_rows < 4096 ? cap_rows : 0);
            int rejected = st != 0 && st2 != 0;
            if (!rejected) all_rejected = 0;
            printf("%s{\"case\":\"%s\",\"solve_status\":%d,\"tax_status\":%d,\"rejected\":%s}", k ? "," : "", names[k], st, st2, rejected ? "true" : "false");
            free(tmp_i); free(tmp_d);
        }
        printf("]\n");
        free_owned();
        return all_rejected ? 0 : 1;
    }
    if (!strcmp(argv[1], "alloc")) {
        int saw_nomem = 0, saw_ok = 0, wrong = 0;
        for (long k = 0; k < 64; k++) {
            fk_test_set_alloc_budget(k);
            SolveOut o; double *cf, *ncf, *ntx;
            int st = run_solve(&R.P, R.d0, &o, &cf, &ncf, &ntx);
            free(cf); free(ncf); free(ntx);
            if (st == FK_ST_NOMEM) saw_nomem++;
            else if (st == R.st) saw_ok++;
            else wrong++;
        }
        fk_test_set_alloc_budget(-1);
        free_owned();
        printf("{\"mode\":\"alloc\",\"injections\":64,\"nomem\":%d,\"completed_equal\":%d,\"wrong_status\":%d}\n", saw_nomem, saw_ok, wrong);
        return wrong ? 1 : 0;
    }
    if (!strcmp(argv[1], "mutate")) {
        /* structure-aware random mutation of real plans: any status is acceptable, UB/OOB is not */
        uint64_t seed = 0x9E3779B97F4A7C15ull; long runs = 0, ok_status = 0, rejected = 0;
        free_owned(); rewind(f);
        while (read_rec(f, &R)) {
            for (int m = 0; m < 40; m++) {
                Plan P = R.P;
                seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17;
                int64_t *ints[] = {(int64_t *)P.row_kind, (int64_t *)P.row_slot_start, (int64_t *)P.row_slot_count, (int64_t *)P.slot_pos,
                                   (int64_t *)P.year_key, (int64_t *)P.payment_idx, (int64_t *)P.sp_start, (int64_t *)P.sp_count,
                                   (int64_t *)P.idx_to_sorted, (int64_t *)P.row_sorted, (int64_t *)P.row_cand, (int64_t *)P.in_rep, (int64_t *)P.d_row};
                int64_t lens[] = {P.n_rows, P.n_rows, P.n_rows, P.n_slots, P.n_years, P.n_years, P.n_sorted, P.n_sorted,
                                  P.idx_span, P.n_rows, P.n_rows, P.n_d, P.n_d};
                int which = (int)(seed % 13);
                int64_t len = lens[which];
                int64_t *copy = malloc(8 * (size_t)(len > 0 ? len : 1));
                memcpy(copy, ints[which], 8 * (size_t)len);
                int64_t vals[] = {-1, 0, 1, len, len + 1, INT64_MAX, INT64_MIN, (int64_t)(seed >> 3), -(int64_t)(seed >> 5)};
                copy[(seed >> 8) % (uint64_t)(len > 0 ? len : 1)] = vals[(seed >> 16) % 9];
                switch (which) {
                case 0: P.row_kind = copy; break; case 1: P.row_slot_start = copy; break; case 2: P.row_slot_count = copy; break;
                case 3: P.slot_pos = copy; break; case 4: P.year_key = copy; break; case 5: P.payment_idx = copy; break;
                case 6: P.sp_start = copy; break; case 7: P.sp_count = copy; break; case 8: P.idx_to_sorted = copy; break;
                case 9: P.row_sorted = copy; break; case 10: P.row_cand = copy; break; case 11: P.in_rep = copy; break;
                default: P.d_row = copy; break;
                }
                int64_t scal = (seed >> 20) % 6;
                if (scal == 0) P.lag = (int64_t)(seed >> 1); else if (scal == 1) P.lcf_years = -(int64_t)(seed >> 2);
                else if (scal == 2) P.idx_min = (int64_t)(seed >> 4);
                SolveOut o; double *cf, *ncf, *ntx;
                int st = run_solve(&P, R.d0, &o, &cf, &ncf, &ntx);
                free(cf); free(ncf); free(ntx); free(copy);
                runs++; if (st == 0) ok_status++; else rejected++;
            }
            free_owned();
        }
        printf("{\"mode\":\"mutate\",\"runs\":%ld,\"ok_status\":%ld,\"non_ok_status\":%ld}\n", runs, ok_status, rejected);
        return 0;
    }
    return 2;
}
