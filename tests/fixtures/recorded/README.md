# Recorded HTTP test fixtures — not demo data

Captured by the real live run on 2026-10-30, plus a separate keyless CoinGecko
OHLC request. These are **test fixtures only**, never default/demo inputs.
No fabricated posts, prices or chain logs are included.

Each file has the exact request URL / RPC payload, fetch time, status, and an
original response SHA-256. Publisher prose, descriptions, embeds and profiles
are erased. RSS keeps dates and URIs; Bluesky keeps original-author identities,
dates, URIs and repost markers. `post_features` contains the actual extraction
scores/rule traces and content/title hashes recorded during that live run; it
contains no article or post prose. This lets offline integration tests exercise
the full decision path without retaining copyrighted text. Error responses
retain their observed HTTP status but discard their bodies.

The fixture transport never falls through to a live HTTP request. Fixture
reports carry a prominent test-only label. The manifest freezes the clock and
configuration; it does not claim that these historical observations are live.
