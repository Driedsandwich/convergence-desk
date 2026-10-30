import { describe, test, expect } from 'bun:test'
import { configSchema, evaluate, normalize, digest, endpoint } from './evidence'
import fixture from '../../tests/fixtures/synthetic_cre_cases.json'

describe('SYNTHETIC: parity with Python runtime.venue_evidence', () => {
  for (const item of fixture.cases) test(item.name, () => {
    const config = configSchema.parse(item.config)
    const result = evaluate(config, item.coinbase, item.kraken)
    expect(result.verdict).toBe(item.expected.verdict)
    expect(result.cross_venue_status).toBe(item.expected.cross_venue_status)
    if (item.expected.spread === null) expect(result.spread).toBeNull()
    else expect(Number(result.spread)).toBeCloseTo(item.expected.spread, 12)
    for (const venue of ['coinbase', 'kraken'] as const) {
      if (item.expected.returns[venue] === null) expect(result.venues[venue].return_fraction).toBeNull()
      else expect(Number(result.venues[venue].return_fraction)).toBeCloseTo(item.expected.returns[venue]!, 12)
    }
  })
})

test('SYNTHETIC: adapters sort, deduplicate, exclude unfinished and future bars', () => {
  const item = fixture.cases[0], config = configSchema.parse(item.config)
  const bars = [...item.coinbase, { ...item.coinbase.at(-1)!, start: Date.parse(config.window_end), end: Date.parse(config.window_end) + 3600000 }]
  const cb = bars.map(b => [b.start / 1000, b.close, b.close, b.close, b.close, b.volume]).reverse()
  cb.push(cb[2])
  expect(normalize(cb, 'coinbase', config)).toEqual(item.coinbase)
  const kr = bars.map(b => [b.start / 1000, String(b.close), String(b.close), String(b.close), String(b.close), String(b.close), String(b.volume), 1])
  expect(normalize({ error: [], result: { XXBTZUSD: kr, last: 123 } }, 'kraken', config)).toEqual(item.coinbase)
  expect(() => normalize({ error: ['unavailable'] }, 'kraken', config)).toThrow()
  expect(() => normalize([[1, 2]], 'coinbase', config)).toThrow()
  expect(endpoint(config, 'kraken')).toContain('pair=XBTUSD')
  expect(endpoint({ ...config, token: 'DOGE' }, 'kraken')).toContain('pair=XDGUSD')
})

test('SYNTHETIC: canonical SHA-256 known vector and config bounds', () => {
  expect(digest({})).toBe('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a')
  expect(digest({ b: '1.0', a: null })).toBe(digest({ a: null, b: '1.0' }))
  expect(() => configSchema.parse({ ...fixture.cases[0].config, window_end: fixture.cases[0].config.window_start })).toThrow()
})
