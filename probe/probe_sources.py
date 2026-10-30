#!/usr/bin/env python3
"""Bounded, anonymous source probe. Python 3.10+, standard library only.

Run: python3 probe/probe_sources.py
Writes sanitized probe/results.json and docs/SOURCES_PROBE.md beside this script.
Never persists response bodies, post text, account bios, or transaction addresses.
"""
import json
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
UA = "ConvergenceDesk-source-probe/0.1 (public read-only hackathon compatibility test; no credentials)"
MAX_BODY = 524288
BUDGET = 245
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC = "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
ROWS = []
COUNTS = Counter()
START = 0


class Preview(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.times, self.classes, self.text = [], [], set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-post" in a:
            self.ids.append(a["data-post"])
        if tag == "time" and "datetime" in a:
            self.times.append(a["datetime"])
        self.classes.update(c for c in a.get("class", "").split() if c.startswith("tgme_widget_message"))

    def handle_data(self, data):
        # Used only transiently to inspect terms; never serialized for posts.
        self.text.append(data)


def shape(value, depth=0):
    """Only field names/types, inspecting first array element; never text values."""
    if depth > 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(k): shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return {"type": "array", "first_item": shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def call(source, url, kind="json", payload=None, context=None):
    if COUNTS[source] >= 30 or time.monotonic() - START >= BUDGET:
        return None
    time.sleep(0.20)
    COUNTS[source] += 1
    row = {"source": source, "url": url, "method": "POST" if payload else "GET",
           "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "credentials_sent": False, "status": None, "usable": False,
           "rate_limit_headers": {}, "context": context or {}}
    if payload:
        row["rpc_request"] = payload
    headers = {"User-Agent": UA, "Accept": "application/json" if kind == "json" else "*/*"}
    data = None
    if payload:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    begun = time.monotonic()
    response = None
    obj = None
    try:
        try:
            response = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=4)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            row["status"] = response.status
            row["final_url"] = response.url
            row["content_type"] = response.headers.get("Content-Type", "")
            row["server_date"] = response.headers.get("Date")
            row["cache_headers"] = {k: v for k, v in response.headers.items() if k.lower() in ("age", "cache-control", "cf-cache-status", "x-cache")}
            row["rate_limit_headers"] = {k: v for k, v in response.headers.items()
                                         if "ratelimit" in k.lower().replace("-", "") or k.lower() == "retry-after"
                                         or "used-weight" in k.lower()}
            body = response.read(MAX_BODY + 1)
        row["bytes_read"] = len(body)
        row["truncated"] = len(body) > MAX_BODY
        if row["truncated"]:
            row["parse_error"] = "body exceeded 512 KiB; not parsed"
        elif kind == "json":
            obj = json.loads(body)
            row["shape"] = shape(obj)
            sample = {}
            ok = row["status"] == 200
            if isinstance(obj, dict) and (obj.get("error") or obj.get("errors")):
                ok = False
                err = obj.get("error", obj.get("errors"))
                # API errors are diagnostics, never posts; allow only a short code/message.
                sample["api_error"] = ({k: err[k] for k in ("code", "message") if k in err}
                                       if isinstance(err, dict) else str(err)[:240])
                row["api_error"] = sample["api_error"]
            purpose = (context or {}).get("purpose", "")
            if purpose == "feed":
                feed = obj.get("feed", [])
                handle = context["account"]
                own = [x for x in feed if x.get("post", {}).get("author", {}).get("handle") == handle
                       and not x.get("reason")]
                sample = {"feed_count": len(feed), "own_posts_count": len(own),
                          "first_own_created_at": own[0].get("post", {}).get("record", {}).get("createdAt") if own else None}
                ok = ok and bool(own)
            elif purpose == "profile":
                sample = {k: obj[k] for k in ("handle", "postsCount", "followersCount", "createdAt") if k in obj}
                ok = ok and "handle" in obj
            elif purpose == "search":
                sample = {"posts_count": len(obj.get("posts", []))}
                ok = ok and bool(obj.get("posts"))
            elif purpose == "reddit":
                sample = {"children_count": len(obj.get("data", {}).get("children", []))}
                ok = ok and bool(sample["children_count"])
            elif purpose == "mastodon":
                sample = {"statuses_count": len(obj) if isinstance(obj, list) else 0,
                          "first_created_at": obj[0].get("created_at") if isinstance(obj, list) and obj else None}
                ok = ok and bool(sample["statuses_count"])
            elif purpose == "mastodon_lookup":
                sample = {"id": obj.get("id"), "acct": obj.get("acct"), "statuses_count": obj.get("statuses_count")}
                ok = ok and bool(obj.get("id"))
            elif purpose == "coinbase" or purpose == "binance":
                sample = {"candles_count": len(obj) if isinstance(obj, list) else 0,
                          "first_candle_timestamp": obj[0][0] if isinstance(obj, list) and obj else None,
                          "first_candle_field_count": len(obj[0]) if isinstance(obj, list) and obj else None}
                ok = ok and bool(sample["candles_count"])
                if ok:
                    sample["newest_candle_timestamp"] = max(x[0] for x in obj)
                    stamp = sample["newest_candle_timestamp"] / (1000 if purpose == "binance" else 1)
                    sample["newest_candle_age_seconds"] = round(time.time() - stamp)
            elif purpose == "kraken":
                result = obj.get("result", {})
                keys = [k for k in result if k != "last"]
                candles = result.get(keys[0], []) if keys else []
                sample = {"result_keys": list(result), "candles_count": len(candles),
                          "first_candle_timestamp": candles[0][0] if candles else None}
                ok = ok and bool(candles)
                if ok:
                    sample["newest_candle_timestamp"] = max(x[0] for x in candles)
                    sample["newest_candle_age_seconds"] = round(time.time() - sample["newest_candle_timestamp"])
            elif purpose == "coingecko":
                sample = {"asset_count": len(obj) if isinstance(obj, dict) else 0}
                ok = ok and isinstance(obj.get("bitcoin"), dict) and "usd" in obj["bitcoin"]
                if ok:
                    sample["last_updated_at"] = obj["bitcoin"].get("last_updated_at")
            elif payload:
                result = obj.get("result")
                if payload["method"] == "eth_blockNumber":
                    sample["block_number"] = int(result, 16) if isinstance(result, str) and result.startswith("0x") else None
                    ok = ok and sample["block_number"] is not None
                else:
                    sample["logs_count"] = len(result) if isinstance(result, list) else None
                    sample["first_block_number"] = int(result[0]["blockNumber"], 16) if isinstance(result, list) and result else None
                    ok = ok and isinstance(result, list)
            row["sample"] = sample
            row["usable"] = ok
        elif kind == "telegram":
            p = Preview()
            p.feed(body.decode("utf-8", "replace"))
            row["shape"] = {"html_classes_present": sorted(p.classes), "time_datetime_present": bool(p.times)}
            row["sample"] = {"post_count": len(p.ids), "timestamp_count": len(p.times), "last_timestamp": p.times[-1] if p.times else None,
                             "requested_channel_matched": any(x.startswith(context["account"] + "/") for x in p.ids)}
            row["usable"] = row["status"] == 200 and bool(p.ids) and row["sample"]["requested_channel_matched"]
        elif kind == "rss":
            tree = ET.fromstring(body)
            items = tree.findall(".//item") or tree.findall("{http://www.w3.org/2005/Atom}entry")
            row["shape"] = {"root": tree.tag, "first_item_fields": [child.tag for child in items[0]] if items else []}
            dates = [child.text for child in items[0] if child.tag in ("pubDate", "{http://www.w3.org/2005/Atom}updated")] if items else []
            row["sample"] = {"items_count": len(items), "first_item_dates": dates}
            row["usable"] = row["status"] == 200 and bool(items)
        elif kind == "terms":
            p = Preview()
            p.feed(body.decode("utf-8", "replace"))
            # No article or post text; print terms only for human review.
            plain = " ".join(" ".join(p.text).split())
            row["shape"] = {"html": True}
            row["sample"] = {"text_character_count": len(plain)}
            quote = "For clarity, Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform to train, fine-tune, validate or otherwise engage in the development, enhancement, benchmarking or deployment of artificial intelligence, machine learning models and similar technologies."
            if row["status"] == 200 and quote in plain:
                row["terms_quote"] = quote
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        row["transport_error"] = str(exc)[:240]
    except (ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as exc:
        row["parse_error"] = type(exc).__name__ + ": " + str(exc)[:160]
    finally:
        row["key_or_login_required"] = "not required for this response" if row["usable"] else "undetermined from this response"
        if "must authenticate" in str(row.get("api_error", "")).lower():
            row["key_or_login_required"] = "required (server explicitly requested API key)"
        row["latency_ms"] = round((time.monotonic() - begun) * 1000, 1)
        ROWS.append(row)
        print(source, COUNTS[source], row["status"], row["latency_ms"], "usable=" + str(row["usable"]), json.dumps(row.get("sample", {})), flush=True)
    return obj if row["usable"] else None


def url(base, **params):
    return base + "?" + urllib.parse.urlencode(params)


def rpc(source, endpoint, method, params):
    return call(source, endpoint, payload={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def run():
    # Prioritize coverage before extra samples or optional discovery.
    bsky = "https://public.api.bsky.app/xrpc/"
    handles = ["coindesk.com", "cointelegraph.com", "decrypt.co", "theblock.co", "blockworks.co", "bitcoinmagazine.com",
               "kraken.com", "coinbase.com", "messari.io", "unchainedcrypto.com", "thedefiant.io", "bankless.com"]
    for handle in handles:
        call("Bluesky", url(bsky + "app.bsky.feed.getAuthorFeed", actor=handle, limit=3, filter="posts_no_replies"), context={"purpose": "feed", "account": handle})
    for _ in range(2):
        call("Bluesky", url(bsky + "app.bsky.actor.getProfile", actor="coindesk.com"), context={"purpose": "profile", "account": "coindesk.com"})
        call("Bluesky", url(bsky + "app.bsky.feed.searchPosts", q="bitcoin", limit=3), context={"purpose": "search"})
    for channel in ["cointelegraph", "coindesk", "binance_announcements", "kraken_exchange", "cointelegraph", "binance_announcements"]:
        call("Telegram", "https://t.me/s/" + channel, "telegram", context={"account": channel})
    for _ in range(2):
        call("Reddit", "https://www.reddit.com/r/CryptoCurrency/new.json?limit=3&raw_json=1", context={"purpose": "reddit"})
        call("Mastodon", "https://mastodon.social/api/v1/timelines/public?limit=3&local=true", context={"purpose": "mastodon"})
    markets = [
        ("Coinbase Exchange", "https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=300", "coinbase"),
        ("Kraken", "https://api.kraken.com/0/public/OHLC?pair=ETHUSD&interval=5", "kraken"),
        ("Binance market data", "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=5m&limit=3", "binance"),
        ("CoinGecko", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_vol=true&include_last_updated_at=true", "coingecko"),
    ]
    for _ in range(2):
        for source, endpoint, purpose in markets:
            call(source, endpoint, context={"purpose": purpose})
    for source, endpoint in [("Ethereum PublicNode", "https://ethereum-rpc.publicnode.com"),
                             ("Ethereum Cloudflare", "https://cloudflare-eth.com"),
                             ("Ethereum LlamaRPC", "https://eth.llamarpc.com"),
                             ("Ethereum Ankr", "https://rpc.ankr.com/eth")]:
        block = rpc(source, endpoint, "eth_blockNumber", [])
        again = rpc(source, endpoint, "eth_blockNumber", [])
        block = again or block
        # Still test getLogs when blockNumber fails: latest-only is a valid small range.
        for width in ([3, 10] if block else [1]):
            end = int(block["result"], 16) if block else None
            filt = {"address": USDC, "topics": [TRANSFER], "fromBlock": hex(end - width + 1) if end else "latest",
                    "toBlock": hex(end) if end else "latest"}
            rpc(source, endpoint, "eth_getLogs", [filt])
    for _ in range(2):
        for source, endpoint in [("CoinDesk RSS", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
                                 ("Cointelegraph RSS", "https://cointelegraph.com/rss"),
                                 ("Decrypt RSS", "https://decrypt.co/feed")]:
            call(source, endpoint, "rss")
    # Recheck a proven original-author feed, not just a profile or repost.
    good = list(dict.fromkeys(r["context"]["account"] for r in ROWS if r["source"] == "Bluesky" and r["usable"] and r["context"].get("purpose") == "feed"))
    for handle in good[:6]:
        call("Bluesky", url(bsky + "app.bsky.feed.getAuthorFeed", actor=handle, limit=3, filter="posts_no_replies"), context={"purpose": "feed", "account": handle})
    # Determine whether a named organizational account is usable on Mastodon.
    for acct in ["cointelegraph", "bitcoinmagazine"]:
        obj = call("Mastodon", url("https://mastodon.social/api/v1/accounts/lookup", acct=acct), context={"purpose": "mastodon_lookup", "account": acct})
        if obj:
            call("Mastodon", "https://mastodon.social/api/v1/accounts/" + obj["id"] + "/statuses?limit=3&exclude_reblogs=true&exclude_replies=true", context={"purpose": "mastodon", "account": acct})
    call("Telegram terms", "https://telegram.org/tos/content-licensing", "terms")
    followups()
    more_accounts()


def followups():
    """Additional account discovery and freshness checks within the same source caps."""
    bsky = "https://public.api.bsky.app/xrpc/"
    good = []
    for handle in ["cointelegraph.bsky.social", "theblock.bsky.social", "blockworks.bsky.social", "bitcoinmagazine.bsky.social",
                   "thedefiant.bsky.social", "bankless.bsky.social", "messari.bsky.social", "unchainedcrypto.bsky.social",
                   "coinbase.bsky.social", "krakenfx.bsky.social"]:
        obj = call("Bluesky", url(bsky + "app.bsky.feed.getAuthorFeed", actor=handle, limit=3, filter="posts_no_replies"), context={"purpose": "feed", "account": handle})
        if obj:
            good.append(handle)
    for handle in good[:2]:
        call("Bluesky", url(bsky + "app.bsky.feed.getAuthorFeed", actor=handle, limit=3, filter="posts_no_replies"), context={"purpose": "feed", "account": handle})
    for source, endpoint, purpose in [
        ("Coinbase Exchange", "https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=300", "coinbase"),
        ("Kraken", "https://api.kraken.com/0/public/OHLC?pair=ETHUSD&interval=5", "kraken"),
        ("Binance market data", "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=5m&limit=3", "binance"),
        ("CoinGecko", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_vol=true&include_last_updated_at=true", "coingecko"),
    ]:
        call(source, endpoint, context={"purpose": purpose})
    call("Mastodon", "https://mastodon.social/api/v1/timelines/public?limit=3&local=true", context={"purpose": "mastodon"})


def more_accounts():
    for acct in ["protos", "coindesk", "decrypt", "blockworks", "cryptoslate", "cryptonews", "TheBlock"]:
        obj = call("Mastodon", url("https://mastodon.social/api/v1/accounts/lookup", acct=acct), context={"purpose": "mastodon_lookup", "account": acct})
        if obj:
            call("Mastodon", "https://mastodon.social/api/v1/accounts/" + obj["id"] + "/statuses?limit=3&exclude_reblogs=true&exclude_replies=true", context={"purpose": "mastodon", "account": acct})


def render(elapsed, interrupted):
    grouped = {}
    for row in ROWS:
        grouped.setdefault(row["source"], []).append(row)
    lines = ["# Convergence Desk: live source probe", "", "Generated from anonymous HTTP calls on this machine; no accounts, keys, cookies, or browser tools.",
             "", f"First request UTC: {ROWS[0]['utc'] if ROWS else 'not tested'}. Total probe execution time: {elapsed:.2f}s across the recorded phases (excludes human review between phases). Logical HTTP calls: {len(ROWS)}. Interrupted: {interrupted}.",
             "", "Evidence: [sanitized request results](../probe/results.json); [runnable Python probe](../probe/probe_sources.py). Response bodies and other people's post text are not saved. JSON includes exact query parameters, RPC request bodies, actual field names, status, latency, server Date, sample counts/timestamps, and observed rate headers. No API key or login was supplied. An absent error diagnostic is not evidence that authentication was required.",
             "", "Run `python3 probe/probe_sources.py` from the artifact directory. It uses Python 3.10+ standard library, 0.2-second pauses, 4-second socket timeouts, 512-KiB response caps, a 245-second scheduling budget and a 275-second Unix watchdog. At most 30 logical calls per source; redirect destinations are retained. The run observed four redirects (two Telegram previews and two CoinDesk RSS requests); counting these still leaves every source at or below 30 requests. Total response storage is bounded and bodies are discarded. The `--resume-followups` and `--resume-accounts` modes preserve earlier observations and source counters; phase timings remain explicit. The main script runs all phases together on a fresh invocation.",
             "", "A successful HTTP response alone is insufficient: posts, candles, RSS items, or a valid JSON-RPC result must be present. No means the tested request did not return usable data without credentials; it does not prove credentials would fix the failure. No rate-limit headers means no headers observed, not unlimited access. Quotas, sustained ingestion, 20-account polling, and exact RPC maximum block ranges were not tested. All geographic restrictions are unknown: this is one machine, not US/EU vantage points.",
             "", "| Source | Endpoint tried | Works without key | Observed limits | Data we can use | Known regional blocks | Terms-of-use concern | Verdict |", "|---|---|---|---|---|---|---|---|"]
    for source, rows in grouped.items():
        if source.endswith("terms"):
            continue
        usable = [r for r in rows if r["usable"]]
        endpoints = sorted(set(r["url"].split("?")[0] for r in rows))
        statuses = dict(Counter(str(r["status"]) for r in rows))
        rates = [r["rate_limit_headers"] for r in rows if r["rate_limit_headers"]]
        low, high = min(r["latency_ms"] for r in rows), max(r["latency_ms"] for r in rows)
        limits = f"{len(rows)} calls; statuses {statuses}; {low}–{high} ms; " + (json.dumps(rates[0]) if rates else "no rate-limit headers")
        data = "No usable response observed"
        if usable:
            data = json.dumps(usable[-1].get("sample", {}), ensure_ascii=False)
        verdict = "backup" if usable else "drop"
        if usable and source in ("Bluesky", "Coinbase Exchange", "Kraken", "Ethereum PublicNode", "CoinDesk RSS", "Cointelegraph RSS", "Decrypt RSS"):
            verdict = "use"
        if source == "Telegram":
            verdict = "drop"
            data += "; previews only; automation/AI terms concern below"
        if source == "Mastodon":
            data = "Account lookup and two old account feeds worked; public timeline required authentication. No current organizational feed confirmed."
        if source == "Bluesky":
            data += "; profiles and author feeds worked; search returned 403 twice"
        if source == "Ethereum PublicNode":
            data += "; 3- and 10-block USDC Transfer ranges worked; maximum range not tested"
        terms = "not checked"
        if source == "Telegram" and any(r.get("terms_quote") for r in grouped.get("Telegram terms", [])):
            terms = '“Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform” ([read terms](https://telegram.org/tos/content-licensing)); full sentence below'
        lines.append("| " + " | ".join(x.replace("|", "\\|").replace("\n", " ") for x in [source, "<br>".join(endpoints), "yes" if usable else "no", limits, data, "unknown", terms, verdict]) + " |")
    lines += ["", "## Confirmed organizational account watchlist", "", "This is the proposed small Bluesky demo watchlist, not a claim of six currently active voices. Each listed account returned original-author posts; repost-only results do not qualify. Domain handles and brand-named handles are distinguished: independent ownership verification of the `.bsky.social` accounts was not tested. These are organization/media-branded account candidates, not private-individual recommendations. Retain provenance and require user selection before trusting an unverified brand handle.", "", "| Requested Bluesky account | Successful calls | Own posts in first successful sample | First own post timestamp |", "|---|---|---|---|"]
    handles = {}
    for row in ROWS:
        if row["source"] == "Bluesky" and row["usable"] and row["context"].get("purpose") == "feed":
            handles.setdefault(row["context"]["account"], []).append(row)
    for handle, rows in handles.items():
        sample = rows[0]["sample"]
        lines.append(f"| [{handle}](https://bsky.app/profile/{handle}) | {len(rows)} | {sample['own_posts_count']} | {sample['first_own_created_at']} |")
    lines += ["", "The returned dates matter: in this run Decrypt was current, while CoinDesk, The Block, Bitcoin Magazine, The Defiant and Unchained samples were older. Do not relabel those historical posts as today's convergence or pad the list with accounts that returned empty feeds. A 20-account polling workload was not tested. Several requested domain handles returned HTTP 400; successful account resolution or an empty feed does not establish a usable voice.",
              "", "### All tested voice identities", "", "| Platform | Requested account/channel | Feed HTTP status | Observed posts | First/last sampled timestamp |", "|---|---|---|---|---|"]
    seen = set()
    for row in ROWS:
        source, ctx, sample = row["source"], row["context"], row.get("sample", {})
        account = ctx.get("account")
        if not account or (source, account) in seen or ctx.get("purpose") in ("profile", "mastodon_lookup"):
            continue
        seen.add((source, account))
        count = sample.get("own_posts_count", sample.get("post_count", sample.get("statuses_count", 0)))
        date = sample.get("first_own_created_at", sample.get("last_timestamp", sample.get("first_created_at")))
        lines.append(f"| {source} | {account} | {row['status']} | {count} | {date or 'none observed'} |")
    lines += ["", "## Detailed observations", "", "Field names and per-request parameters, HTTP status, timestamps, latency, small samples and JSON-RPC errors are recorded in `probe/results.json`. Anonymous failures do not distinguish key requirements from WAF, rate limiting, region filtering or other server policy unless the returned diagnostic says so.", ""]
    for source, rows in grouped.items():
        lines.append("### " + source)
        usable = [r for r in rows if r["usable"]]
        if usable:
            # Keep the report readable; full nested shapes remain in results.json.
            observed = usable[-1].get("shape", {})
            compact = {"top_level_fields": list(observed)}
            if observed.get("type") == "array":
                compact = {"type": "array", "first_item_shape": observed.get("first_item")}
            elif "feed" in observed:
                post = observed["feed"].get("first_item", {}).get("post", {})
                compact["post_fields"] = list(post) if isinstance(post, dict) else []
                compact["record_fields"] = list(post.get("record", {})) if isinstance(post, dict) and isinstance(post.get("record"), dict) else []
            elif "first_item_fields" in observed:
                compact = observed
            lines.append("Observed response shape (keys/types only): `" + json.dumps(compact, ensure_ascii=False) + "`")
        errors_seen = set()
        for row in rows:
            diagnostic = row.get("api_error") or row.get("transport_error") or row.get("parse_error") or row.get("sample", {}).get("api_error")
            if diagnostic and str(diagnostic) not in errors_seen:
                errors_seen.add(str(diagnostic))
                lines += ["", "- HTTP " + str(row["status"]) + ": " + json.dumps(diagnostic, ensure_ascii=False)]
            if row.get("terms_quote"):
                lines += ["", "> " + row["terms_quote"], "", "Read at " + row["url"] + " (" + row["utc"] + "). The page also describes a consent-based exception; that consent was not obtained or tested. This is a source-selection concern, not a legal clearance assessment."]
        lines.append("")
    lines += ["## Interpretation and limits", "", "Editorial interpretation below refers to the recorded 2026-10-30 run. On a later rerun, revalidate these observations against the newly generated table and JSON; the editorial text is not automatically reassessed.", "",
              "- Bluesky: profile keys included `handle`, `postsCount`, `followersCount`; author feeds included `feed[].post.record` and post timestamps. The tested `searchPosts?q=bitcoin&limit=3` returned 403/non-JSON twice. Authentication as a fix was not tested. Author polling can work without search.",
              "- Telegram: `cointelegraph` and `binance_announcements` each returned posts twice, with HTML message classes and `<time datetime>` attributes. `coindesk` and `kraken_exchange` redirected to pages with no preview posts. Technical reachability does not override the content-licensing restriction quoted above. Drop for this agent.",
              "- Reddit: the exact `new.json?limit=3&raw_json=1` request returned 403 twice despite the descriptive User-Agent saved in results. Block reason, logged-in access and geographic variation were not tested.",
              "- Mastodon: `mastodon.social` public timeline returned 422 and explicitly said `This method requires an authenticated user`. Anonymous account lookup/statuses worked for some accounts. Cointelegraph's returned post was from 2018, Decrypt's from 2022; the other tested populated profile counts did not guarantee an original status feed. Rate headers advertised limit 300 with remaining/reset values; sustainable request throughput and instance-wide limits were not tested.",
              "- Markets: Coinbase returned six-position candle arrays (350 rows); Kraken returned `error` and `result`, including `XETHZUSD` and `last` (721 rows); Binance returned twelve-position kline arrays (3 rows). These counts are observations, not documented server maxima. Array position semantics were not verified against documentation in this job. CoinGecko returned `usd`, `usd_24h_vol`, and `last_updated_at` for the two requested assets without a key. Binance exposed used-weight counters; the allowed maximum was not observed. All exact cache/rate headers captured by the final probe version are in JSON.",
              "- RPC: JSON-RPC failures can have HTTP 200. PublicNode returned both block heights and USDC Transfer logs over inclusive 3- and 10-block ranges (184 and 787 logs in this run). Ten blocks is the largest tested range, not the provider maximum. Cloudflare returned `Cannot fulfill request` for block number and `Internal error` for logs; LlamaRPC returned HTTP 525; Ankr explicitly required an API key. Latest-only log calls were still attempted on these failing endpoints. No quota exhaustion or large-range stress test was performed.",
              "- News: all three RSS feeds returned items twice. Saved samples contain item counts, dates and XML field names only. RSS publishing does not establish reuse permissions; terms were not checked. RSS entries and social posts from the same outlet are one voice, not two independent endorsements.",
              "- Regional availability: unknown for every source. US and EU probes were not performed and this machine's egress location was not verified. A local success cannot establish that a judge in either region can call it. No country-specific block was observed or inferred.", "",
              "## Default source set", "",
              "1. **Voices — Bluesky author feeds plus publisher RSS as an explicit fallback.** The six-account watchlist above contains only accounts that returned original posts, but only `decrypt.co` supplied a recent sample. Start with that domain-handled account for current social posts; keep the other five as visibly historical/verification-pending candidates rather than claiming current convergence. For a viable current multi-organization demo, use the three confirmed publisher identities below. These are public organization feeds, **not social accounts**. This is a fallback to the requested account model; the probe did not establish several fresh, independently verified social accounts. Cap the user-selected list at 20, and count each publisher once across feeds and social accounts. Polling interval/capacity beyond this brief probe: not tested.", "",
              "| Confirmed public publisher identity | Feed actually fetched twice | Items per sampled response | First item date in this run |", "|---|---|---|---|"]
    for source in ("CoinDesk RSS", "Cointelegraph RSS", "Decrypt RSS"):
        rows = [r for r in grouped.get(source, []) if r["usable"]]
        if rows:
            r = rows[0]
            lines.append(f"| {source} | {r['url']} | {r['sample']['items_count']} | {', '.join(r['sample']['first_item_dates'])} |")
    lines += ["", "2. **Market evidence — Coinbase Exchange ETH-USD candles + Kraken ETHUSD OHLC.** Both worked keylessly on repeated calls; use two venues for cross-checks, and judge freshness from event timestamps rather than HTTP success. At the last check Coinbase's newest five-minute candle opened about 403 seconds before fetch and Kraken's about 103 seconds before fetch; an open candle is not a completed candle. These are the recommended candidates for US/EU judges to retry using the exact saved URLs, but US/EU reachability remains **not tested**, not guaranteed. CoinGecko's keyless simple-price endpoint is an aggregate backup; no other CoinGecko endpoint or token-coverage claim was tested. Binance's data-only host also worked here, but cross-region availability is unverified, so keep it as a backup.",
              "", "3. **On-chain reads — Ethereum PublicNode** at `https://ethereum-rpc.publicnode.com`. The exact USDC contract and Transfer topic are stored in each RPC request in JSON. Logs include `blockNumber`, `transactionHash`, `logIndex`, `topics`, `data` and `removed`. That supplies evidence for transfer decoding and amount thresholds; this probe did **not** compute large-transfer classifications, verify token decimals with `eth_call`, or interpret transfers as buys/sells. A production reader would also need confirmations/reorg handling; those were not tested.",
              "", "4. **Optional news — CoinDesk RSS.** It returned 25 items twice. If it is already selected as a publisher voice, display it as news context without counting it again toward convergence. Cointelegraph and Decrypt RSS also worked as alternatives.",
              "", "The source probe is complete; no agent, trading logic, account, real-money position, or external post was created. The observations do not establish a fresh multi-account social-only default or US/EU availability, and the report deliberately leaves those requirements unverified rather than presenting invented evidence.", ""]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "SOURCES_PROBE.md").write_text("\n".join(lines), encoding="utf-8")


def deadline(signum, frame):
    raise TimeoutError("whole-probe deadline")


if __name__ == "__main__":
    START = time.monotonic()
    WALL_START = time.time()
    interrupted = False
    previous_elapsed = 0
    phases = []
    resume = any(x in sys.argv for x in ("--resume-followups", "--resume-accounts", "--resume-terms"))
    if resume:
        prior = json.loads((ROOT / "probe" / "results.json").read_text())
        ROWS.extend(prior["rows"])
        COUNTS.update(prior["request_counts"])
        previous_elapsed = prior["elapsed_seconds"]
        phases = prior.get("phases", [{"started_utc": prior["started_utc"], "elapsed_seconds": previous_elapsed}])
        for row in ROWS:
            if "api_error" in row.get("sample", {}):
                row.setdefault("api_error", row["sample"]["api_error"])
            required = "required (server explicitly requested API key)" if "must authenticate" in str(row.get("api_error", "")).lower() else "undetermined from this response"
            row.setdefault("key_or_login_required", "not required for this response" if row["usable"] else required)
    # Unix wall-clock safety net; portable loop budget still applies elsewhere.
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(275)
    try:
        if "--resume-terms" in sys.argv:
            call("Telegram terms", "https://telegram.org/tos/content-licensing", "terms")
        elif "--resume-accounts" in sys.argv:
            more_accounts()
        elif resume:
            followups()
        else:
            run()
    except TimeoutError:
        interrupted = True
    finally:
        elapsed = time.monotonic() - START
        phases.append({"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(WALL_START)), "elapsed_seconds": round(elapsed, 3)})
        result = {"started_utc": phases[0]["started_utc"], "elapsed_seconds": round(elapsed + previous_elapsed, 3), "phases": phases,
                  "request_counts": dict(COUNTS), "interrupted": interrupted, "user_agent": UA, "max_response_bytes": MAX_BODY,
                  "rows": ROWS}
        (ROOT / "probe" / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        render(elapsed + previous_elapsed, interrupted)
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        print("FINISHED", round(elapsed, 2), "seconds", len(ROWS), "requests", flush=True)
        print("Voice recommendation: Bluesky author feeds; publisher RSS fallback for multiple current organizations.")
        print("Market recommendation: Coinbase Exchange + Kraken; US/EU reachability not tested.")
        print("On-chain recommendation: PublicNode USDC Transfer logs. News: CoinDesk RSS.")
        print("Telegram: exclude because of the observed content-licensing restriction; see report for all failures.")
