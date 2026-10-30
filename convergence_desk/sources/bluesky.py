"""Public author feeds, original author posts only; bounded cursor pagination."""
import json
from urllib.parse import urlencode
from .common import dt
from .voices import prepare, batch


def fetch(client, voice, start, as_of):
    rows = []
    cursor = None
    seen = set()
    for _ in range(5):
        params = dict(actor=voice['bluesky'], limit=100, filter='posts_no_replies')
        if cursor:
            params['cursor'] = cursor
        endpoint = 'https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?' + urlencode(params)
        def parse(body, provenance):
            data = json.loads(body)
            if data.get('error'):
                raise ValueError('Bluesky: ' + str(data['error']))
            page = []
            oldest = None
            for item in data.get('feed', []):
                post = item['post']
                if item.get('reason') or post['author']['handle'].lower() != voice['bluesky'].lower():
                    continue
                created = dt(post['record']['createdAt'])
                oldest = min(oldest, created) if oldest else created
                if start <= created <= as_of:
                    page.append(prepare(voice, post['uri'], created, post['record'].get('text', ''), '', provenance, post['author']['handle']))
            return dict(rows=page, cursor=data.get('cursor'), older_than_window=oldest is not None and oldest < start)
        page = client.fetch('bluesky:' + voice['voice_id'], endpoint, parse)
        rows.extend(page['rows'])
        cursor = page['cursor']
        if page['older_than_window'] or not cursor or cursor in seen:
            break
        seen.add(cursor)
    return batch(list({row['uri']: row for row in rows}.values()))
