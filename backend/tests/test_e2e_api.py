"""端到端 API 验证脚本"""
import urllib.request
import json
import time

ENDPOINTS = [
    ('strategy/multi-factor-picks', '?top_n=3&refresh=true', 'stocks'),
    ('strategy/low-absorption-picks', '?top_n=3&refresh=true', 'stocks'),
    ('strategy/capital-flow-picks', '?top_n=3&refresh=true', 'stocks'),
    ('strategy/combo', '?top_n=3&mode=vote&refresh=true', 'stocks'),
    ('ml/predict', '?top_n=3&refresh=true', 'stocks'),
    ('dragon/strategy', '?strategy_type=institution&top_n=3&refresh=true', 'stocks'),
    ('dragon/strategy', '?strategy_type=synergy&top_n=3&refresh=true', 'stocks'),
    ('dragon/strategy', '?strategy_type=resonance&top_n=3&refresh=true', 'stocks'),
    ('dragon/strategy', '?strategy_type=premium&top_n=3&refresh=true', 'stocks'),
    ('strategy/comparison', '?refresh=true', 'signals'),
    ('dragon/hot-money', '', 'hot_money'),
    ('dragon/sector-analysis', '?refresh=true', 'sectors'),
    ('dragon/consecutive', '?days=5', 'consecutive'),
]

print('===== 端到端 API 测试 =====')
for name, qs, expected in ENDPOINTS:
    url = f'http://localhost:8002/api/v1/{name}{qs}'
    try:
        start = time.time()
        with urllib.request.urlopen(url, timeout=180) as r:
            data = json.loads(r.read().decode('utf-8'))
        elapsed = time.time() - start
        status = data.get('status', '?')

        if expected in data:
            arr = data[expected]
            n = len(arr) if isinstance(arr, list) else 0
            extra = ''
            if n > 0 and isinstance(arr, list):
                first = arr[0]
                if 'rating' in first:
                    extra = f" rating={first.get('rating')}"
                if 'reasons' in first:
                    r0 = first['reasons']
                    extra += f" reasons={r0 if not isinstance(r0, list) else r0[:2]}"
                if 'winRate' in first:
                    extra += f" winRate={first.get('winRate')}"
                if 'appearances_10d' in first:
                    extra += f" app10d={first.get('appearances_10d')} avg1d={first.get('seat_avg_1d')}"
            print(f"[{name}?...] {elapsed:.1f}s status={status} {expected}={n}{extra}")
        else:
            keys = list(data.keys())[:5]
            print(f"[{name}?...] {elapsed:.1f}s status={status} keys={keys} (no {expected})")
    except urllib.error.HTTPError as e:
        print(f"[{name}?...] HTTP {e.code}: {e.reason}")
    except Exception as e:
        print(f"[{name}?...] ERROR: {type(e).__name__}: {e}")

print('\n===== 端到端测试完成 =====')
