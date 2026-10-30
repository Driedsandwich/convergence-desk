# Convergence Desk

A zero-configuration, open-source public-market research agent. It detects when
selected publishers converge on a token narrative, checks completed candles on
two venues, and records a complete **practice** position or the failed rules.
No accounts, keys, paid APIs, browser automation, or real orders.

Python 3.10+; runtime dependencies: standard library only.

```sh
python3 -m convergence_desk.cli run --hours 48
# Open the printed runs/<id>/report.html in your own browser.
python3 -m convergence_desk.cli replay runs/<id>/snapshot.json
python3 -m convergence_desk.cli chaos --kill publicnode --hours 48
```

`python` also works where it names Python 3. Exit codes: **0** completed,
**2** completed with degraded sources, **1** failed (including replay mismatch).
A no-trade outcome is valid: the report explains conflicting voices, missing or
contradictory evidence, and risk limits without loosening thresholds.

The default list contains 19 RSS publishers verified fresh on this machine on
2026-10-30, plus Decrypt's public Bluesky feed. Decrypt is one voice across both
channels. Coinbase and Kraken provide hourly candles; Binance and keyless
CoinGecko are fallbacks. PublicNode supplies a short, confirmed USDC/USDT
liquidity sample, which is never treated as a token buy/sell signal.

Use `--voices FILE`, `--rules FILE`, `--risk FILE`, and `--out runs/<id>` to
customize a run. Reusing the same output directory resumes its frozen clock and
safe checkpoints; use a new directory to collect a new live observation.
`CONVERGENCE_KILL_SOURCE=coinbase` also enables deliberate failure.

The append-only `runs/practice_ledger.jsonl` carries open practice positions,
evaluates observable stop/target/time exits on later runs, and feeds reserved
risk and today's gross realized losses into the next decision. It never sends orders.

- [Judge guide, configuration and limits](docs/RUNNING.md)
- [Measured source probe and exclusions](docs/SOURCES_PROBE.md)
- [Recorded test fixture policy](tests/fixtures/recorded/README.md)

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

Run outputs, excerpts, checkpoints and the practice ledger are git-ignored.
Full publisher articles/posts are never persisted. Replay uses saved extraction
features and verifies the complete decision-record hash without network access.

Built for the BLI Legal Tech Hackathon 2 (DoraHacks). Practice research only.
