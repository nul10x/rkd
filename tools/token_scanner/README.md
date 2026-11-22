# token_scanner

Version 0.1.0 · based on Logbook finding KR-000038 · status of finding at build time: <fill in>

## Objective
Report a Solana token's market, holder and mint-permission facts with timestamps, plus Pump.fun block-0 risk context, for a Discord /scan command

## Requirements
- Input: <what, from where, read-only>
- Output: deterministic JSON/CSV including finding id and tool version
- Budget: <max API calls per run>; Python 3.8+ stdlib; macOS/Windows first, Termux-portable; < 200 MB RSS; one-shot run, no daemon of its own

## Architecture
- `token_scanner.py`: pure logic (no network)
- `cli.py`: argument parsing, I/O, calls `collectors/client.py` for any network access
- `tests/`: unit tests, one offline end-to-end test, one failure-path test

## Implementation plan
1. <step>

## Testing
`python3 -m unittest discover -s . -t . -v` from the repo root.
Measured run: <wall time>, <peak RSS>, on <machine>, <date>.

## Known limitations
- <what it cannot detect, data gaps, the finding's own limitations>

## Version history
- 0.1.0 (2026-11-22): scaffold created.
