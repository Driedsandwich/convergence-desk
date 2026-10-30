# Screen demo script — 2 minutes 50 seconds

Record a terminal and the generated local HTML report. The time marks below are edited video time, not a promise about network latency. Capture each live command starting and finishing; trim waiting with a visible “Waiting for public sources — elapsed time trimmed” caption. Keep the real report timestamp visible. Do not replace an uneventful result with synthetic inputs, lower thresholds to obtain a position, or call a resumed run a new live collection.

Before recording, activate Python 3.10+ from the repository root and prepare fresh paths in one Bash terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
DEMO_RUN="runs/video-$(date -u +%Y%m%dT%H%M%S)-$$"
DEMO_CHAOS="$DEMO_RUN-chaos"
```

Use separate ledgers so earlier practice positions do not obscure the explanation. Keep the terminal free of `set -e`: chaos intentionally exits 2. Opening HTML below is a presenter action; no browser automation is part of the agent.

| Video time | Command / screen action | Narration |
|---|---|---|
| 0:00–0:18 | Type command A below. Show source progress, then its final JSON and exit code after a clearly marked wait cut. | “Convergence Desk reads public market evidence and records practice decisions. It needs no keys and places no orders. I am collecting a fresh observation with a forty-eight-hour narrative window.” |
| 0:18–0:37 | Type command B. Point to **PRACTICE ONLY**, the observation timestamp, **What the agent concluded** cards, then **Decision summary**, counts and state. | “This summary is the result for the time shown. Read the current counts here. A converged narrative can still be rejected. No position is a valid outcome when evidence or risk checks fail.” |
| 0:37–1:08 | In **Why**, expand **XRP bullish** if present in this observation, otherwise the candidate selected during preflight. Point to source URIs and fired extraction rules, then **Convergence and risk rules** and **Market check**. | “Here is one candidate's evidence path. These links identify the publisher inputs. The fired words explain the scores. Each qualifying publisher votes once. The agent then checks completed candles, volume and agreement across venues. These failed checks explain this rejection.” |
| 1:08–1:38 | Scroll to **Cause and effect**. Point separately at decision-pivotal and convergence-pivotal columns. Expand **All intervention values and results** and find the relevant `leave_out_voice` trial. Use the verified XRP branch below only if it matches the displayed snapshot. | “For this XRP observation, CryptoPotato is pivotal to convergence. Removing it loses quorum, but the trade still rejects because market evidence fails. That is why the decision-pivotal column is empty. Disabling market confirmation flips acceptance in the stored intervention. That alternative is an explanation, not an opened position.” |
| 1:38–1:55 | Point to **Rejection ledger**, including XRP and, if present, both BTC directions. | “The rejection ledger keeps failed rules with actual and required values. Opposing convergent directions can block each other. The report preserves reasons to abstain instead of hiding the candidates that failed.” |
| 1:55–2:23 | Type command C, show source completion and `chaos exit: 2`, then command D. Point to **Decision summary** → “degraded; thresholds unchanged”, **Source health and provenance** → `publicnode`, and **Market-wide liquidity** → `available: false`. | “Now I deliberately fail PublicNode. The run still produces a report and exits two. The source row records the deliberate failure. Thresholds stay unchanged. Stablecoin liquidity is unavailable; it is context and never supplies a directional vote.” |
| 2:23–2:50 | Return to the original report's **Replay** section and point to the full decision hash. Type command E. Show `replay_match: true`, identical full hash strings and `replay exit: 0`. | “Replay reads only the saved snapshot. It reruns decisions and interventions without network calls or ledger changes. The decision hash matches. This verifies the saved reasoning trail. It does not prove the source was correct or reconstruct discarded text.” |

**A — fresh live run**

```bash
python -m convergence_desk.cli run --hours 48 --out "$DEMO_RUN" --ledger "$DEMO_RUN/practice_ledger.jsonl"
echo "run exit: $?"
```

**B — open the live report**

```bash
python -m webbrowser -t "file://$(pwd)/$DEMO_RUN/report.html"
```

**C — deliberately kill one source in a fresh run**

```bash
python -m convergence_desk.cli chaos --kill publicnode --hours 48 --out "$DEMO_CHAOS" --ledger "$DEMO_CHAOS/practice_ledger.jsonl"
echo "chaos exit: $?"
```

**D — open the chaos report**

```bash
python -m webbrowser -t "file://$(pwd)/$DEMO_CHAOS/report.html"
```

**E — replay the original snapshot**

```bash
python -m convergence_desk.cli replay "$DEMO_RUN/snapshot.json"
echo "replay exit: $?"
```

## Verified reference and live-result branches

Documentation verification used observation time **2026-10-30T01:17:03.356069Z**, directory `runs/20261030T011703356069Z`: **433 posts, 3 converged narratives, 0 practice positions, 32 rejected token/direction candidates**, exit **0**, not degraded. Its decision hash was:

```text
37ad4e440e659ca234dca1b27a21634086f3d07e3751817997bb81c26712d87d
```

Replay of that snapshot returned `replay_match: true` and exit 0. These are observations from that run, not promised output for the recording session. The report's source timestamps and content hashes identify its inputs.

In that same observation, XRP bullish had qualifying publishers `cryptopotato` and `utoday`, each weight 0.8, total 1.6. Its failed decision checks were `market_confirmation`, `return_aligned`, and `volume_z`. Each publisher was **convergence-pivotal**, with no decision-pivotal voice. The `drop_market_evidence` intervention changed acceptance from false to true. BTC bullish and bearish both converged and both failed `no_direction_conflict`. These facts support the narration above without claiming a practice position was opened.

For a new recording, inspect the generated report before choosing the final narration:

- If a practice position exists, use its **Why** entry and say: “These checks passed. The summary records its reference entry, units, stop, target and time stop. This is a practice plan.” Point at those fields rather than narrating a rejection.
- If a decision-pivotal voice exists, name it and show its trial: “Removing this voice changes acceptance. The full pipeline, including portfolio allocation, is rerun.” Distinguish the acceptance flip from convergence alone.
- If only a convergence-pivotal voice exists, use the wording in the timed XRP example with the actual candidate and publisher.
- If neither exists, say: “No pivotal voice appeared in this observation.” To demonstrate a real pivotal case, show the preserved reference snapshot above if available, with its historical timestamp clearly labeled, and return to the new live run for chaos/replay. Never promise or fabricate a pivotal live result. Without a preserved suitable snapshot, this demo requirement remains unshown.

The chaos run is a new collection; its overall hash is expected to differ from the original run. Demonstrate equality by replaying a snapshot against its own saved expected hash. A run can already be degraded before chaos; show the PublicNode-specific failure row to establish the deliberate intervention. If all inputs fail and exit 1 occurs, show the failure honestly instead of claiming successful degraded completion.
