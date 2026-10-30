# Convergence Desk

![Convergence Desk: many public signals converge into one checked decision](docs/assets/cover.png)

Convergence Desk is a deterministic market research agent that turns public publisher narratives into an explicit practice decision: a position with size and exits, or a rejection with the failed rules. It counts each publisher once, checks completed candles across two venues, applies portfolio risk limits, and reruns controlled interventions to show what changes the result. Every run produces an offline HTML report and a hashed snapshot that can reproduce the decision without network access. It uses Python's standard library, requires zero API keys, and never places real orders.

## 60-second quickstart

Start in the repository root with **Python 3.10+**. No runtime package installation, account, wallet, or key is required. The setup takes a few commands; live collection can take longer than a minute because it waits for public sources. These commands use Bash on Linux/macOS and create fresh output folders and separate practice ledgers:

```bash
python3 -m venv .venv
source .venv/bin/activate
DEMO_RUN="runs/quickstart-$(date -u +%Y%m%dT%H%M%S)-$$"
python -m convergence_desk.cli run --hours 48 --out "$DEMO_RUN" --ledger "$DEMO_RUN/practice_ledger.jsonl"
echo "run exit: $?"
python -m webbrowser -t "file://$(pwd)/$DEMO_RUN/report.html"
python -m convergence_desk.cli replay "$DEMO_RUN/snapshot.json"
python -m convergence_desk.cli chaos --kill publicnode --hours 48 --out "$DEMO_RUN-chaos" --ledger "$DEMO_RUN-chaos/practice_ledger.jsonl"
echo "chaos exit: $?"
python -m webbrowser -t "file://$(pwd)/$DEMO_RUN-chaos/report.html"
```

On a headless machine, copy `report.html` to a desktop and open it locally. Exit **0** means completed without degraded source health; **2** means completed with degraded sources and still produces a report; **1** means failure (or a replay mismatch). A rejection is a valid result and does not by itself cause exit 2. Do not run these commands under `set -e` if you want to continue after exit 2.

The shorter live command is `python -m convergence_desk.cli run --hours 48`; it prints its output directory and uses `runs/practice_ledger.jsonl`. Replay accepts that directory's `snapshot.json`. Reusing `--out` resumes its frozen observation time and checkpoints; use a fresh directory for a new observation. Configuration overrides are `--voices FILE`, `--rules FILE`, and `--risk FILE`; defaults live in [config](convergence_desk/config/).

## What the agent does

1. Freeze a UTC observation time; read selected publishers, rules, risk limits, and prior practice positions. Collect RSS titles/summaries and original Bluesky author posts within the requested window, subject to available feed history.
2. Extract token mentions, direction, conviction and urgency using visible lexical rules. Persist feature scores, fired rules, source URIs, hashes and excerpts of at most 140 characters. Full text is transient; articles are not fetched.
3. Group token/direction candidates. Each qualifying publisher contributes its configured trust weight once per candidate, even across RSS and Bluesky. Default convergence requires two distinct publishers, weight at least 1.5, and conviction at least 0.5. Neutral and nonconvergent candidates remain visible.
4. Fetch completed hourly candles for supported mentions and existing positions, always including BTC and ETH. Check window return, freshness and latest volume against that venue's previous five bars. Require two venues with a common completed endpoint, matching return signs and close spread no greater than 2%. The primary venue supplies volume confirmation; volumes are never averaged.
5. Read a recent Ethereum USDC/USDT liquidity sample for context. It contributes no directional vote and does not affect the CLI's trade acceptance.
6. Evaluate observable exits on prior practice positions. Reject conflicting directions and failed evidence/risk checks. Otherwise size the position against stop risk, remaining daily risk and exposure, with entry reference, stop, target and time stop. Defaults use a hypothetical $10,000 account, 10% position cap, 1% per-trade risk budget, 3% daily budget including reserved open risk, at most three open positions, 5% stop distance, 2R target and 24-hour holding limit.
7. Remove each voice and perturb thresholds, rerunning market checks and portfolio allocation. Record both decision-pivotal and convergence-pivotal voices. Also test disabling market confirmation while retaining entry and risk checks.
8. Save `snapshot.json`, `record.json`, `report.html`, and idempotent open/close events in the append-only practice ledger. Offline replay rebuilds the record from saved inputs and compares its complete decision hash.

## How this maps to the rubric

Weights are reproduced as supplied by the sponsor, with common and track criteria kept separate.

| Rubric line | Exact implementation | Report evidence |
|---|---|---|
| Common: Combining sources — 20% | [`sources/voices.py::prepare`](convergence_desk/sources/voices.py), [`core/converge.py::converge`](convergence_desk/core/converge.py), [`runtime.py::venue_evidence`](convergence_desk/runtime.py), [`sources/publicnode.py::fetch`](convergence_desk/sources/publicnode.py) | **Why** → post evidence, **Market check**, **Market-wide liquidity**; chain context is explicitly separate from voting |
| Common: Coping with failure — 20% | [`sources/common.py::Client.fetch`](convergence_desk/sources/common.py), [`core/resilience.py::retry`, `CircuitBreaker.call`, `CheckpointStore.save`](convergence_desk/core/resilience.py), [`cli.py::run`](convergence_desk/cli.py) | **Decision summary** degraded note; **Source health and provenance**; **Rejection ledger** for insufficient evidence |
| Track: Real thinking — 25% | [`core/extract.py::extract`](convergence_desk/core/extract.py), [`core/converge.py::converge`](convergence_desk/core/converge.py), [`core/evidence.py::check_evidence`](convergence_desk/core/evidence.py), [`core/decide.py::decide`](convergence_desk/core/decide.py) | **What the agent concluded** cards (one per converged narrative, with the failed rules and what would change the decision); **Why** → extraction traces, **Convergence and risk rules**, **Market check**. Reasoning is deterministic rules, not an LLM |
| Track: Cause and effect — 20% | [`runtime.py::interventions`, `evaluate`](convergence_desk/runtime.py) | **Cause and effect**, including **All intervention values and results**; interventions explain the engine's decisions, not market causality |
| Track: Repeatability — 10% | [`core/trail.py::canonical_json`, `content_hash`](convergence_desk/core/trail.py), [`runtime.py::make_record`](convergence_desk/runtime.py), [`cli.py::replay`](convergence_desk/cli.py) | **Replay** → command, decision and snapshot SHA-256; **Source health and provenance** |
| Track: Advanced execution — 5% | [`core/decide.py::decide`](convergence_desk/core/decide.py), [`ledger.py::evaluate`, `openings`, `append`](convergence_desk/ledger.py) | **Decision summary** → size and exits; **Why** → risk rules. Persistent lifecycle events are in the JSONL ledger, not a dedicated report panel; execution is practice only |
| Does not score: API-call volume | [`cli.py::run`](convergence_desk/cli.py), [`report.py::render`](convergence_desk/report.py) | **Source health and provenance** documents requests for traceability, not a volume score |
| Does not score: a wall of charts without an argument | [`report.py::render`](convergence_desk/report.py) | **Why** and **Rejection ledger** expose actual-versus-required rule checks; the report uses tables, not charts |
| Does not score: short-term P&L | [`ledger.py::evaluate`](convergence_desk/ledger.py) | **Decision summary** emphasizes plans and reasons. Simulated losses feed risk accounting; the report does not present a performance score |
| Does not score: fabricated or placeholder data presented as real | [`sources/voices.py::prepare`](convergence_desk/sources/voices.py), [`runtime.py::make_record`](convergence_desk/runtime.py), [`report.py::render`](convergence_desk/report.py) | **Source health and provenance** preserves observed hashes and fetch times; recorded test input is visibly labeled when used. Default `run` fetches live sources |

## Data sources and provenance

| Source actually wired into the CLI | Use and boundary |
|---|---|
| Publisher RSS/Atom, URLs in [`default_voices.json`](convergence_desk/config/default_voices.json) | CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine, CryptoSlate, The Defiant, Bitcoinist, NewsBTC, BeInCrypto, CryptoPotato, U.Today, Cryptonews, Unchained, The Daily Hodl, Protos, DL News, AMBCrypto and Crypto Briefing. Titles and summaries represent media narratives |
| Bluesky public `app.bsky.feed.getAuthorFeed` | Decrypt (`decrypt.co`) by default; original author posts, no reposts; same publisher vote as Decrypt RSS. No search API |
| Coinbase Exchange `/products/{symbol}-USD/candles`; Kraken `/0/public/OHLC` | Primary completed hourly price/volume evidence |
| Binance `data-api.binance.vision/api/v3/klines` | Fallback hourly evidence, quoted in USDT; USD/USDT basis is included in spread tolerance |
| CoinGecko `/api/v3/coins/{id}/ohlc` | Keyless fallback price context for configured IDs; lacks per-bar volume, so cannot supply volume confirmation |
| Ethereum PublicNode JSON-RPC | USDC/USDT transfers, token decimals and block timestamps; defaults: 20 blocks, 10-block chunks, 12 confirmations, large amount strictly above 1,000,000 token units |

HTTP provenance records source, endpoint, fetch time, status and SHA-256 of response bytes; RPC calls also retain request parameters. Per-item provenance links normalized content to its source. Failed requests retain diagnostics without response bodies. Post/title hashes refer to normalized content before truncation. Replay uses stored extraction features, not the excerpts. Hashes establish local consistency, not publisher authenticity or independently verifiable extraction from discarded text.

Exclusions follow the recorded observations in [SOURCES_PROBE.md](docs/SOURCES_PROBE.md), especially its **Runnable integration update**: Telegram was dropped because the recorded content-licensing terms restrict scraping/aggregation for AI uses and consent was not obtained or tested; Reddit returned HTTP 403. Mastodon had no confirmed current organizational feed; Blockworks RSS was stale; other tested Bluesky handles were stale, empty or unsuccessful. Cloudflare Ethereum returned RPC errors, LlamaRPC returned HTTP 525, and Ankr explicitly requested an API key. These are historical probe findings, not claims about current global availability or legal clearance. The runnable integration update supersedes the probe's earlier source ordering.

## Limitations

- Practice only; no real orders, wallet connection, broker integration or background monitoring. Entry is a completed-candle reference, not an executable quote. Ledger exits use hourly bars without fees or slippage; adverse gaps can exceed planned stop risk. A missing history interval defers closure and keeps risk reserved.
- RSS headlines and summaries are media narratives, not individual traders. Publisher identities need not represent independent information: syndication and shared stories are not deduplicated across outlets. Trust weights are configuration choices, not accuracy estimates.
- Extraction is an English lexical heuristic. It does not understand sarcasm, pronouns or cross-clause references. Urgency is recorded but does not change allocation. There is no LLM integration and no environment variable is read; `.env.example` is intentionally empty.
- Public API reachability has been checked from one machine only; other regions, including US/EU access, are unverified. RSS/Bluesky reuse permissions remain unchecked in the source probe.
- Requested hours filter finite feeds; they do not guarantee a complete archive. Bluesky stops after five pages. Market coverage is an explicit symbol allowlist; unsupported mentions remain candidates with missing market evidence.
- The on-chain sample covers recent blocks, not the narrative window; totals are token units, not guaranteed dollars. Confirmations reduce exposure to reorgs but there is no subsequent reorg reconciliation. Liquidity context is not a token buy/sell signal.
- Local checkpoints and ledgers require a single writer. Use separate output and ledger paths for concurrent runs. Changing configuration requires a new output directory. Offline replay needs compatible code and preserved features; it cannot re-extract discarded text or authenticate a source from a hash alone.
- A pivotal voice or accepted position is not guaranteed in a live run. “None in tested steps” is a local sensitivity result, not proof of general robustness.

## Chainlink CRE workflow

An optional TypeScript CRE workflow independently checks a converged narrative using Coinbase/Kraken candle consensus and an Ethereum USDC supply read. Export with `convergence-desk cre-config`, simulate with the CRE CLI, and attach the result with `convergence-desk cre-attach`; the original decision stays unchanged. See [setup, commands and verification status](docs/CRE.md). The workflow builds locally; successful simulation still requires your CRE login.

## Documentation and license

[Architecture and schemas](docs/ARCHITECTURE.md) · [2:50 demo script](docs/DEMO_SCRIPT.md) · [Submission form draft](docs/SUBMISSION.md) · [Source probe](docs/SOURCES_PROBE.md).

Code is distributed under the [MIT License](LICENSE), copyright 2026 Driedsandwich. This code license does not grant rights to publisher content.
