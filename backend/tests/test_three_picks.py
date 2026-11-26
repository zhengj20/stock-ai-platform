"""单独测试 3 个 picks API"""
import urllib.request
import json

for ep in ['multi-factor-picks', 'low-absorption-picks', 'capital-flow-picks']:
    url = f'http://localhost:8002/api/v1/strategy/{ep}?top_n=3&refresh=true'
    try:
        r = urllib.request.urlopen(url, timeout=180)
        d = json.loads(r.read().decode('utf-8'))
        s = d.get('stocks', [])
        first = s[0] if s else None
        print(f'[{ep}] status={d.get("status")} count={len(s)}')
        if first:
            print(f'  first code={first.get("code")} name={first.get("name")} score={first.get("score")} rating={first.get("rating")}')
    except urllib.error.HTTPError as e:
        print(f'[{ep}] HTTP {e.code}: {e.reason}')
    except Exception as e:
        print(f'[{ep}] ERROR: {type(e).__name__}: {e}')
