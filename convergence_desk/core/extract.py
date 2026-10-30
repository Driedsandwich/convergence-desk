"""Small, auditable lexicons; scores describe text, never probabilities."""

import re
from typing import Tuple

from .models import Post, Score, Signal


TOKEN_NAMES = {
    "BTC": ("bitcoin",), "ETH": ("ethereum", "ether"), "SOL": ("solana",),
    "BNB": ("binance coin",), "XRP": ("ripple",), "ADA": ("cardano",),
    "DOGE": ("dogecoin",), "AVAX": ("avalanche",), "DOT": ("polkadot",),
    "LINK": ("chainlink",), "MATIC": ("polygon",), "POL": ("polygon ecosystem token",),
    "LTC": ("litecoin",), "BCH": ("bitcoin cash",), "ATOM": ("cosmos",),
    "UNI": ("uniswap",), "AAVE": ("aave",), "MKR": ("makerdao",),
    "DAI": ("dai",), "USDT": ("tether",), "USDC": ("usd coin",),
    "TON": ("toncoin",), "TRX": ("tron",), "XLM": ("stellar",),
    "XMR": ("monero",), "ETC": ("ethereum classic",), "FIL": ("filecoin",),
    "ICP": ("internet computer",), "NEAR": ("near protocol",), "APT": ("aptos",),
    "ARB": ("arbitrum",), "OP": ("optimism",), "SUI": ("sui",),
    "INJ": ("injective",), "SEI": ("sei",), "TIA": ("celestia",),
    "RENDER": ("render token",), "FET": ("fetch.ai",), "SHIB": ("shiba inu",),
    "PEPE": ("pepe",), "ONE": ("harmony",), "GAS": (),
}
# Common English words are never bare-symbol matches, even when uppercase.
AMBIGUOUS_SYMBOLS = {"ONE", "GAS", "NEAR", "LINK", "ATOM", "UNI", "DOT", "OP", "APT", "TON", "ETC", "RENDER"}
BULLISH = ("bullish", "buy", "buying", "long", "accumulate", "breakout", "rally", "undervalued", "upside")
BEARISH = ("bearish", "sell", "selling", "short", "dump", "breakdown", "overvalued", "downside", "crash")
STRONG = ("definitely", "certain", "strong conviction", "high conviction", "confident", "will", "guaranteed")
HEDGES = ("maybe", "might", "could", "perhaps", "uncertain", "if", "possibly", "not sure")
URGENT = ("now", "breaking", "today", "immediately", "urgent", "this hour", "soon")


def _matches(text: str, word: str):
    return re.finditer(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.IGNORECASE)


def _mentions(text: str):
    candidates = []
    for match in re.finditer(r"(?<!\w)\$([A-Za-z][A-Za-z0-9]{1,9})\b", text):
        candidates.append((match.start(), match.end(), match.group(1).upper(), "cashtag:" + match.group(0)))
    for token, names in TOKEN_NAMES.items():
        for name in names:
            for match in _matches(text, name):
                candidates.append((match.start(), match.end(), token, "name:" + name))
        if token not in AMBIGUOUS_SYMBOLS:
            for match in _matches(text, token):
                candidates.append((match.start(), match.end(), token, "symbol:" + token))
    # Long names win overlaps: "bitcoin cash" must not also mention BTC.
    chosen = []
    for candidate in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0], item[2])):
        if not any(candidate[0] < other[1] and other[0] < candidate[1] for other in chosen):
            chosen.append(candidate)
    return sorted(chosen)


def _scores(text: str) -> Tuple[str, Score, Score, Score]:
    sentiment = 0.0
    sentiment_trace = []
    for words, sign in ((BULLISH, 1), (BEARISH, -1)):
        for word in words:
            for match in _matches(text, word):
                prefix_text = re.split(r"[,;:]", text[:match.start()])[-1]
                prefix = re.findall(r"\b\w+\b", prefix_text.lower())[-3:]
                negated = any(w in ("not", "never", "no") for w in prefix)
                delta = 0.4 * sign * (-1 if negated else 1)
                sentiment += delta
                sentiment_trace.append(f"sentiment:{'negated:' if negated else ''}{word}:{delta:+.2f}")
    sentiment = round(max(-1.0, min(1.0, sentiment)), 10)
    direction = "bullish" if sentiment > 0 else "bearish" if sentiment < 0 else "neutral"
    conviction = 0.5
    conviction_trace = ["conviction:baseline:0.50"]
    for words, delta in ((STRONG, 0.15), (HEDGES, -0.2)):
        for word in words:
            for match in _matches(text, word):
                prefix = re.findall(r"\b\w+\b", text[:match.start()].lower())[-2:]
                applied = -abs(delta) if delta > 0 and "not" in prefix else delta
                conviction += applied
                conviction_trace.append(f"conviction:{word}:{applied:+.2f}")
    conviction = round(max(0.0, min(1.0, conviction)), 10)
    urgency_trace = [f"urgency:{word}:+0.25" for word in URGENT for _ in _matches(text, word)]
    urgency = min(1.0, len(urgency_trace) * 0.25)
    return (direction, Score(sentiment, tuple(sentiment_trace or ["sentiment:no_direction_words:0"])),
            Score(conviction, tuple(conviction_trace)),
            Score(urgency, tuple(urgency_trace or ["urgency:no_time_words:0"])))


def extract(post: Post) -> Tuple[Signal, ...]:
    """Score each token in its clause; contrast words separate opposing claims.

    Shared claims in a clause apply to each mentioned token. This intentionally
    simple parser does not infer sarcasm, pronouns, or multi-clause coreference.
    """
    signals = []
    # Avoid splitting decimal numbers and names such as fetch.ai at a dot.
    clauses = re.split(r"[!?;\n]+|\.(?=\s|$)|\b(?:but|whereas|while)\b", post.text, flags=re.IGNORECASE)
    for clause in clauses:
        mentions = _mentions(clause)
        direction, sentiment, conviction, urgency = _scores(clause)
        for token in sorted({m[2] for m in mentions}):
            traces = tuple(m[3] for m in mentions if m[2] == token)
            signals.append(Signal(post, token, direction, sentiment, conviction, urgency, traces))
    return tuple(signals)
