import { z } from 'zod'
import { sha256 } from '@noble/hashes/sha2.js'
import { bytesToHex } from '@noble/hashes/utils.js'

export const configSchema = z.object({
  schema_version: z.literal(1),
  record_decision_hash: z.string().regex(/^[a-f0-9]{64}$/),
  synthetic_for_tests: z.boolean(),
  token: z.string().regex(/^[A-Z0-9]{1,12}$/),
  direction: z.enum(['bullish', 'bearish']),
  window_start: z.string().datetime({ offset: true }),
  window_end: z.string().datetime({ offset: true }),
  market_min_return: z.number().finite().positive(),
  cross_venue_max_spread: z.number().finite().positive().max(0.2),
  max_market_age_hours: z.number().finite().positive(),
  market_min_volume_z: z.number().finite(),
  volume_lookback: z.number().int().min(2).max(240),
}).strict().refine(c => {
  const hours = (Date.parse(c.window_end) - Date.parse(c.window_start)) / 3600000
  return hours >= 1 && hours <= 240
}, 'window must be 1..240 hours')
export type Config = z.infer<typeof configSchema>
export type Bar = { start: number; end: number; close: number; volume: number }
export type Venue = 'coinbase' | 'kraken'
export const thresholdKeys = ['market_min_return', 'cross_venue_max_spread',
  'max_market_age_hours', 'market_min_volume_z', 'volume_lookback'] as const

// This result format intentionally uses decimal strings for measurements. Sorted
// keys + JSON primitives then have identical UTF-8 encodings in Python and JS.
export function canonicalJSON(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('non-finite JSON')
    const encoded = JSON.stringify(value)
    if (encoded === undefined) throw new Error('non-JSON value')
    return encoded
  }
  if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']'
  const obj = value as Record<string, unknown>
  return '{' + Object.keys(obj).sort().map(k => JSON.stringify(k) + ':' + canonicalJSON(obj[k])).join(',') + '}'
}
export const digest = (value: unknown) => bytesToHex(sha256(new TextEncoder().encode(canonicalJSON(value))))
const decimal = (n: number | null) => n === null ? null : String(n)
const iso = (n: number | null) => n === null ? null : new Date(n).toISOString()
export const fetchStart = (c: Config) => Math.floor((Date.parse(c.window_start) - 3 * 3600000) / 3600000) * 3600000

export function endpoint(c: Config, venue: Venue): string {
  if (venue === 'coinbase') return `https://api.exchange.coinbase.com/products/${c.token}-USD/candles?granularity=3600&start=${encodeURIComponent(new Date(fetchStart(c)).toISOString())}&end=${encodeURIComponent(c.window_end)}`
  const pair = (c.token === 'BTC' ? 'XBT' : c.token === 'DOGE' ? 'XDG' : c.token) + 'USD'
  return `https://api.kraken.com/0/public/OHLC?pair=${pair}&interval=60&since=${fetchStart(c) / 1000}`
}

export function normalize(data: unknown, venue: Venue, c: Config): Bar[] {
  let rows: unknown
  if (venue === 'kraken') {
    const response = data as { error?: unknown[]; result?: Record<string, unknown> }
    if (!Array.isArray(response.error) || response.error.length || !response.result) throw new Error('Kraken API error or malformed response')
    rows = Object.entries(response.result).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).find(([key]) => key !== 'last')?.[1]
  } else rows = data
  if (!Array.isArray(rows)) throw new Error(`${venue}: missing candles`)
  const result = new Map<number, Bar>()
  for (const row of rows) {
    if (!Array.isArray(row) || row.length < (venue === 'coinbase' ? 6 : 8)) throw new Error(`${venue}: malformed candle`)
    const start = Number(row[0]) * 1000, end = start + 3600000
    if (!Number.isFinite(start) || start % 3600000 !== 0) throw new Error(`${venue}: invalid hourly timestamp`)
    // Ignore in-progress candles and all later data returned by Kraken (no end parameter).
    if (end > Date.parse(c.window_end) || end < fetchStart(c)) continue
    const [open, high, low, close, volume] = (venue === 'coinbase'
      ? [row[3], row[2], row[1], row[4], row[5]] : [row[1], row[2], row[3], row[4], row[6]]).map(Number)
    if (![open, high, low, close, volume].every(Number.isFinite) || Math.min(open, high, low, close) <= 0 || volume < 0 || high < Math.max(open, close, low) || low > Math.min(open, close)) throw new Error(`${venue}: invalid OHLCV`)
    result.set(start, { start, end, close, volume })
  }
  return [...result.values()].sort((a, b) => a.end - b.end)
}

function single(series: Bar[], c: Config) {
  const start = Date.parse(c.window_start), end = Date.parse(c.window_end)
  const latest = series.at(-1), anchor = series.filter(b => b.end <= start).at(-1)
  const ret = latest && anchor && latest.end > start ? latest.close / anchor.close - 1 : null
  const fresh = !!latest && !!anchor && (end - latest.end) / 3600000 <= c.max_market_age_hours &&
    (start - anchor.end) / 3600000 <= c.max_market_age_hours && latest.end > start
  const previous = latest ? series.filter(b => b.end < latest.end).slice(-c.volume_lookback).map(b => b.volume) : []
  const mean = previous.reduce((a, b) => a + b, 0) / previous.length
  const std = Math.sqrt(previous.reduce((a, b) => a + (b - mean) ** 2, 0) / previous.length)
  const volumeZ = latest && previous.length === c.volume_lookback && std > 0 ? (latest.volume - mean) / std : null
  const signed = ret === null ? null : ret * (c.direction === 'bullish' ? 1 : -1)
  const status = fresh && signed !== null && signed <= -c.market_min_return ? 'contradict'
    : fresh && signed !== null && signed >= c.market_min_return && volumeZ !== null && volumeZ >= c.market_min_volume_z ? 'confirm' : 'inconclusive'
  return { ret, fresh, status, close: latest?.close ?? null, volumeZ,
    anchor: anchor?.end ?? null, latest: latest?.end ?? null }
}

export function evaluate(c: Config, coinbase: Bar[], kraken: Bar[]) {
  const krakenEnds = new Set(kraken.map(b => b.end))
  const common = coinbase.filter(b => krakenEnds.has(b.end)).map(b => b.end)
  const end = common.length ? Math.max(...common) : null
  const values = { coinbase: single(coinbase.filter(b => end === null || b.end <= end), c),
    kraken: single(kraken.filter(b => end === null || b.end <= end), c) }
  const left = values.coinbase, right = values.kraken
  const spread = end !== null && left.close !== null && right.close !== null ? Math.abs(left.close - right.close) / Math.min(left.close, right.close) : null
  const aligned = end !== null && left.ret !== null && right.ret !== null && Math.sign(left.ret) === Math.sign(right.ret)
  const fresh = left.fresh && right.fresh
  const agreement = end !== null && fresh && aligned && spread !== null && spread <= c.cross_venue_max_spread
  const status = agreement ? 'agreement' : end !== null && fresh && spread !== null ? 'disagreement' : 'unavailable'
  return {
    verdict: agreement ? left.status : status === 'disagreement' ? 'contradict' : 'inconclusive',
    cross_venue_status: status, spread: decimal(spread), same_return_direction: aligned,
    common_completed_endpoint: iso(end),
    venues: Object.fromEntries(Object.entries(values).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([venue, v]) => [venue, {
      return_fraction: decimal(v.ret), close: decimal(v.close), volume_z: decimal(v.volumeZ),
      anchor_at: iso(v.anchor), endpoint_at: iso(v.latest), fresh: v.fresh, verdict: v.status,
    }])),
  }
}
