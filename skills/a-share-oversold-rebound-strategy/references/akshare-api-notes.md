# akshare 数据接口使用笔记

## 非交易时段行为（关键）

东方财富行情接口在非交易时段会直接断开连接：

```
RemoteDisconnected('Remote end closed connection without response')
```

**不是网络故障**，是服务端主动关闭。脚本通过 `api_call()` 重试包装器处理（3次指数退避），但连续失败仍抛 `RuntimeError`。

**验证方法**: `python a_share_overshot.py test` — 非交易时段会看到 ✗ 标记，属正常现象。

## 列名映射表

akshare 返回的 DataFrame 使用中文列名，脚本需标准化为英文：

| 原始列名 | 标准列名 | 用途 |
|---------|---------|------|
| 代码 | code | 股票代码 |
| 名称 | name | 股票名称 |
| 最新价 | price | 当前价格 |
| 涨跌幅 | pct_change | 当日涨跌幅(%) |
| 涨跌额 | change_amt | 当日涨跌额(元) |
| 成交量 | volume | 成交量(手) |
| 成交额 | turnover | 成交额(元) |
| 振幅 | amplitude | 振幅(%) |
| 最高 | high | 日内最高价 |
| 最低 | low | 日内最低价 |
| 今开 | open_price | 今日开盘价 |
| 昨收 | prev_close | 昨日收盘价 |
| 换手率 | turnover_rate | 换手率(%) |
| 流通市值 | circ_market_cap | 流通市值(元) |
| 总市值 | total_market_cap | 总市值(元) |
| 市盈率-动态 | pe_dynamic | 动态PE |
| 市净率 | pb | PB |

**注意**: akshare 版本更新可能废弃旧列名或新增列名。`_find_pct_column()` 函数做了多候选回退（`pct_change → 涨跌幅 → change_pct`）。

## 关键接口速查

| 接口 | 参数 | 返回 | 备注 |
|------|------|------|------|
| `stock_zh_a_spot_em()` | 无 | DataFrame(全市场) | ~5000行，含所有A股实时数据 |
| `stock_zh_index_spot_em()` | 无 | DataFrame(指数) | 上证/深证/创业板等 |
| `stock_zh_a_minute(symbol, period)` | symbol: str, period: "1"\|"5"\|"15" | DataFrame | 当日分时K线，收盘后可能为空 |
| `stock_zh_a_hist(symbol, period, start_date, end_date, adjust)` | 见签名 | DataFrame | 日/周/月K历史数据 |
| `tool_trade_date_hist_sina()` | 无 | DataFrame | 交易日历，含节假日 |
| `stock_individual_info_em(symbol)` | symbol: str | DataFrame(2列) | 个股基本信息（行业等） |
| `stock_board_industry_cons_em(symbol)` | symbol: str | DataFrame | 板块成分股反查 |

## 性能注意事项

- `stock_zh_a_spot_em()` 单次返回全市场 ~5000 只股票，耗时约 1-3s
- `stock_zh_a_minute()` + `stock_zh_a_hist()` 需逐只调用，每条约 0.5-2s
- 脚本限制深度检查最多 30 只（`deep_check_limit=30`），避免超时
- akshare 无官方速率限制文档，经验值：每秒不超过 10 次独立请求较安全
