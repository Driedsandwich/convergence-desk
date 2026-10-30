"""Freshness probe; stores dates/counts/hashes only, never publisher text."""
import urllib.request, urllib.parse, json, time, hashlib
import xml.etree.ElementTree as E
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

def main():
    now=datetime.now(timezone.utc)
    candidates=[('coindesk','CoinDesk','https://www.coindesk.com/arc/outboundfeeds/rss/'),('cointelegraph','Cointelegraph','https://cointelegraph.com/rss'),('decrypt','Decrypt','https://decrypt.co/feed'),('theblock','The Block','https://www.theblock.co/rss.xml'),('blockworks','Blockworks','https://blockworks.co/feed'),('bitcoinmagazine','Bitcoin Magazine','https://bitcoinmagazine.com/feed'),('cryptoslate','CryptoSlate','https://cryptoslate.com/feed/'),('thedefiant','The Defiant','https://thedefiant.io/feed'),('bitcoinist','Bitcoinist','https://bitcoinist.com/feed/'),('newsbtc','NewsBTC','https://www.newsbtc.com/feed/'),('beincrypto','BeInCrypto','https://beincrypto.com/feed/'),('cryptopotato','CryptoPotato','https://cryptopotato.com/feed/'),('utoday','U.Today','https://u.today/rss'),('cryptonews','Cryptonews','https://cryptonews.com/news/feed/'),('unchained','Unchained','https://unchainedcrypto.com/feed/'),('dailyhodl','The Daily Hodl','https://dailyhodl.com/feed/'),('protos','Protos','https://protos.com/feed/'),('dlnews','DL News','https://www.dlnews.com/arc/outboundfeeds/rss/'),('ambcrypto','AMBCrypto','https://ambcrypto.com/feed/'),('cryptobriefing','Crypto Briefing','https://cryptobriefing.com/feed/')]
    rows=[]; voices=[]
    for vid,label,url in candidates:
        row=dict(voice_id=vid,label=label,endpoint=url,fetch_time=now.isoformat(),kind='rss')
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'ConvergenceDesk/0.1 (open-source hackathon public-feed freshness probe; no credentials)'})
            with urllib.request.urlopen(req,timeout=6) as r:
                body=r.read(2_000_001); row['http_status']=r.status
            if len(body)>2_000_000: raise ValueError('response exceeds 2 MB limit')
            row['content_sha256']=hashlib.sha256(body).hexdigest()
            root=E.fromstring(body); dates=[]
            for item in list(root.iter('item'))+list(root.iter('{http://www.w3.org/2005/Atom}entry')):
                stamp=next((el.text for el in item if el.tag.split('}')[-1] in ('pubDate','published','updated') and el.text),None)
                if not stamp: continue
                try: date=parsedate_to_datetime(stamp)
                except ValueError: date=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
                dates.append(date)
            recent=[d for d in dates if now-timedelta(days=7)<=d<=now]
            row.update(items=len(dates),recent_items=len(recent),newest=max(dates).isoformat() if dates else None)
            if recent: voices.append(dict(voice_id=vid,label=label,trust_weight=0.8,rss=url))
        except Exception as e: row['error']=str(e)[:200]
        rows.append(row); print(json.dumps(row),flush=True); time.sleep(.2)
    for handle,vid in [('decrypt.co','decrypt'),('coindesk.com','coindesk'),('theblock.bsky.social','theblock'),('bitcoinmagazine.bsky.social','bitcoinmagazine'),('thedefiant.bsky.social','thedefiant'),('unchainedcrypto.bsky.social','unchained')]:
        url='https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?'+urllib.parse.urlencode(dict(actor=handle,limit=50,filter='posts_no_replies'))
        row=dict(voice_id=vid,endpoint=url,kind='bluesky',handle=handle,fetch_time=now.isoformat())
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ConvergenceDesk/0.1 (public author freshness probe)'}),timeout=6) as r:
                body=r.read(2_000_000); row['http_status']=r.status
            row['content_sha256']=hashlib.sha256(body).hexdigest(); data=json.loads(body)
            dates=[datetime.fromisoformat(x['post']['record']['createdAt'].replace('Z','+00:00')) for x in data.get('feed',[]) if not x.get('reason') and x['post']['author']['handle']==handle]
            recent=[d for d in dates if now-timedelta(days=7)<=d<=now]
            row.update(original_posts=len(dates),recent_items=len(recent),newest=max(dates).isoformat() if dates else None)
            if recent:
                v=next((v for v in voices if v['voice_id']==vid),None)
                if v: v['bluesky']=handle
                elif len(voices)<20: voices.append(dict(voice_id=vid,label=vid,trust_weight=.8,bluesky=handle))
        except Exception as e: row['error']=str(e)[:200]
        rows.append(row); print(json.dumps(row),flush=True); time.sleep(.2)
    Path('probe/expanded_sources.json').write_text(json.dumps(dict(as_of=now.isoformat(),rows=rows),indent=2)+'\n')
    Path('convergence_desk/config/default_voices.json').write_text(json.dumps(dict(voices=voices),indent=2)+'\n')
if __name__=='__main__': main()
