"""Record HTTP shapes for tests only; erase all publisher prose before saving."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .common import sha


def save_recording(directory, key, source, endpoint, payload, body, status, headers, stamp, parsed=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if source.startswith('rss:'):
        original = ET.fromstring(body)
        root = ET.Element('rss'); channel = ET.SubElement(root,'channel')
        for entry in list(original.iter('item')) + list(original.iter('{http://www.w3.org/2005/Atom}entry')):
            item = ET.SubElement(channel,'item')
            ET.SubElement(item,'title').text = ''
            for child in entry:
                name = child.tag.split('}')[-1]
                if name in ('pubDate','published','updated'):
                    ET.SubElement(item,'pubDate').text = child.text
                elif name in ('link','guid','id'):
                    ET.SubElement(item,name).text = child.text or child.get('href','')
        sanitized = ET.tostring(root,encoding='unicode')
    elif source.startswith('bluesky:'):
        original = json.loads(body)
        feed=[]
        for item in original.get('feed',[]):
            p=item['post']; record=p['record']
            safe={'post':{'uri':p['uri'], 'author':{'handle':p['author']['handle']},
                         'record':{'createdAt':record['createdAt'],'text':''}}}
            if item.get('reason'):
                safe['reason']={'$type':item['reason'].get('$type','repost')}
            feed.append(safe)
        sanitized=json.dumps({'feed':feed,'cursor':original.get('cursor')})
    else:
        sanitized=body.decode()
    result=dict(recorded_test_fixture=True, redaction='Publisher prose removed; never use as demo data.',
                source=source,endpoint=endpoint,payload=payload,status=status,
                headers={k:v for k,v in headers.items() if k.lower() in ('retry-after','content-type')},
                fetch_time=stamp, original_response_sha256=sha(body),body=sanitized)
    if source.startswith(('rss:', 'bluesky:')) and parsed is not None:
        rows = parsed if isinstance(parsed, list) else parsed.get('rows', [])
        result['post_features'] = {r['uri']: {k:r[k] for k in ('features', 'content_sha256', 'title_sha256')} for r in rows}
    (directory/(key+'.json')).write_text(json.dumps(result,indent=2)+'\n')
