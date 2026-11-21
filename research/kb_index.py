"""Generate docs/knowledge/INDEX.md: every Logbook record grouped by research division, read-only.

The Logbook stays the source of truth; this file is a browsable map for agents. Re-run after each batch:
  python3 -m research.kb_index
Divisions come from 'division:<name>' tags; untagged records are grouped by category.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIVISIONS = [
    ("onchain", "1. Blockchain and on-chain analytics"), ("ta", "2. Technical analysis and market structure"),
    ("social", "3. Social intelligence and narratives"), ("tokenomics", "4. Tokenomics and liquidity"),
    ("security", "5. Contract security and scam detection"), ("psychology", "6. Trading psychology"),
    ("cycles", "7. Market cycles and history"), ("strategies", "8. Strategies and statistics"),
    ("launches", "9. DEXs, launchpads and launches"), ("mev", "10. MEV, sandwiches, snipers, tx mechanics"),
]
PROJECTS = [
    ("success", "Traits of successful memecoins"), ("pre-pump", "What precedes big moves"),
    ("wash-trading", "Organic vs artificial volume"), ("narrative", "Narrative identification"),
    ("insider", "Insider wallet behaviour"), ("liquidity", "Liquidity changes vs price"),
    ("rug", "Rug-pull precursors"), ("costs", "Strategies vs fees and slippage"),
]


def cli(*args):
    p = subprocess.run([sys.executable, "-m", "ecosystem.cli", *args], capture_output=True, text=True, cwd=ROOT, check=True)
    return json.loads(p.stdout)


def main():
    rows = [cli("get", r["id"]) for r in cli("search", "", "--limit", "1000")]
    rows.sort(key=lambda r: r["id"])

    def line(r):
        conf = "-" if r.get("confidence") is None else "{:.2f}".format(r["confidence"])
        return "| {} | {} | {} | {} | {} | {} |".format(r["id"], r["kind"], r["status"], conf, (r.get("discovered_at") or "")[:10],
                                                       r["title"].replace("|", "/"))
    head = "| id | kind | status | conf | date | title |\n|---|---|---|---|---|---|"
    out = ["# RKD memecoin knowledge index", "",
           "Generated from the Logbook by `python3 -m research.kb_index`. Do not edit by hand. Read a record with",
           "`python3 -m ecosystem.cli get KR-xxxxxx`; search with `python3 -m ecosystem.cli search \"<words>\"`.",
           "Status ladder: unverified < hypothesis < under_investigation < historically_supported < validated (or rejected).",
           "", "Records: {}".format(len(rows)), ""]
    tags = {r["id"]: set((r.get("tags") or "").split()) for r in rows}
    used = set()
    for key, name in DIVISIONS:
        sel = [r for r in rows if "division:" + key in tags[r["id"]]]
        used |= {r["id"] for r in sel}
        out += ["## " + name, "", head] + [line(r) for r in sel] + (["| - | | | | | nothing yet |"] if not sel else []) + [""]
    out += ["## Standing projects (keyword match on tags)", ""]
    for key, name in PROJECTS:
        sel = [r["id"] for r in rows if any(key in t for t in tags[r["id"]])]
        out.append("- **{}**: {}".format(name, ", ".join(sel) if sel else "nothing yet"))
    out += ["", "## Studies, plans and lessons not tagged with a division", "", head]
    out += [line(r) for r in rows if r["id"] not in used]
    path = os.path.join(ROOT, "docs", "knowledge", "INDEX.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(path, len(rows))


if __name__ == "__main__":
    main()
