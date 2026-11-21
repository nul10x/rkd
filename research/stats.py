"""Small stdlib statistics helpers: Kaplan-Meier, log-rank, Mann-Whitney U, Wilson, bootstrap."""
import math
import random


def km(times, events):
    """Kaplan-Meier: returns list of (t, S(t)) at event times."""
    data = sorted(zip(times, events))
    n, s, out, i = len(data), 1.0, [], 0
    while i < len(data):
        t = data[i][0]
        d = sum(1 for tt, e in data if tt == t and e)
        c = sum(1 for tt, e in data if tt == t)
        if d:
            s *= 1 - d / n
            out.append((t, s))
        n -= c
        i += c
    return out


def km_median(times, events):
    for t, s in km(times, events):
        if s <= 0.5:
            return t
    return None  # not reached (more than half censored)


def logrank(t1, e1, t2, e2):
    """Two-group log-rank chi-square (df=1) and p-value."""
    times = sorted({t for t, e in zip(t1 + t2, e1 + e2) if e})
    o_e, var = 0.0, 0.0
    for t in times:
        n1 = sum(1 for x in t1 if x >= t)
        n2 = sum(1 for x in t2 if x >= t)
        d1 = sum(1 for x, e in zip(t1, e1) if x == t and e)
        d2 = sum(1 for x, e in zip(t2, e2) if x == t and e)
        n, d = n1 + n2, d1 + d2
        if n < 2:
            continue
        o_e += d1 - d * n1 / n
        var += d * (n1 / n) * (n2 / n) * (n - d) / (n - 1)
    if var == 0:
        return None, None
    chi2 = o_e * o_e / var
    return chi2, math.erfc(math.sqrt(chi2 / 2))


def mann_whitney(a, b):
    """U for a vs b, two-sided normal-approx p with tie correction. Returns (U, p, AUC=P(a>b))."""
    allv = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, i = {}, 0
    rk = [0.0] * len(allv)
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        for k in range(i, j):
            rk[k] = (i + j + 1) / 2
        i = j
    r1 = sum(r for r, (v, g) in zip(rk, allv) if g == 0)
    n1, n2 = len(a), len(b)
    u = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    ties = {}
    for v, _ in allv:
        ties[v] = ties.get(v, 0) + 1
    tc = sum(t ** 3 - t for t in ties.values())
    sd = math.sqrt(n1 * n2 / 12 * ((n + 1) - tc / (n * (n - 1)))) if n > 1 else 0
    z = (u - n1 * n2 / 2) / sd if sd else 0
    return u, math.erfc(abs(z) / math.sqrt(2)), u / (n1 * n2) if n1 and n2 else None


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def bootstrap(fn, rows, n=2000, seed=1, alpha=0.05):
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        v = fn([rows[rng.randrange(len(rows))] for _ in rows])
        if v is not None:
            vals.append(v)
    if not vals:
        return None, None, 0
    vals.sort()
    return vals[int(alpha / 2 * len(vals))], vals[int((1 - alpha / 2) * len(vals)) - 1], len(vals) / n


def newcombe_diff(k1, n1, k2, n2, z=1.96):
    """Newcombe (1998, method 10) hybrid-score 95% CI for p1 - p2 from two Wilson intervals."""
    if not n1 or not n2:
        return None, None, None
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi
