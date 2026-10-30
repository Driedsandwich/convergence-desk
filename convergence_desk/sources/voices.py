"""Transient extraction: full text is never returned to disk serializers."""
from dataclasses import asdict
from html import unescape
import re
from convergence_desk.core.extract import extract
from convergence_desk.core.models import Post
from .common import Batch, dt, iso, sha


def clean(text):
    return ' '.join(unescape(re.sub('<[^>]+>', ' ', text or '')).split())


def prepare(voice, uri, created_at, text, title, provenance, author):
    post = Post('voices', voice['voice_id'], voice['label'], uri, created_at, text)
    features = []
    for signal in extract(post):
        features.append({k: v for k, v in asdict(signal).items() if k != 'post'})
    return dict(source='voices', author_id=voice['voice_id'], author_label=voice['label'],
                author=author, uri=uri, created_at=iso(created_at), excerpt=text[:140],
                content_sha256=post.content_sha256, title_sha256=sha(title), features=features,
                provenance={**provenance, 'identity': uri, 'content_sha256': post.content_sha256})


def batch(rows):
    posts = tuple(Post('voices', r['author_id'], r['author_label'], r['uri'], dt(r['created_at']), r['excerpt']) for r in rows)
    return Batch(posts, tuple(r['provenance'] for r in rows),
                 {r['uri']: r['features'] for r in rows}, {r['uri']: r for r in rows})
