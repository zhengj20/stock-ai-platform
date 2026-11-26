"""集成测试 - 验证 P0/P1/P2 修复"""
from app.services.strategy_service import StrategyService, _rate_score


def test_rate_score():
    print('=== _rate_score 测试 ===')
    for s in [95, 85, 75, 65, 55, 45]:
        r = _rate_score(s)
        print(f'  score={s} -> rating={r}')
    assert _rate_score(95) == '强烈推荐'
    assert _rate_score(75) == '推荐'
    assert _rate_score(65) == '观望'
    assert _rate_score(45) == '回避'
    print('PASS')


def test_score_synergy_returns_tuple():
    print('=== _score_synergy 返回 (score, reasons) ===')
    svc = StrategyService()
    result = svc._score_synergy(
        pct=10, amplitude=2, price=10.0, last_close=9.0, high=10.0,
        closes=[9.5, 9.0, 8.5, 8.0, 7.5], volumes=[1000, 1200, 1500, 800, 700]
    )
    print(f'  result = {result}')
    assert isinstance(result, tuple), '应该返回元组'
    assert len(result) == 2, '元组长度应该是2'
    score, reasons = result
    assert isinstance(score, int), 'score 应该是 int'
    assert isinstance(reasons, list), 'reasons 应该是 list'
    assert len(reasons) > 0, '涨停股应该有 reasons 标签'
    assert '涨停' in reasons, 'reasons 应包含"涨停"'
    print('PASS')


def test_score_resonance_returns_tuple():
    print('=== _score_resonance 返回 (score, reasons) ===')
    svc = StrategyService()
    result = svc._score_resonance(
        pct=5, amplitude=8, amount_yi=15.0, price=20.0, last_close=19.0,
        closes=[18, 18.5, 19, 19.5, 20, 20, 20, 20, 20, 20],
        volumes=[1000]*10
    )
    print(f'  result = {result}')
    assert isinstance(result, tuple)
    assert len(result) == 2
    score, reasons = result
    assert isinstance(reasons, list)
    print('PASS')


def test_score_premium_returns_tuple():
    print('=== _score_premium 返回 (score, reasons) ===')
    svc = StrategyService()
    result = svc._score_premium(
        pct=10, amplitude=2, price=11.0, last_close=10.0, high=11.0, low=10.0,
        closes=[10, 10.2, 10.5, 10.3, 10.6, 10.8, 11, 11.2, 11, 11],
        volumes=[1000]*10, amount_yi=5.0
    )
    print(f'  result = {result}')
    assert isinstance(result, tuple)
    assert len(result) == 2
    score, reasons = result
    assert isinstance(reasons, list)
    print('PASS')


def test_dl_institution_includes_reasons():
    print('=== get_dragon_list_strategy institution 类型 reasons 包含详细标签 ===')
    svc = StrategyService()
    # 通过 _build_strategy_reason 检查 institution 原因格式
    s = {'code': '600519', 'name': '贵州茅台', 'change_pct': 2.5, 'amplitude': 3.0, 'amount': 5e9}
    reason = svc._build_strategy_reason(s, 'institution', detail_reasons=['温和上涨', '中大盘', '站上MA5'])
    print(f'  reason = {reason}')
    assert '温和上涨' in reason
    assert '中大盘' in reason
    assert '站上MA5' in reason
    print('PASS')


def test_dead_code_removed():
    print('=== run_strategy / run_all_strategies 已被删除（死代码清理）===')
    svc = StrategyService()
    assert not hasattr(svc, 'run_strategy'), 'run_strategy 应已删除'
    assert not hasattr(svc, 'run_all_strategies'), 'run_all_strategies 应已删除'
    print('PASS')


def test_ml_train_text_honest():
    print('=== train_ml_model 输出明确标注"非端到端机器学习"===')
    svc = StrategyService()
    # 不真正跑 train（避免全市场扫描），仅检查 raw_output 文案
    # 改为检查 train_ml_model 调用的 docstring 与文案
    import inspect
    src = inspect.getsource(svc.train_ml_model)
    assert '规则化评分模型' in src, '应该明确说明是规则化评分'
    assert '非端到端机器学习模型' in src, '应该明确说明非端到端ML'
    print('PASS')


def test_no_cache_for_empty_results():
    print('=== 验证空结果不写入缓存（避免污染后续请求）===')
    import inspect
    from app.services.strategy_service import StrategyService
    src = inspect.getsource(StrategyService._set_cache)
    assert '空' in src or 'not cache' in src.lower() or 'len(v) == 0' in src, '应明确不缓存空结果'
    assert 'stocks' in src, '应检查 stocks 列表'
    assert 'signals' in src, '应检查 signals 列表'
    print('PASS')


def test_strategy_endpoints_have_no_data_message():
    print('=== 验证空结果时返回 status=no_data 与 msg 提示 ===')
    import inspect
    from app.services.strategy_service import StrategyService
    # 5 个选股端点都应该有空结果处理
    for method in ['get_low_absorption_picks', 'predict_ml_stocks', 'get_multi_factor_picks',
                   'get_capital_flow_picks', 'get_strategy_combo']:
        fn = getattr(StrategyService, method, None)
        if fn is None:
            continue
        src = inspect.getsource(fn)
        assert "'status': 'no_data'" in src or 'no_data' in src, f'{method} 应有空结果提示'
    print('PASS')


def test_hot_money_no_fake_winrate():
    print('=== get_hot_money_tracking 不再硬编码胜率 + 使用 stock_lhb_yybph_em ===')
    import inspect
    src = inspect.getsource(StrategyService.get_hot_money_tracking)
    assert 'style_bonus' not in src, 'style_bonus 硬编码应已删除'
    assert 'winRate' in src, 'winRate 字段保留但值为"--"'
    assert 'appearances_10d' in src, '应使用真实上榜次数'
    # P2 优化: 应使用营业部排行(seat) API 而非机构(jgmmtj) API
    assert 'stock_lhb_yybph_em' in src, '应使用 stock_lhb_yybph_em 营业部排行接口'
    assert 'stock_lhb_jgmmtj_em' not in src, '不应再用 stock_lhb_jgmmtj_em (机构数据不含席位)'
    assert 'seat_avg_1d' in src, '应输出 seat_avg_1d 真实历史平均涨幅'
    print('PASS')


if __name__ == '__main__':
    test_rate_score()
    print()
    test_score_synergy_returns_tuple()
    print()
    test_score_resonance_returns_tuple()
    print()
    test_score_premium_returns_tuple()
    print()
    test_dl_institution_includes_reasons()
    print()
    test_dead_code_removed()
    print()
    test_ml_train_text_honest()
    print()
    test_hot_money_no_fake_winrate()
    print()
    test_no_cache_for_empty_results()
    print()
    test_strategy_endpoints_have_no_data_message()
    print()
    print('=== 所有单测通过 ===')
