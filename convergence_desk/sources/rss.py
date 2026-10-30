"""RSS/Atom publisher voices; only titles and summaries are read transiently."""
from datetime import timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from .common import dt
from .voices import prepare, batch, clean


def fetch(client, voice, start, as_of):
    source = 'rss:' + voice['voice_id']
    def parse(body, provenance):
        root = ET.fromstring(body)
        rows = []
        for item in list(root.iter('item')) + list(root.iter('{http://www.w3.org/2005/Atom}entry')):
            fields = {el.tag.split('}')[-1]: el for el in item}
            def text(name):
                return ''.join(fields[name].itertext()) if name in fields else ''
            stamp = text('pubDate') or text('published') or text('updated')
            if not stamp:
                continue
            try:
                created = parsedate_to_datetime(stamp).astimezone(timezone.utc)
            except (ValueError, TypeError):
                created = dt(stamp)
            if not start <= created <= as_of:
                continue
            uri = text('link') or (fields['link'].get('href') if 'link' in fields else '') or text('guid') or text('id')
            if not uri:
                continue
            title = clean(text('title'))
            summary = clean(text('description') or text('summary'))
            rows.append(prepare(voice, uri, created, title + ('\n' + summary if summary else ''), title, provenance, voice['label']))
        return list({row['uri']: row for row in rows}.values())
    return batch(client.fetch(source, voice['rss'], parse))
