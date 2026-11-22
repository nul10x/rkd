"""Study 5: primary vs holdout comparison and weekly breakdown (exploratory). Offline; reads the cached build.
Usage: python3 -m research.study5_compare
"""
import json

from collectors import study5 as S
from research.stats import newcombe_diff, wilson


def seen(name):
    rows, _ = S.build_cpmm(name, S.cache)
    return [r for r in rows if not r["launchpad"] and r.get("new_token") and "freeze_used" in r]


def main():
    p, h = seen("primary"), seen("holdout")
    kp, kh = sum(r["freeze_used"] for r in p), sum(r["freeze_used"] for r in h)
    out = {"Q5b_primary": [kp, len(p)], "Q5b_holdout": [kh, len(h)],
           "diff_primary_minus_holdout_newcombe": newcombe_diff(kp, len(p), kh, len(h))}
    wk = {}
    for r in p + h:
        w = (r["day"] - S.day_start("2026-10-01")) // (7 * S.DAY)
        a = wk.setdefault(int(w), [0, 0])
        a[0] += r["freeze_used"]
        a[1] += 1
    out["weekly_from_2026-10-01"] = {str(w): {"k": k, "n": n, "p": round(k / n, 4), "ci95": [round(x, 4) for x in wilson(k, n)]}
                                     for w, (k, n) in sorted(wk.items())}
    # Serial operators: freeze authorities and pool creators behind the freeze_used tokens.
    used = [r for r in p + h if r["freeze_used"]]
    auths, creators = {}, {}
    for r in used:
        auths[r["freeze_auth"]] = auths.get(r["freeze_auth"], 0) + 1
        creators[r["pool_creator"]] = creators.get(r["pool_creator"], 0) + 1
    out["operators"] = {"freeze_used_tokens": len(used), "distinct_freeze_authorities": len(auths),
                        "distinct_pool_creators": len(creators),
                        "top_authority_token_counts": sorted(auths.values(), reverse=True)[:5],
                        "retained_tokens_by_authority_count": len({r["freeze_auth"] for r in p + h})}
    # Authority-level rate: share of distinct authorities (any token) that froze holders at least once.
    by = {}
    for r in p + h:
        by[r["freeze_auth"]] = by.get(r["freeze_auth"], False) or r["freeze_used"]
    k = sum(by.values())
    out["authority_level_freeze_used"] = {"k": k, "n": len(by), "p": round(k / len(by), 4),
                                          "ci95": [round(x, 4) for x in wilson(k, len(by))]}
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
