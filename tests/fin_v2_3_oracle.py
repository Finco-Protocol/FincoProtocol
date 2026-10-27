"""Independent Decimal oracles: no production discount, return or coverage helper."""
from datetime import date
from decimal import Decimal, localcontext


def dec(x):
    return Decimal(str(x))


def npv(dates, amounts, rate, observation, periodic=False):
    with localcontext() as ctx:
        ctx.prec = 50
        base = Decimal(1) + dec(rate)
        total = Decimal(0)
        for n, (d, amount) in enumerate(zip(dates, amounts), 1):
            exponent = dec(n) if periodic else dec((d - observation).days) / Decimal(365)
            total += dec(amount) / (base ** exponent)
        return +total


def xirr(dates, amounts):
    if not any(x < 0 for x in amounts) or not any(x > 0 for x in amounts):
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        t = [dec((d - dates[0]).days) / Decimal(365) for d in dates]
        cash = [dec(x) for x in amounts]
        def f(r):
            log = (Decimal(1) + r).ln()
            return sum(a * (-year * log).exp() for a, year in zip(cash, t))
        lo, hi = Decimal('-.999'), Decimal(1)
        while f(lo) * f(hi) > 0 and hi < Decimal(1000000):
            hi *= 2
        if f(lo) * f(hi) > 0:
            return None
        flo = f(lo)
        for _ in range(180):
            mid = (lo + hi) / 2
            fm = f(mid)
            if fm * flo > 0:
                lo, flo = mid, fm
            else:
                hi = mid
            if hi - lo < Decimal('1e-30'):
                break
        return +(lo + hi) / 2


def float_leaves(value, path="", out=None):
    import dataclasses
    out = {} if out is None else out
    if isinstance(value, float):
        out[path] = value.hex()
    elif dataclasses.is_dataclass(value):
        for f in dataclasses.fields(value):
            float_leaves(getattr(value, f.name), path + '.' + f.name, out)
    elif isinstance(value, dict):
        for k, v in value.items():
            float_leaves(v, path + '.' + str(k), out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            float_leaves(v, f'{path}[{i}]', out)
    elif hasattr(value, 'tolist'):
        float_leaves(value.tolist(), path, out)
    return out
