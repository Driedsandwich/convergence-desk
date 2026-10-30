import {
  CronCapability, HTTPClient, EVMClient, handler, consensusIdenticalAggregation,
  Runner, type NodeRuntime, type Runtime, getNetwork, LAST_FINALIZED_BLOCK_NUMBER,
  encodeCallMsg, bytesToHex,
} from '@chainlink/cre-sdk'
import { encodeFunctionData, decodeFunctionResult, zeroAddress } from 'viem'
import { configSchema, type Config, type Bar, type Venue, endpoint, normalize,
  evaluate, digest, thresholdKeys, canonicalJSON } from './evidence'

const USDC = '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48' as const
const abi = [{ type: 'function', name: 'totalSupply', stateMutability: 'view',
  inputs: [], outputs: [{ type: 'uint256' }] }] as const

// Consensus covers only normalized completed bars, not changing HTTP headers,
// Kraken's cursor, or its unfinished candle. No fabricated fallback values.
function fetchCandles(runtime: NodeRuntime<Config>): string {
  const http = new HTTPClient()
  const series = {} as Record<Venue, Bar[]>
  for (const venue of ['coinbase', 'kraken'] as const) {
    const response = http.sendRequest(runtime, { url: endpoint(runtime.config, venue), method: 'GET' }).result()
    if (response.statusCode !== 200) throw new Error(`${venue}: HTTP ${response.statusCode}`)
    series[venue] = normalize(JSON.parse(new TextDecoder().decode(response.body)), venue, runtime.config)
  }
  return JSON.stringify(series)
}

function onCron(runtime: Runtime<Config>) {
  const c = runtime.config
  const observed = runtime.now().toISOString()
  if (Date.parse(c.window_end) > Date.parse(observed)) throw new Error('window_end is in the future')
  const candles = JSON.parse(runtime.runInNodeMode(fetchCandles, consensusIdenticalAggregation<string>())().result()) as Record<Venue, Bar[]>
  const network = getNetwork({ chainFamily: 'evm', chainSelectorName: 'ethereum-mainnet' })
  if (!network) throw new Error('Ethereum mainnet is not supported by this SDK')
  const evm = new EVMClient(network.chainSelector.selector)
  const response = evm.callContract(runtime, {
    call: encodeCallMsg({ from: zeroAddress, to: USDC,
      data: encodeFunctionData({ abi, functionName: 'totalSupply' }) }),
    blockNumber: LAST_FINALIZED_BLOCK_NUMBER,
  }).result()
  const supply = decodeFunctionResult({ abi, functionName: 'totalSupply', data: bytesToHex(response.data) })
  const payload = {
    schema_version: 1, check: 'chainlink-cre-market-evidence',
    record_decision_hash: c.record_decision_hash, synthetic_for_tests: c.synthetic_for_tests,
    token: c.token, direction: c.direction, window_start: c.window_start, window_end: c.window_end,
    thresholds: Object.fromEntries(thresholdKeys.map(key => [key, String(c[key])])),
    observed_at: observed, ...evaluate(c, candles.coinbase, candles.kraken),
    onchain: { chain: 'ethereum-mainnet', contract: USDC, function: 'totalSupply()',
      value: supply.toString(), decimals: '6', block_reference: 'finalized', read_at: runtime.now().toISOString(),
      scope: 'Current market-wide USDC supply; context only, not a directional vote or historical window value.' },
  }
  // Serialize nullable observations: SDK handler output types do not accept null.
  return canonicalJSON({ ...payload, sha256: digest(payload) })
}

export async function main() {
  const runner = await Runner.newRunner<Config>({ configSchema })
  await runner.run(() => [handler(new CronCapability().trigger({ schedule: '0 0 * * * *' }), onCron)])
}
