"""Independent expected-value oracle: Fractions and a unit-by-unit brute force; shares NO code with revenue_reference_core."""
from fractions import Fraction as F


def brute(semantics, years, gen_mwh, cap1, cap2, base, red, merch, start, end, idx_base=None, rate=F(0), frac=F(0)):
    """Allocate energy ONE MWh at a time (gen values are integers).  Returns {year: (m_base, m_red, m_merch, eur)}."""
    annual = semantics.startswith("ANNUAL")
    ceil = semantics.endswith("CEILING")
    hi1 = cap1
    hi2 = cap2 if ceil else cap1 + cap2
    used, res = 0, {}
    for y, g in zip(years, gen_mwh):
        if annual:
            used = 0
        k = F(1) if not (start <= y <= end) else (1 - frac) + frac * (1 + rate) ** (y - idx_base) if frac else F(1)
        b = r = m = 0
        for _ in range(g):
            if start <= y <= end:
                if used < hi1:
                    b += 1
                elif used < hi2:
                    r += 1
                else:
                    m += 1
                used += 1
            else:
                m += 1
        res[y] = (b, r, m, b * base * k + r * red * k + m * merch[y])
    return res
