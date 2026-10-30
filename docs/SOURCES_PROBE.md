# Convergence Desk: live source probe

Generated from anonymous HTTP calls on this machine; no accounts, keys, cookies, or browser tools.

First request UTC: 2026-10-30T00:29:33Z. Total probe execution time: 55.10s across the recorded phases (excludes human review between phases). Logical HTTP calls: 90. Interrupted: False.

Evidence: [sanitized request results](../probe/results.json); [runnable Python probe](../probe/probe_sources.py). Response bodies and other people's post text are not saved. JSON includes exact query parameters, RPC request bodies, actual field names, status, latency, server Date, sample counts/timestamps, and observed rate headers. No API key or login was supplied. An absent error diagnostic is not evidence that authentication was required.

Run `python3 probe/probe_sources.py` from the artifact directory. It uses Python 3.10+ standard library, 0.2-second pauses, 4-second socket timeouts, 512-KiB response caps, a 245-second scheduling budget and a 275-second Unix watchdog. At most 30 logical calls per source; redirect destinations are retained. The run observed four redirects (two Telegram previews and two CoinDesk RSS requests); counting these still leaves every source at or below 30 requests. Total response storage is bounded and bodies are discarded. The `--resume-followups` and `--resume-accounts` modes preserve earlier observations and source counters; phase timings remain explicit. The main script runs all phases together on a fresh invocation.

A successful HTTP response alone is insufficient: posts, candles, RSS items, or a valid JSON-RPC result must be present. No means the tested request did not return usable data without credentials; it does not prove credentials would fix the failure. No rate-limit headers means no headers observed, not unlimited access. Quotas, sustained ingestion, 20-account polling, and exact RPC maximum block ranges were not tested. All geographic restrictions are unknown: this is one machine, not US/EU vantage points.

| Source | Endpoint tried | Works without key | Observed limits | Data we can use | Known regional blocks | Terms-of-use concern | Verdict |
|---|---|---|---|---|---|---|---|
| Bluesky | https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile<br>https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed<br>https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts | yes | 30 calls; statuses {'200': 18, '400': 10, '403': 2}; 62.4–354.8 ms; no rate-limit headers | {"feed_count": 3, "own_posts_count": 3, "first_own_created_at": "2023-05-23T04:03:28.382Z"}; profiles and author feeds worked; search returned 403 twice | unknown | not checked | use |
| Telegram | https://t.me/s/binance_announcements<br>https://t.me/s/coindesk<br>https://t.me/s/cointelegraph<br>https://t.me/s/kraken_exchange | yes | 6 calls; statuses {'200': 6}; 1383.0–5713.7 ms; no rate-limit headers | {"post_count": 20, "timestamp_count": 20, "last_timestamp": "2026-10-29T13:01:53+00:00", "requested_channel_matched": true}; previews only; automation/AI terms concern below | unknown | “Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform” ([read terms](https://telegram.org/tos/content-licensing)); full sentence below | drop |
| Reddit | https://www.reddit.com/r/CryptoCurrency/new.json | no | 2 calls; statuses {'403': 2}; 327.9–347.4 ms; {"Retry-After": "0"} | No usable response observed | unknown | not checked | drop |
| Mastodon | https://mastodon.social/api/v1/accounts/108194299134124221/statuses<br>https://mastodon.social/api/v1/accounts/109287325649504801/statuses<br>https://mastodon.social/api/v1/accounts/113695123223093208/statuses<br>https://mastodon.social/api/v1/accounts/271000/statuses<br>https://mastodon.social/api/v1/accounts/280129/statuses<br>https://mastodon.social/api/v1/accounts/406396/statuses<br>https://mastodon.social/api/v1/accounts/419188/statuses<br>https://mastodon.social/api/v1/accounts/lookup<br>https://mastodon.social/api/v1/timelines/public | yes | 19 calls; statuses {'422': 3, '200': 14, '404': 2}; 322.6–789.7 ms; {"x-ratelimit-remaining": "299", "x-ratelimit-limit": "300", "x-ratelimit-reset": "2026-10-30T00:30:00.967090Z"} | Account lookup and two old account feeds worked; public timeline required authentication. No current organizational feed confirmed. | unknown | not checked | backup |
| Coinbase Exchange | https://api.exchange.coinbase.com/products/ETH-USD/candles | yes | 3 calls; statuses {'200': 3}; 79.2–99.7 ms; no rate-limit headers | {"candles_count": 350, "first_candle_timestamp": 1793319900, "first_candle_field_count": 6, "newest_candle_timestamp": 1793319900, "newest_candle_age_seconds": 403} | unknown | not checked | use |
| Kraken | https://api.kraken.com/0/public/OHLC | yes | 3 calls; statuses {'200': 3}; 344.1–358.4 ms; no rate-limit headers | {"result_keys": ["XETHZUSD", "last"], "candles_count": 721, "first_candle_timestamp": 1793104200, "newest_candle_timestamp": 1793320200, "newest_candle_age_seconds": 103} | unknown | not checked | use |
| Binance market data | https://data-api.binance.vision/api/v3/klines | yes | 3 calls; statuses {'200': 3}; 106.5–222.8 ms; {"x-mbx-used-weight": "2", "x-mbx-used-weight-1m": "2"} | {"candles_count": 3, "first_candle_timestamp": 1793319600000, "first_candle_field_count": 12, "newest_candle_timestamp": 1793320200000, "newest_candle_age_seconds": 103} | unknown | not checked | backup |
| CoinGecko | https://api.coingecko.com/api/v3/simple/price | yes | 3 calls; statuses {'200': 3}; 78.9–283.7 ms; no rate-limit headers | {"asset_count": 2, "last_updated_at": 1793320290} | unknown | not checked | backup |
| Ethereum PublicNode | https://ethereum-rpc.publicnode.com | yes | 4 calls; statuses {'200': 4}; 86.4–797.4 ms; no rate-limit headers | {"logs_count": 787, "first_block_number": 26301981}; 3- and 10-block USDC Transfer ranges worked; maximum range not tested | unknown | not checked | use |
| Ethereum Cloudflare | https://cloudflare-eth.com | no | 3 calls; statuses {'200': 3}; 110.6–154.2 ms; no rate-limit headers | No usable response observed | unknown | not checked | drop |
| Ethereum LlamaRPC | https://eth.llamarpc.com | no | 3 calls; statuses {'525': 3}; 588.0–741.1 ms; no rate-limit headers | No usable response observed | unknown | not checked | drop |
| Ethereum Ankr | https://rpc.ankr.com/eth | no | 3 calls; statuses {'200': 3}; 256.1–611.9 ms; no rate-limit headers | No usable response observed | unknown | not checked | drop |
| CoinDesk RSS | https://www.coindesk.com/arc/outboundfeeds/rss/ | yes | 2 calls; statuses {'200': 2}; 229.7–236.0 ms; no rate-limit headers | {"items_count": 25, "first_item_dates": ["Fri, 30 Oct 2026 00:17:10 +0000"]} | unknown | not checked | use |
| Cointelegraph RSS | https://cointelegraph.com/rss | yes | 2 calls; statuses {'200': 2}; 92.4–118.5 ms; no rate-limit headers | {"items_count": 30, "first_item_dates": ["Fri, 30 Oct 2026 00:11:26 +0000", "Fri, 30 Oct 2026 00:25:19 +0000"]} | unknown | not checked | use |
| Decrypt RSS | https://decrypt.co/feed | yes | 2 calls; statuses {'200': 2}; 84.2–138.1 ms; no rate-limit headers | {"items_count": 38, "first_item_dates": ["Thu, 29 Oct 2026 22:57:48 +0000"]} | unknown | not checked | use |

## Runnable integration update (2026-10-30)

The default decisions below supersede the historical fallback ordering in the original probe:
**publisher RSS is the primary voice source**, with Bluesky author feeds for explicitly
configured handles. The new machine probe tested 20 publisher feeds; 19 returned items
within seven days and are included. Blockworks returned only stale items (newest
2026-01-07), so it is excluded. Decrypt was the only tested Bluesky handle with original
posts within seven days and is included under the same `voice_id` as Decrypt RSS.
The 19 publisher identities fit the engine's 20-voice limit. Trust weight 0.8 is a visible
demo configuration choice, not a measured accuracy rating.

Evidence: [expanded sanitized results](../probe/expanded_sources.json),
[repeatable freshness probe](../probe/expand_sources.py), and
[default voices](../convergence_desk/config/default_voices.json).
No publisher text is saved by the probe. RSS and post reuse rights remain unchecked;
the integration discards full text after transient extraction and keeps only hashes,
URIs, metadata, feature scores/rule traces and excerpts of at most 140 characters.

Telegram remains excluded under the already-recorded content-licensing line:
> Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform

The full recorded sentence and source URL remain below. Reddit remains excluded after HTTP 403.

| Publisher | Items within 7 days | Newest item in this run | Default |
|---|---:|---|---|
| CoinDesk | 25 | 2026-10-30T00:17:10+00:00 | use |
| Cointelegraph | 30 | 2026-10-30T00:11:26+00:00 | use |
| Decrypt | 38 | 2026-10-29T22:57:48+00:00 | use |
| The Block | 20 | 2026-10-29T21:49:16+00:00 | use |
| Blockworks | 0 | 2026-01-07T14:00:00+00:00 | drop |
| Bitcoin Magazine | 10 | 2026-10-29T23:18:27+00:00 | use |
| CryptoSlate | 10 | 2026-10-30T00:40:53+00:00 | use |
| The Defiant | 100 | 2026-10-29T23:32:17+00:00 | use |
| Bitcoinist | 8 | 2026-10-29T17:00:27+00:00 | use |
| NewsBTC | 10 | 2026-10-30T00:00:00+00:00 | use |
| BeInCrypto | 12 | 2026-10-29T21:57:27+00:00 | use |
| CryptoPotato | 36 | 2026-10-29T22:07:05+00:00 | use |
| U.Today | 94 | 2026-10-30T00:01:00+00:00 | use |
| Cryptonews | 20 | 2026-10-29T22:30:00+00:00 | use |
| Unchained | 10 | 2026-10-30T00:10:00+00:00 | use |
| The Daily Hodl | 10 | 2026-10-29T22:14:21+00:00 | use |
| Protos | 10 | 2026-10-29T18:58:18+00:00 | use |
| DL News | 2 | 2026-10-28T22:30:00+00:00 | use |
| AMBCrypto | 16 | 2026-10-30T00:00:45+00:00 | use |
| Crypto Briefing | 30 | 2026-10-30T00:36:21+00:00 | use |

Bluesky freshness: Decrypt 50/50 original posts within seven days; CoinDesk,
The Block, Bitcoin Magazine, The Defiant and Unchained returned no originals in
that window. Only Decrypt is selected by default; users can add public handles.

### Market and on-chain measurements from the runnable agent

The first 48-hour live run fetched 51 completed hourly bars per supported primary
market. Coinbase returned HTTP 404 for TRX-USD; Kraken TRXUSD plus Binance TRXUSDT
provided the fallback cross-check. The USDT/USD quote difference is explicitly
included in the 2% spread tolerance. A separate keyless CoinGecko `/coins/ethereum/ohlc`
request returned 14 completed rows for the tested window. CoinGecko OHLC has no
volume field: it is price-only fallback context, never fabricated volume confirmation.
Venue agreement compares a common completed timestamp, window-return signs and
relative closing-price spread; the original per-venue volume series stays separate.

PublicNode accepted four log requests: USDC and USDT over two consecutive inclusive
10-block chunks each (20 blocks total, 26302055–26302074 in the first live run).
Ten blocks is a measured working chunk size, **not a provider maximum**. The reader
uses 12 confirmations and a configurable 1–100-block window with chunks capped at
10. `eth_call` with selector `0x313ce567` returned decimals=6 for each token; these
verified results and provenance are cached in git-ignored `runs/token_decimals.json`.
Block headers supplied event timestamps from 00:42:47 through 00:46:35 UTC for
retained events. This is a short recent liquidity sample, not 48 hours of on-chain history.
Mint/burn and transfers strictly above the configured threshold are retained; smaller
ordinary transfers are discarded. Transfer totals include large mints/burns when they
meet that threshold. These observations describe market-wide liquidity and do not
contribute a token-direction vote or override market/risk checks.

## Confirmed organizational account watchlist

This is the proposed small Bluesky demo watchlist, not a claim of six currently active voices. Each listed account returned original-author posts; repost-only results do not qualify. Domain handles and brand-named handles are distinguished: independent ownership verification of the `.bsky.social` accounts was not tested. These are organization/media-branded account candidates, not private-individual recommendations. Retain provenance and require user selection before trusting an unverified brand handle.

| Requested Bluesky account | Successful calls | Own posts in first successful sample | First own post timestamp |
|---|---|---|---|
| [coindesk.com](https://bsky.app/profile/coindesk.com) | 2 | 3 | 2025-02-25T20:55:45.537Z |
| [decrypt.co](https://bsky.app/profile/decrypt.co) | 2 | 3 | 2026-10-29T21:39:53.187Z |
| [theblock.bsky.social](https://bsky.app/profile/theblock.bsky.social) | 2 | 3 | 2025-11-06T17:26:15.985Z |
| [bitcoinmagazine.bsky.social](https://bsky.app/profile/bitcoinmagazine.bsky.social) | 2 | 3 | 2023-05-23T04:03:28.382Z |
| [thedefiant.bsky.social](https://bsky.app/profile/thedefiant.bsky.social) | 1 | 2 | 2024-10-17T15:48:57.354Z |
| [unchainedcrypto.bsky.social](https://bsky.app/profile/unchainedcrypto.bsky.social) | 1 | 3 | 2024-03-29T13:45:59.971Z |

The returned dates matter: in this run Decrypt was current, while CoinDesk, The Block, Bitcoin Magazine, The Defiant and Unchained samples were older. Do not relabel those historical posts as today's convergence or pad the list with accounts that returned empty feeds. A 20-account polling workload was not tested. Several requested domain handles returned HTTP 400; successful account resolution or an empty feed does not establish a usable voice.

### All tested voice identities

| Platform | Requested account/channel | Feed HTTP status | Observed posts | First/last sampled timestamp |
|---|---|---|---|---|
| Bluesky | coindesk.com | 200 | 3 | 2025-02-25T20:55:45.537Z |
| Bluesky | cointelegraph.com | 400 | 0 | none observed |
| Bluesky | decrypt.co | 200 | 3 | 2026-10-29T21:39:53.187Z |
| Bluesky | theblock.co | 400 | 0 | none observed |
| Bluesky | blockworks.co | 400 | 0 | none observed |
| Bluesky | bitcoinmagazine.com | 400 | 0 | none observed |
| Bluesky | kraken.com | 400 | 0 | none observed |
| Bluesky | coinbase.com | 400 | 0 | none observed |
| Bluesky | messari.io | 400 | 0 | none observed |
| Bluesky | unchainedcrypto.com | 400 | 0 | none observed |
| Bluesky | thedefiant.io | 400 | 0 | none observed |
| Bluesky | bankless.com | 400 | 0 | none observed |
| Telegram | cointelegraph | 200 | 17 | 2026-10-29T23:37:58+00:00 |
| Telegram | coindesk | 200 | 0 | none observed |
| Telegram | binance_announcements | 200 | 20 | 2026-10-29T13:01:53+00:00 |
| Telegram | kraken_exchange | 200 | 0 | none observed |
| Mastodon | cointelegraph | 200 | 1 | 2018-01-29T14:15:06.438Z |
| Mastodon | bitcoinmagazine | 200 | 0 | none observed |
| Bluesky | cointelegraph.bsky.social | 200 | 0 | none observed |
| Bluesky | theblock.bsky.social | 200 | 3 | 2025-11-06T17:26:15.985Z |
| Bluesky | blockworks.bsky.social | 200 | 0 | none observed |
| Bluesky | bitcoinmagazine.bsky.social | 200 | 3 | 2023-05-23T04:03:28.382Z |
| Bluesky | thedefiant.bsky.social | 200 | 2 | 2024-10-17T15:48:57.354Z |
| Bluesky | bankless.bsky.social | 200 | 0 | none observed |
| Bluesky | messari.bsky.social | 200 | 0 | none observed |
| Bluesky | unchainedcrypto.bsky.social | 200 | 3 | 2024-03-29T13:45:59.971Z |
| Bluesky | coinbase.bsky.social | 200 | 0 | none observed |
| Bluesky | krakenfx.bsky.social | 200 | 0 | none observed |
| Mastodon | protos | 200 | 0 | none observed |
| Mastodon | coindesk | 200 | 0 | none observed |
| Mastodon | decrypt | 200 | 3 | 2022-11-04T22:57:23.402Z |
| Mastodon | cryptonews | 200 | 0 | none observed |
| Mastodon | TheBlock | 200 | 0 | none observed |

## Detailed observations

Field names and per-request parameters, HTTP status, timestamps, latency, small samples and JSON-RPC errors are recorded in `probe/results.json`. Anonymous failures do not distinguish key requirements from WAF, rate limiting, region filtering or other server policy unless the returned diagnostic says so.

### Bluesky
Observed response shape (keys/types only): `{"top_level_fields": ["feed", "cursor"], "post_fields": ["uri", "cid", "author", "record", "embed", "bookmarkCount", "replyCount", "repostCount", "likeCount", "quoteCount", "indexedAt", "labels"], "record_fields": ["$type", "createdAt", "embed", "facets", "text"]}`

- HTTP 403: "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"

### Telegram
Observed response shape (keys/types only): `{"top_level_fields": ["html_classes_present", "time_datetime_present"]}`

### Reddit

- HTTP 403: "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"

### Mastodon
Observed response shape (keys/types only): `{"top_level_fields": ["id", "username", "acct", "display_name", "locked", "bot", "discoverable", "indexable", "group", "created_at", "note", "url", "uri", "avatar", "avatar_static", "avatar_description", "header", "header_static", "header_description", "followers_count", "following_count", "statuses_count", "last_status_at", "hide_collections", "show_media", "show_media_replies", "show_featured", "noindex", "feature_approval", "emojis", "roles", "fields"]}`

- HTTP 422: "This method requires an authenticated user"

- HTTP 404: "Record not found"

### Coinbase Exchange
Observed response shape (keys/types only): `{"type": "array", "first_item_shape": {"type": "array", "first_item": "int"}}`

### Kraken
Observed response shape (keys/types only): `{"top_level_fields": ["error", "result"]}`

### Binance market data
Observed response shape (keys/types only): `{"type": "array", "first_item_shape": {"type": "array", "first_item": "int"}}`

### CoinGecko
Observed response shape (keys/types only): `{"top_level_fields": ["bitcoin", "ethereum"]}`

### Ethereum PublicNode
Observed response shape (keys/types only): `{"top_level_fields": ["jsonrpc", "id", "result"]}`

### Ethereum Cloudflare

- HTTP 200: {"code": -32046, "message": "Cannot fulfill request"}

- HTTP 200: {"code": -32603, "message": "Internal error"}

### Ethereum LlamaRPC

### Ethereum Ankr

- HTTP 200: {"code": -32000, "message": "Unauthorized: You must authenticate your request with an API key. Create an account on https://www.ankr.com/rpc/ and generate your personal API key for free."}

### CoinDesk RSS
Observed response shape (keys/types only): `{"root": "rss", "first_item_fields": ["title", "link", "{http://search.yahoo.com/mrss/}content", "guid", "pubDate", "description", "{http://purl.org/dc/elements/1.1/}creator", "{http://purl.org/rss/1.0/modules/content/}encoded", "{http://purl.org/dc/elements/1.1/}description", "category", "category", "category"]}`

### Cointelegraph RSS
Observed response shape (keys/types only): `{"root": "rss", "first_item_fields": ["title", "pubDate", "{http://www.w3.org/2005/Atom}updated", "guid", "link", "description", "{http://purl.org/dc/elements/1.1/}creator", "{http://search.yahoo.com/mrss/}content", "enclosure", "category"]}`

### Decrypt RSS
Observed response shape (keys/types only): `{"root": "rss", "first_item_fields": ["title", "link", "pubDate", "description", "{http://purl.org/dc/elements/1.1/}creator", "guid", "enclosure", "category", "category", "category", "{http://search.yahoo.com/mrss/}thumbnail"]}`

### Telegram terms

> For clarity, Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform to train, fine-tune, validate or otherwise engage in the development, enhancement, benchmarking or deployment of artificial intelligence, machine learning models and similar technologies.

Read at https://telegram.org/tos/content-licensing (2026-10-30T00:36:14Z). The page also describes a consent-based exception; that consent was not obtained or tested. This is a source-selection concern, not a legal clearance assessment.

## Interpretation and limits

Editorial interpretation below refers to the recorded 2026-10-30 run. On a later rerun, revalidate these observations against the newly generated table and JSON; the editorial text is not automatically reassessed.

- Bluesky: profile keys included `handle`, `postsCount`, `followersCount`; author feeds included `feed[].post.record` and post timestamps. The tested `searchPosts?q=bitcoin&limit=3` returned 403/non-JSON twice. Authentication as a fix was not tested. Author polling can work without search.
- Telegram: `cointelegraph` and `binance_announcements` each returned posts twice, with HTML message classes and `<time datetime>` attributes. `coindesk` and `kraken_exchange` redirected to pages with no preview posts. Technical reachability does not override the content-licensing restriction quoted above. Drop for this agent.
- Reddit: the exact `new.json?limit=3&raw_json=1` request returned 403 twice despite the descriptive User-Agent saved in results. Block reason, logged-in access and geographic variation were not tested.
- Mastodon: `mastodon.social` public timeline returned 422 and explicitly said `This method requires an authenticated user`. Anonymous account lookup/statuses worked for some accounts. Cointelegraph's returned post was from 2018, Decrypt's from 2022; the other tested populated profile counts did not guarantee an original status feed. Rate headers advertised limit 300 with remaining/reset values; sustainable request throughput and instance-wide limits were not tested.
- Markets: Coinbase returned six-position candle arrays (350 rows); Kraken returned `error` and `result`, including `XETHZUSD` and `last` (721 rows); Binance returned twelve-position kline arrays (3 rows). These counts are observations, not documented server maxima. Array position semantics were not verified against documentation in this job. CoinGecko returned `usd`, `usd_24h_vol`, and `last_updated_at` for the two requested assets without a key. Binance exposed used-weight counters; the allowed maximum was not observed. All exact cache/rate headers captured by the final probe version are in JSON.
- RPC: JSON-RPC failures can have HTTP 200. PublicNode returned both block heights and USDC Transfer logs over inclusive 3- and 10-block ranges (184 and 787 logs in this run). Ten blocks is the largest tested range, not the provider maximum. Cloudflare returned `Cannot fulfill request` for block number and `Internal error` for logs; LlamaRPC returned HTTP 525; Ankr explicitly required an API key. Latest-only log calls were still attempted on these failing endpoints. No quota exhaustion or large-range stress test was performed.
- News: all three RSS feeds returned items twice. Saved samples contain item counts, dates and XML field names only. RSS publishing does not establish reuse permissions; terms were not checked. RSS entries and social posts from the same outlet are one voice, not two independent endorsements.
- Regional availability: unknown for every source. US and EU probes were not performed and this machine's egress location was not verified. A local success cannot establish that a judge in either region can call it. No country-specific block was observed or inferred.

## Default source set

1. **Voices — Bluesky author feeds plus publisher RSS as an explicit fallback.** The six-account watchlist above contains only accounts that returned original posts, but only `decrypt.co` supplied a recent sample. Start with that domain-handled account for current social posts; keep the other five as visibly historical/verification-pending candidates rather than claiming current convergence. For a viable current multi-organization demo, use the three confirmed publisher identities below. These are public organization feeds, **not social accounts**. This is a fallback to the requested account model; the probe did not establish several fresh, independently verified social accounts. Cap the user-selected list at 20, and count each publisher once across feeds and social accounts. Polling interval/capacity beyond this brief probe: not tested.

| Confirmed public publisher identity | Feed actually fetched twice | Items per sampled response | First item date in this run |
|---|---|---|---|
| CoinDesk RSS | https://www.coindesk.com/arc/outboundfeeds/rss/ | 25 | Fri, 30 Oct 2026 00:17:10 +0000 |
| Cointelegraph RSS | https://cointelegraph.com/rss | 30 | Fri, 30 Oct 2026 00:11:26 +0000, Fri, 30 Oct 2026 00:25:19 +0000 |
| Decrypt RSS | https://decrypt.co/feed | 38 | Thu, 29 Oct 2026 22:57:48 +0000 |

2. **Market evidence — Coinbase Exchange ETH-USD candles + Kraken ETHUSD OHLC.** Both worked keylessly on repeated calls; use two venues for cross-checks, and judge freshness from event timestamps rather than HTTP success. At the last check Coinbase's newest five-minute candle opened about 403 seconds before fetch and Kraken's about 103 seconds before fetch; an open candle is not a completed candle. These are the recommended candidates for US/EU judges to retry using the exact saved URLs, but US/EU reachability remains **not tested**, not guaranteed. CoinGecko's keyless simple-price endpoint is an aggregate backup; no other CoinGecko endpoint or token-coverage claim was tested. Binance's data-only host also worked here, but cross-region availability is unverified, so keep it as a backup.

3. **On-chain reads — Ethereum PublicNode** at `https://ethereum-rpc.publicnode.com`. The exact USDC contract and Transfer topic are stored in each RPC request in JSON. Logs include `blockNumber`, `transactionHash`, `logIndex`, `topics`, `data` and `removed`. That supplies evidence for transfer decoding and amount thresholds; this probe did **not** compute large-transfer classifications, verify token decimals with `eth_call`, or interpret transfers as buys/sells. A production reader would also need confirmations/reorg handling; those were not tested.

4. **Optional news — CoinDesk RSS.** It returned 25 items twice. If it is already selected as a publisher voice, display it as news context without counting it again toward convergence. Cointelegraph and Decrypt RSS also worked as alternatives.

The source probe is complete; no agent, trading logic, account, real-money position, or external post was created. The observations do not establish a fresh multi-account social-only default or US/EU availability, and the report deliberately leaves those requirements unverified rather than presenting invented evidence.
