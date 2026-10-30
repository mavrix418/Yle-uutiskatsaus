import datetime as dt
import json
import os
import re
from pathlib import Path

import feedparser
import requests

FEEDS = {
    'Pääuutiset': 'https://yle.fi/rss/uutiset/paauutiset',
    'Kotimaa': 'https://yle.fi/rss/t/18-34837/fi',
    'Ulkomaat': 'https://yle.fi/rss/t/18-34953/fi',
    'Politiikka': 'https://yle.fi/rss/t/18-38033/fi',
    'Talous': 'https://yle.fi/rss/t/18-19274/fi',
    'Tiede': 'https://yle.fi/rss/t/18-819/fi',
    'Urheilu': 'https://yle.fi/rss/urheilu',
    'Tuoreimmat': 'https://yle.fi/rss/uutiset/tuoreimmat',
}

def clean(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', s or '')).strip()

now = dt.datetime.now(dt.timezone.utc)
cutoff = now - dt.timedelta(hours=24)
items = {}
for category, url in FEEDS.items():
    try:
        response = requests.get(url, timeout=20, headers={'User-Agent': 'PersonalNewsReader/1.0'})
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        for e in feed.entries:
            stamp = e.get('published_parsed') or e.get('updated_parsed')
            if not stamp:
                continue
            import calendar
            published = dt.datetime.fromtimestamp(calendar.timegm(stamp), dt.timezone.utc)
            if published < cutoff or published > now:
                continue
            title = clean(e.get('title'))
            if not title or re.search(r'kulttuuri|viihde|julkkis', title, re.I):
                continue
            link = e.get('link', '')
            if not link.startswith('https://yle.fi/'):
                continue
            key = link.split('?')[0]
            if key not in items:
                items[key] = {'title': title, 'description': clean(e.get('summary'))[:550], 'url': key, 'category': category, 'published': published.isoformat()}
    except Exception as exc:
        print(f'Feed failed {category}: {exc}')

articles = sorted(items.values(), key=lambda x: x['published'], reverse=True)[:180]
if not articles:
    raise RuntimeError('No recent articles found; keeping previous edition')

key = os.environ['GEMINI_API_KEY']
model = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
prompt = '''Laadi suomenkielinen radiouutiskatsaus annetusta Ylen RSS-aineistosta.
Valitse päivän merkittävyyden perusteella 20–40 erillistä uutistapahtumaa: hiljaisena päivänä noin 20, tavallisena 25–30 ja poikkeuksellisen vilkkaana jopa 40. Jos aineistossa ei ole 20 erillistä, olennaista uutista, valitse vain saatavilla olevat; älä keksi tai täytä vanhoilla uutisilla. Huomioi kotimaa, ulkomaat, politiikka, talous, teknologia/tiede ja urheilu, jos aineistossa on relevantteja uutisia. Jätä kulttuuri, viihde ja julkkisaiheet pois. Yhdistä saman tapahtuman päällekkäiset uutiset ja suosi tärkeimpiä tapahtumia.
Kirjoita neutraalisti ja selkeästi ääneen luettavaksi. Tavoittele noin 100–150 sanaa per uutinen VAIN, jos annetuissa otsikoissa ja RSS-kuvauksissa on siihen riittävästi tietoa. Jos tietoja on vähän, kirjoita lyhyemmin; älä toista samoja asioita, keksi faktoja, taustoja, seurauksia tai lainauksia. Kerro epävarmuuksista. Kirjoita myös lisäselitys, jos aineisto antaa siihen lisätietoja; älä toista uutistekstiä vain pituuden vuoksi. Älä lainaa pitkiä tekstikatkelmia. Älä esitä lisäselitystä alkuperäisen koko artikkelin lukemisena.
Palauta VAIN JSON-olio: {"stories":[{"url":"täsmälleen yksi syötteen url","script":"ääneen luettava uutinen ilman otsikon toistoa","more":"mahdollinen lisäselitys"}]}. Käytä vain syötteessä esiintyviä url-arvoja.
Aineisto:\n''' + json.dumps(articles, ensure_ascii=False)

endpoint = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
response = requests.post(endpoint, headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, json={
    'contents': [{'parts': [{'text': prompt}]}],
    'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.2}
}, timeout=120)
response.raise_for_status()
raw = response.json()['candidates'][0]['content']['parts'][0]['text']
parsed = json.loads(raw)
by_url = {a['url']: a for a in articles}
stories = []
for s in parsed.get('stories', []):
    a = by_url.get(s.get('url'))
    if a and s.get('script'):
        stories.append({**a, 'script': s['script'], 'more': s.get('more', '')})
if not stories:
    raise RuntimeError('Gemini did not return usable stories')
Path('docs').mkdir(exist_ok=True)
Path('docs/news.json').write_text(json.dumps({'generated': now.isoformat(), 'stories': stories}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Created {len(stories)} stories')
