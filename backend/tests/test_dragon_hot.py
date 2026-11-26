"""dragon strategy + hot money 验证"""
import urllib.request
import json

ENDPOINTS = [
    ('dragon/strategy?strategy_type=institution&top_n=3&refresh=true', 'institution'),
    ('dragon/strategy?strategy_type=synergy&top_n=3&refresh=true', 'synergy'),
    ('dragon/strategy?strategy_type=resonance&top_n=3&refresh=true', 'resonance'),
    ('dragon/strategy?strategy_type=premium&top_n=3&refresh=true', 'premium'),
    ('dragon/hot-money', 'hot_money'),
]

for path, label in ENDPOINTS:
    url = f'http://localhost:8002/api/v1/{path}'
    try:
        r = urllib.request.urlopen(url, timeout=60)
        d = json.loads(r.read().decode('utf-8'))
        s = d.get('stocks', [])
        first = s[0] if s else None
        print(f'[{label}] status={d.get("status")} count={len(s)}')
        if first:
            print(f'  first code={first.get("code")} name={first.get("name")} score={first.get("score")} rating={first.get("rating")} reason={first.get("reason")}')
    except Exception as e:
        print(f'[{label}] ERROR: {e}')

# 单独检查 hot_money
print()
print('--- hot money 详细 ---')
r = urllib.request.urlopen('http://localhost:8002/api/v1/dragon/hot-money', timeout=60)
d = json.loads(r.read().decode('utf-8'))
for hm in d.get('hot_money', []):
    print(f'  {hm["name"]} | 风格={hm["style"]} | 近10日上榜={hm.get("appearances_10d")}次 | 胜率={hm.get("winRate")}')
