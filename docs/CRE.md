# Chainlink CRE market-evidence workflow

This optional TypeScript workflow orchestrates Coinbase Exchange and Kraken HTTP reads, consensus over their normalized completed candles, an Ethereum USDC `totalSupply()` EVM read, and a market-evidence verdict. The Python agent exports one converged narrative and imports the result as an **independent second check**. Existing decisions, snapshots, hashes, ledgers and default run output are unchanged.

**Verification here:** CRE CLI v1.39.0 installed; SDK v1.23.0 workflow compiled to WASM; 17 TypeScript tests and 135 Python tests passed. Simulation stopped at authentication. **No successful CRE simulation or deployment is claimed.** A successful authenticated simulation remains necessary for the quoted bounty requirement.

## Install and authenticate

The exact automatic CLI install command from the official [macOS / Linux installation page](https://docs.chain.link/cre/getting-started/cli-installation/macos-linux) is:

```bash
curl -sSL https://app.chain.link/cre/install.sh | bash
```

Open a new shell, or add the installed commands to your current shell:

```bash
export PATH="$HOME/.cre/bin:$HOME/.bun/bin:$PATH"
cre version
cre login
```

`cre login` is interactive; complete it yourself. No login, account creation, API key or wallet was used during implementation. The [simulation guide](https://docs.chain.link/cre/guides/operations/simulating-workflows) requires authentication and only specifies an EVM private key for workflows performing writes. This workflow has no write capability calls, no secrets file and no private key requirement in its configuration. Authentication prevented checking later simulator requirements here.

Install Bun (the [TypeScript setup guide](https://docs.chain.link/cre/getting-started/part-1-project-setup-ts) requires Bun >=1.2.21):

```bash
curl -fsSL https://bun.com/install | bash
export PATH="$HOME/.bun/bin:$PATH"
```

From the repository root, install the Python entry point and the locked workflow dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cd cre/market-evidence
bun install --frozen-lockfile
bun run typecheck
bun run build
cd ../..
```

`bun run build` runs `bun cre-compile main.ts wasm/workflow.wasm`, the compiler command documented in [Custom WASM Builds](https://docs.chain.link/cre/guides/operations/custom-build). It succeeds without CRE authentication. Compilation is not simulation. The current SDK automatically obtains the Javy compiler during compilation.

## Generate the input from an existing run

Replace `runs/<id>` with an actual completed run directory:

```bash
convergence-desk cre-config runs/<id>/record.json --out cre/config.json
```

The sibling `snapshot.json` must be present: `record.json` does not contain the run's window length or complete rules. The exporter verifies the record and snapshot hashes, selects the highest-weight converged narrative (then voice count, token and direction, matching Python ordering), and exports the frozen observation window. If no narrative converged, it fails explicitly without inventing one. An unsupported top token also fails rather than silently substituting a different narrative.

Thresholds originate in `default_rules.json`; effective run overrides are preserved from the snapshot. Besides `market_min_return` and `cross_venue_max_spread`, the config carries `max_market_age_hours`, `volume_lookback`, and `market_min_volume_z` so the full `venue_evidence` status can be reproduced. `record_decision_hash` binds the result to its run. Recorded/synthetic test input is labeled `synthetic_for_tests: true`.

Generate the config close to the original run: Kraken supplies finite rolling history, so old windows may have no anchor. The workflow never moves the window forward silently. A missing pair or failed HTTP/RPC read fails the workflow; missing completed bars yield unavailable/inconclusive evidence. It does not fabricate fallback observations. Public endpoints and authenticated execution have not been verified end to end here.

## Simulate after logging in

Run from the `cre/` project root:

```bash
cd cre
cre workflow simulate market-evidence --target staging-settings --non-interactive --trigger-index 0
```

That is the exact simulation command attempted here. It exited **1** with this output:

```text
Initializing...

! You are not logged in

✗ Authentication required: not logged in and no CRE_API_KEY set
  → Run 'cre login' interactively, or
  → Set CRE_API_KEY environment variable for non-interactive use
✗ authentication required: no credentials found: you are not logged in, run cre login and try again
```

No further simulation attempt was made after this authentication gate. Run `cre login` yourself, then the command above. No `--broadcast` flag is used.

For a successful run, capture stdout and extract the handler's result (Bash):

```bash
# Still in cre/
set -o pipefail
cre workflow simulate market-evidence --target staging-settings --non-interactive --trigger-index 0 | tee simulate.log
# Continue only if the simulation command succeeds:
python3 extract_result.py simulate.log simulate_output.json
cd ..
convergence-desk cre-attach runs/<id> cre/simulate_output.json
```

Expected successful CLI output includes `Workflow compiled`, simulator initialization, and `Workflow Simulation Result:` followed by a JSON string containing the result object. The SDK's handler output type disallows nullable fields, so the handler returns serialized JSON; `extract_result.py` decodes it into an ordinary JSON object. The extractor rejects logs with no successful result marker. **These are expected output markers from the docs, not output observed from a successful simulation here.**

The result includes token, direction, frozen window, thresholds, per-venue returns/closes/volume z-scores and anchor/endpoint times, common endpoint, close spread, verdict, observation time, USDC context and `sha256`. Decimal measurements and the uint256 supply are strings to preserve portable hashing and integer precision; missing observations are null. Raw USDC supply uses 6 decimals.

`cre-attach` validates the SHA-256, run identity, narrative, window, thresholds and result schema, copies the extracted JSON bytes into `runs/<id>/cre_result.json`, and inserts/replaces one escaped **Chainlink CRE check** section in `report.html`. It never changes `record.json`, `snapshot.json`, ledger entries or the original decision. Repeat attachment is idempotent. The hash checks local consistency; imported CLI output is **not a signed DON attestation**.

## Semantics and official SDK references

- The layout follows [Project Setup](https://docs.chain.link/cre/getting-started/part-1-project-setup-ts) and [Project Configuration](https://docs.chain.link/cre/reference/project-configuration-ts): `cre/project.yaml`, a `market-evidence/` workflow directory with `workflow.yaml`, `main.ts`, `package.json`, `tsconfig.json`, and a generated project-level `config.json` referenced as `../config.json`.
- [HTTP fetching](https://docs.chain.link/cre/getting-started/part-2-fetching-data-ts): `HTTPClient.sendRequest(...).result()` executes inside `runtime.runInNodeMode`. Both adapters use the same public endpoints and token mappings as Python. Candles are deduplicated, sorted and filtered by completed hour; requests include three hours of pre-window anchor history.
- [Consensus](https://docs.chain.link/cre/reference/sdk/consensus-ts): `consensusIdenticalAggregation<string>()` requires agreement on serialized normalized candle series. It excludes HTTP headers, Kraken's changing cursor and unfinished candle. A disagreement fails consensus rather than manufacturing an averaged OHLC series. Local simulation is a single-node model; distributed consensus happens on the deployed DON.
- The verdict mirrors `runtime.venue_evidence`: latest common completed endpoint; last baseline close at/before window start; fresh endpoint and anchor; matching return signs; `abs(close1-close2)/min(close1,close2)` within the limit. Agreement retains Coinbase's evidence status, including directional minimum return and population-standard-deviation volume z-score over the preceding bars. Kraken's volume does not gate confirmation, nor does its return independently need to exceed the minimum. Cross-venue disagreement means `contradict`; unavailable comparison means `inconclusive`. No risk, publisher convergence, or portfolio decision is reevaluated in CRE.
- [EVM reads](https://docs.chain.link/cre/getting-started/part-3-reading-onchain-value-ts) and [supported networks](https://docs.chain.link/cre/supported-networks-ts): `EVMClient.callContract`, `encodeCallMsg`, viem ABI helpers and `LAST_FINALIZED_BLOCK_NUMBER` read Ethereum mainnet USDC at `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` through `https://ethereum-rpc.publicnode.com`. This is current finalized supply, not liquidity measured over the narrative's historical window. It contributes no directional vote.
- On-chain writing is deliberately omitted under the requested exception: the [write tutorial](https://docs.chain.link/cre/getting-started/part-4-writing-onchain-ts) requires a deployed consumer contract with the appropriate report ABI. This project has none. There is no deployment, signing, transaction or mainnet write code.
- `sha256` hashes UTF-8 JSON of the entire result **excluding `sha256`**, with object keys recursively sorted, compact separators, array order retained, and no ASCII escaping. All measurements are strings; schema version is an integer. This is a separate serialization contract from the Python decision record's float canonicalization.

## Offline tests

```bash
source .venv/bin/activate
python -m pip install pytest
python -m pytest -q --ignore=tests/test_cli.py --ignore=tests/test_sources.py
cd cre/market-evidence
bun test
```

The working copy omits `tests/fixtures/recorded/`; those two Python test files are intentionally excluded and no recorded fixtures were recreated. `tests/test_cre.py`, `tests/fixtures/synthetic_cre_cases.json`, and `evidence.test.ts` use clearly labeled invented data. The shared cases compare TypeScript behavior against the unchanged Python implementation, including contradictory returns, stale/missing anchors, endpoint truncation, spread, primary volume and secondary-venue boundary behavior. Tests also check import integrity, wrong-run rejection, unchanged replay and idempotent report attachment. Synthetic test results are not bounty simulation evidence.
