"""Study 4 collector (plan: Logbook KR-000039). One pre-launch history page per deployer and per block-0 buyer
of the study-3 part-(a) cohort. Cached by collectors/client.py, so re-runs only make missing calls.

  python3 -m collectors.study4 DAY [N_LAUNCHES]   # N_LAUNCHES limits the run (pilot)
Env: RKD_USAGE=data/raw/usage_study4.json RKD_CALL_BUDGET=2000 RKD_LOGBOOK_COUNT=1 RKD_TASK=T-000007 HELIUS_API_KEY=...
"""
import sys

from collectors import client
from collectors import study3 as S3
from research import study3_parse as P3

DAY = 86400


def wallet_params(w, t0):
    return [w, dict(S3.FULL, sortOrder="desc", limit=100, filters={
        "blockTime": {"gte": t0 - 7 * DAY, "lte": t0}, "status": "succeeded"})]


def cohort(day, mint_page):
    """[(launch, {buyer: raw tokens})] for study-3 part (a) launches with block-0 buyers, ordered by mint.
    mint_page(launch) returns the cached study-3 first-hour mint page result, or None."""
    L, grads, non, _ = S3.sample(day)
    out = []
    for m in sorted(grads + non):
        pg = mint_page(L[m])
        if pg is None:
            continue
        buyers = P3.block0_buyers(pg["data"], L[m])
        if buyers:
            out.append((dict(L[m], graduate=m in grads), buyers))
    return out


def main(day, n=None):
    c = cohort(day, S3.mint_page)  # cache hits only: study 3 fetched every page
    if n:
        c = c[:n]
    print(day, "launches", len(c), "buyers", sum(len(b) for _, b in c), "calls", client.calls_used(), flush=True)
    for l, _ in c:
        client.helius_rpc("getTransactionsForAddress", wallet_params(l["deployer"], l["t0"]))
    print("devs done, calls", client.calls_used(), flush=True)
    for i, (l, buyers) in enumerate(c):
        for b in sorted(buyers):
            client.helius_rpc("getTransactionsForAddress", wallet_params(b, l["t0"]))
        if i % 20 == 0:
            print("buyers", i, "calls", client.calls_used(), flush=True)
    print("done, calls", client.calls_used())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
