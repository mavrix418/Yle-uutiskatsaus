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

articles = sorted(items.values(), key=lambda x: x['published'], reverse=True)[:100]
if not articles:
    raise RuntimeError('No recent articles found; keeping previous edition')

key = os.environ['GEMINI_API_KEY']
model = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
prompt = '''Laadi suomenkielinen 5–10 minuutin radiouutiskatsaus annetusta Ylen RSS-aineistosta.
Valitse 10–16 tärkeintä ja erillistä uutista; mukana kotimaa, ulkomaat, politiikka, talous, teknologia/tiede ja urheilu, jos aineistossa on relevantteja uutisia. Älä valitse kulttuuria, viihdettä tai julkkisaiheita. Poista saman tapahtuman päällekkäiset uutiset.
Kirjoita neutraalisti ja ymmärrettävästi, noin 35–65 sanaa per uutinen. Käytä VAIN annettuja otsikoita ja RSS-kuvauksia, älä keksi yksityiskohtia. Jos kuvauksessa ei ole tietoa, älä täydennä arvauksella. Älä lainaa pitkiä tekstikatkelmia. Jokaiselle uutiselle myös noin 100–150 sanan lisäselitys, joka perustuu vain lähteen antamiin tietoihin; jos tietoa on niukasti, sano se. Älä esitä lisäselitystä alkuperäisen koko artikkelin lukemisena.
Palauta VAIN JSON-olio: {"stories":[{"url":"täsmälleen yksi syötteen url","script":"ääneen luettava uutinen","more":"lisäselitys"}]}. Käytä vain syötteessä esiintyviä url-arvoja.
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
