# Submission form draft

## Tagline

Public market narratives become practice decisions, explicit rejections, and a reasoning trail you can replay offline.

## Short description (about 205 words)

Convergence Desk is a deterministic research agent that interprets public crypto narratives and records the practice positions it would open, or explains why it abstains. It combines the news feeds (RSS) of selected crypto publishers with original Bluesky posts, counts each publisher once, and checks completed hourly price bars (candles) on two exchanges before applying portfolio risk limits. Every candidate keeps the keywords that fired, the convergence checks, the market evidence and the decision rules. Controlled interventions remove voices, change thresholds and disable market confirmation to reveal which changes affect convergence or acceptance. A separate Ethereum stablecoin sample supplies liquidity context without becoming a directional vote. Source failures remain visible, retries and checkpoints support recovery, and a chaos mode deliberately switches off one source to show that the run still finishes and says what was missing. Each run writes an offline HTML report, a snapshot of every input and a decision hash (a fingerprint of the result); replay rebuilds the result from the snapshot without network access and checks that the fingerprint matches. Accepted plans enter an append-only practice ledger. It uses no language model: every step is an explicit rule. There are no real orders, no API keys and no claims of predictive accuracy.

## Longer description (about 467 words)

Convergence Desk addresses a review problem: a market narrative can sound persuasive while hiding missing evidence, conflicting voices or an unsafe position size. The agent makes those steps inspectable. It reads publisher feeds, extracts the token, its direction and the writer's conviction (how strongly the claim is made) with explicit keyword rules, and records either a complete practice position or a rejection with failed checks.

The default voice configuration combines publisher news feeds (RSS) with Decrypt's original Bluesky posts. Channels belonging to one publisher share a vote, and posting frequency does not increase its weight. Candidates must meet configured conviction, distinct-publisher and quorum requirements (a minimum combined trust weight). Neutral mentions and unsuccessful candidates remain visible. These are media narratives, not individual traders, and configured trust weights are not measured accuracy ratings.

Narrative convergence alone is insufficient. The runtime compares completed hourly price bars from two exchanges, checks that the data is fresh and that the price moved in the narrative's direction over the window, and requires the two closing prices to sit within a configured spread (2% by default). Volume confirmation uses the primary venue's own history. Coinbase and Kraken are primary sources; Binance and CoinGecko provide fallbacks with limitations disclosed. A recent Ethereum USDC and USDT sample describes liquidity separately and never supplies a token direction vote.

The decision layer checks opposing convergence, existing positions, daily losses, reserved stop risk and exposure limits. Accepted plans include a reference entry price, a size, a stop-loss price, a profit target and a time limit. Later runs evaluate observable exits in an append-only practice ledger. This remains a coarse simulation using completed bars, without fees, slippage (the gap between expected and executed prices) or real orders.

Cause and effect is demonstrated through controlled software interventions. Removing each publisher and changing thresholds reruns convergence, market checks and portfolio allocation. The report separates voices pivotal to acceptance from voices pivotal only to convergence. Disabling market confirmation is another recorded intervention; hypothetical alternatives never become ledger positions.

Failure is part of the output. Bounded requests, retries, circuit breakers that pause a failing source, and checkpoints support collection. Source health and unavailable evidence remain visible, thresholds stay unchanged, and a deliberate chaos run still produces a report marked as degraded (and a distinct exit status for scripts).

For review, each run saves an HTML report, source provenance, extracted features, a snapshot and a decision hash. Offline replay recomputes decisions and interventions without changing the ledger. Full publisher text is discarded after extraction; hashes support consistency, not proof of authenticity or re-extraction. Regional reachability beyond one machine is unverified. The submission emphasizes inspectable reasoning, explicit abstention and repeatability rather than trading performance. It needs only Python itself (no third-party packages), no accounts and no keys, and its source code carries the MIT license.

## Bounty and track selection

The supplied material establishes the following scope, but does not establish official sponsor/bounty or track titles. Use the form's exact labels when submitting; the descriptions below are scope references, not invented official names.

- **Bounty scope:** “Build agents that interpret market evidence and record the practice trades they would make. Strong entries show cause and effect and preserve a repeatable reasoning trail.”
- **Applicable track, identified by the rubric published on the sponsor's own hackathon page (ryobuild.com/hackathon, read 2026-10-30):** Real thinking (25%), Cause and effect (20%), Repeatability (10%), Advanced execution (5%).
- **Common criteria (same page):** Combining sources (20%) and Coping with failure (20%). These are common judging criteria, not additional tracks.

## Required submission links

- **Public code repository:** supply the actual publicly accessible repository URL. The checked working copy points to a local Git bundle, which does not establish a public URL.
- **Architecture:** link `docs/ARCHITECTURE.md` in that public repository.
- **Video demo:** supply the uploaded recording URL after following `docs/DEMO_SCRIPT.md`.

The repository URL, exact official bounty/track titles and video URL remain submission fields to complete. This document does not claim the code has been publicly published or that the video has been recorded.
