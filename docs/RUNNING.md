# Run and inspect in a few minutes

From the repository root:

```sh
python3 -m convergence_desk.cli run --hours 48
python3 -m convergence_desk.cli replay runs/<printed-id>/snapshot.json
```

No installation is required for runtime. The first live run on this machine took
roughly two minutes, including source fetching and counterfactuals. Source latency
and retries can change this. Exit 2 still produces a complete report. The original
90 engine tests remain unchanged; additional adapter/integration tests use recordings.

The report is one offline HTML file with inline CSS and printable tables. It shows
practice entry/size/exits, extraction traces, publisher quorum, per-venue return and
volume, the cross-venue gate, risk rules, interventions, rejected token/direction
candidates, source health, HTTP/content hashes and replay instructions.

## Configuration

Copy the files in `convergence_desk/config/` and pass their paths:

```sh
python3 -m convergence_desk.cli run --hours 48 \
  --voices my_voices.json --rules my_rules.json --risk my_risk.json
```

A voice entry has `voice_id`, `label`, `trust_weight` (0–1), plus `rss` (URL),
`bluesky` (public author handle), or both. Put both channels of one publisher in
**one entry**. Up to 20 distinct publishers are allowed; frequency never increases
a publisher's vote. Quorum does not shrink when a source fails. Trust weights
are configuration judgments, not estimated probabilities.

`--hours` overrides the rules' narrative/return window (1–240 hours). The source
rules add `cross_venue_max_spread` (default 0.02), `chain_blocks` (20),
`chain_chunk_size` (10), `chain_confirmations` (12), and
`large_transfer_threshold` (1,000,000 token units, strict greater-than).
USDC/USDT are counted separately; totals are token units, not a guaranteed USD valuation.

## Privacy and deterministic replay

RSS titles and feed summaries and original Bluesky text are processed only in
memory. Full articles are not downloaded. Live output posts include URI, author,
created time, normalized content SHA-256, title SHA-256, extracted numeric features
and rule traces, and an excerpt no longer than 140 characters. There is no full
text field. HTTP hashes refer to original response bytes; item hashes refer to
normalized item content. Market bars and retained on-chain events have their own
provenance. Failed requests record status/error without response bodies.

The integration calls the existing core's extraction, convergence, evidence and
decision functions. Its small runtime layer restores saved features and adds a
two-venue check before risk allocation; counterfactuals rerun that entire path.
No files in `convergence_desk/core/` were modified. The CLI snapshot format is
versioned separately from the core's full-text test snapshot format. A replay
verifies saved feature decisions; it cannot re-extract discarded text or prove
that a publisher response was authentic merely from its hash.

`record.json` includes the snapshot hash and decision hash. The latter covers the
whole record except its own hash field, including health and provenance. Snapshot
hashing excludes only `expected_decision_hash`, avoiding a circular hash.

## Degraded operation and resume

```sh
python3 -m convergence_desk.cli chaos --kill publicnode
CONVERGENCE_KILL_SOURCE=coinbase python3 -m convergence_desk.cli run
```

Source IDs: `coinbase`, `kraken`, `binance`, `coingecko`, `publicnode`, `rss`,
`bluesky`, or a specific feed such as `rss:coindesk`. Run with a new output folder
for each failure scenario. Successful parsed responses are checkpointed without
full publisher text. Reusing `--out` with the same configuration resumes the
original observation time; completed runs return their recorded result. Changes
to configuration require a new directory. Retry respects Retry-After and uses a
per-source circuit breaker. A Retry-After over 15 seconds defers that source for
its requested interval while the rest of the run continues. There is no background
polling or order execution.

Coinbase's TRX-USD product returned 404 in the live run; that is an individual
product failure, not a claim that the entire venue was unavailable. Kraken plus
Binance supplied that cross-check, while the health record and exit 2 retained
the original failure. CoinGecko's keyless OHLC has no per-bar volume and is used
only for fallback price context; it cannot itself provide volume confirmation.

## Practice ledger semantics

`runs/practice_ledger.jsonl` appends idempotent open/close events. `--ledger FILE`
selects an isolated practice ledger. Later runs load existing positions, evaluate
completed hourly bars, reserve open stop risk, enforce open-position/exposure
limits and account for today's gross realized losses in UTC. Stop and target in
the same bar are resolved stop-first. Adverse opening gaps fill at the opening
price; this can exceed the planned stop risk. Time exits use an observable bar
open/close, so this is a coarse practice simulation, without fees or slippage.

The first partial entry hour is excluded because its pre-entry extremes cannot be
attributed to the position. A later gap in available history defers closure and
keeps risk reserved, with a health note. If no later bar exists, the position stays
open rather than inventing an exit. The ledger and checkpoints are single-writer
files: use separate `--ledger` and `--out` paths for concurrent processes.

## Coverage limits

Feeds expose finite history. `--hours 48` filters available posts; it does not
promise a complete 48-hour archive. Bluesky pagination stops at five pages (500
feed entries), and reposts are excluded. Source availability/freshness was measured
from this machine only. Telegram is excluded for the recorded content-licensing
restriction, Reddit for HTTP 403. Reuse rights for RSS/Bluesky were not checked.

The explicit market symbol set is in `sources/market.py`; other mentioned symbols
remain in the rejection ledger with missing evidence. Cross-venue agreement
requires aligned window return signs and closes within the configured spread at
a common completed timestamp; it is not a guarantee of price correctness. The
primary venue alone supplies volume z-score; volumes are never averaged between
venues. On-chain logs cover only the recorded recent block window, not the entire
narrative window, and 12 confirmations do not make reorgs impossible.

Recorded HTTP fixtures are prose-redacted historical test inputs. Tests never
fall through to live requests, and fixture reports are labeled prominently.
They are not used by the default run or supplied as demo evidence.
