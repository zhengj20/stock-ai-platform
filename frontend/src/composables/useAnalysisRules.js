// ═══════════════════════════════════════════════════════════
// 评分分档 — 与后端 SCORE_THRESHOLDS 保持完全一致
// 后端 stock_service.py 顶部 SCORE_THRESHOLDS 常量是单一可信源
// ═══════════════════════════════════════════════════════════
export const CONCLUSION_LEVELS = [
  { min: 75, level: 'strong_bullish', type: 'bullish',        title: '强势偏多', text: '综合偏多，可逢低布局' },
  { min: 60, level: 'bullish',        type: 'slight_bullish', title: '偏多',     text: '整体偏多，可关注介入机会' },
  { min: 45, level: 'neutral',        type: 'neutral',        title: '中性',     text: '多空交织，建议观望等待明确信号' },
  { min: 30, level: 'bearish',        type: 'slight_bearish', title: '偏空',     text: '空头占优，建议控制仓位或回避' },
  { min: 0,  level: 'strong_bearish', type: 'bearish',        title: '弱势偏空', text: '多项指标偏空，建议谨慎操作' },
]

// 根据评分返回分档信息（与后端 get_score_level 对齐）
export function getScoreLevel(score) {
  if (score == null || isNaN(score)) {
    return { level: 'no_data', title: '数据不足', type: 'neutral', text: '数据不足，无法判断' }
  }
  return CONCLUSION_LEVELS.find(l => score >= l.min) || CONCLUSION_LEVELS[CONCLUSION_LEVELS.length - 1]
}

// 建议仓位：根据综合评分给出（P3 交互优化）
export function getPositionAdvice(score) {
  if (score == null || isNaN(score)) return { ratio: '--', text: '数据不足' }
  if (score >= 75) return { ratio: '60-80%', text: '可适度重仓' }
  if (score >= 60) return { ratio: '40-60%', text: '中等仓位' }
  if (score >= 45) return { ratio: '20-40%', text: '轻仓试探' }
  if (score >= 30) return { ratio: '0-20%',  text: '观望为主' }
  return { ratio: '0%',     text: '建议空仓回避' }
}

export const DIMENSION_GROUPS = [
  { key: 'trend', label: '均线趋势' },
  { key: 'macd', label: 'MACD' },
  { key: 'kdj', label: 'KDJ' },
  { key: 'rsi', label: 'RSI' },
  { key: 'boll', label: '布林带' },
  { key: 'volume', label: '量能' },
  { key: 'fundamental', label: '基本面' },
  { key: 'price', label: '今日盘面' },
]

export const ANALYSIS_RULES = [
  // ── 均线趋势 ──
  { key: 'trend', check: c => c.ma60 > 0 && c.price > c.ma5 && c.ma5 > c.ma20 && c.ma20 > c.ma60,
    text: () => '均线呈多头排列，短期趋势向上', score: +10 },
  { key: 'trend', check: c => c.ma60 > 0 && c.price < c.ma5 && c.ma5 < c.ma20 && c.ma20 < c.ma60,
    text: () => '均线空头排列，短期趋势向下', score: -10 },
  { key: 'trend', check: c => c.ma5 > c.ma20 && c.ma5 > 0,
    text: c => `MA5(${c.ma5.toFixed(2)})位于MA20(${c.ma20.toFixed(2)})之上，短期偏强`, score: +3 },
  { key: 'trend', check: c => c.ma5 < c.ma20 && c.ma5 > 0,
    text: c => `MA5(${c.ma5.toFixed(2)})位于MA20(${c.ma20.toFixed(2)})之下，短期偏弱`, score: -3 },
  // ── MACD ──
  { key: 'macd', check: c => /金叉/.test(c.macdSignal),
    text: () => 'MACD刚形成金叉，短线有上行动能', score: +8 },
  { key: 'macd', check: c => /死叉/.test(c.macdSignal),
    text: () => 'MACD已死叉，注意回调风险', score: -8 },
  { key: 'macd', check: c => !/金叉|死叉/.test(c.macdSignal) && /多头/.test(c.macdSignal),
    text: () => 'MACD维持多头格局', score: +5 },
  { key: 'macd', check: c => !/金叉|死叉/.test(c.macdSignal) && /空头/.test(c.macdSignal),
    text: () => 'MACD处于空头状态', score: -5 },
  // ── KDJ（阈值与后端 _calc_indicators 对齐：J>100 才算超买）──
  { key: 'kdj', check: c => c.kdjJ > 100,
    text: c => `KDJ-J(${c.kdjJ.toFixed(0)})>100进入超买区，短线回调概率大`, score: -6 },
  { key: 'kdj', check: c => c.kdjJ > 80 && c.kdjJ <= 100,
    text: c => `KDJ-J(${c.kdjJ.toFixed(0)})偏高，注意短期回调风险`, score: -3 },
  { key: 'kdj', check: c => c.kdjJ < 0,
    text: c => `KDJ-J(${c.kdjJ.toFixed(0)})<0深度超卖，存在反弹机会`, score: +6 },
  { key: 'kdj', check: c => c.kdjJ >= 0 && c.kdjJ < 20,
    text: c => `KDJ-J(${c.kdjJ.toFixed(0)})偏低，关注反弹信号`, score: +3 },
  { key: 'kdj', check: c => c.kdjJ >= 20 && c.kdjJ <= 80,
    text: () => 'KDJ处于中性区域，方向不明显', score: 0 },
  // ── RSI（阈值与后端 _calc_indicators 对齐：20/80 才算极值）──
  { key: 'rsi', check: c => c.rsi6 > 80,
    text: c => `RSI(${c.rsi6.toFixed(0)})>80极度超买，不宜追高`, score: -6 },
  { key: 'rsi', check: c => c.rsi6 > 65 && c.rsi6 <= 80,
    text: c => `RSI(${c.rsi6.toFixed(0)})偏强，但尚未过热`, score: +2 },
  { key: 'rsi', check: c => c.rsi6 < 20,
    text: c => `RSI(${c.rsi6.toFixed(0)})<20极度超卖，可关注抄底机会`, score: +6 },
  { key: 'rsi', check: c => c.rsi6 >= 20 && c.rsi6 < 35,
    text: c => `RSI(${c.rsi6.toFixed(0)})偏弱，等待企稳信号`, score: -2 },
  // ── 布林带 ──
  { key: 'boll', check: c => c.bollUp > 0 && c.bollDn > 0 && c.bollUp !== c.bollDn && c.price > 0,
    text: c => {
      const pos = (c.price - c.bollDn) / (c.bollUp - c.bollDn) * 100
      if (pos > 95) return `股价${c.price.toFixed(2)}触及布林上轨(${c.bollUp.toFixed(2)})，短线压力较大`
      if (pos < 5) return `股价${c.price.toFixed(2)}接近布林下轨(${c.bollDn.toFixed(2)})，存在技术支撑`
      if (pos > 70) return '股价在布林带中上区域运行，偏强'
      if (pos < 30) return '股价在布林带中下区域运行，偏弱'
      return `股价${c.price.toFixed(2)}沿布林中轨(${c.bollMid.toFixed(2)})附近震荡`
    }, score: 0 },
  // ── 量能 ──
  { key: 'volume', check: c => c.volRatio > 3,
    text: c => `量比${c.volRatio.toFixed(1)}极度放大，资金异动明显`, score: 0 },
  { key: 'volume', check: c => c.volRatio > 1.5 && c.volRatio <= 3 && c.changePct > 0,
    text: c => `量比${c.volRatio.toFixed(1)}温和放量，上涨有量能配合`, score: +4 },
  { key: 'volume', check: c => c.volRatio > 1.5 && c.volRatio <= 3 && c.changePct <= 0,
    text: c => `量比${c.volRatio.toFixed(1)}放大但股价未涨，注意抛压`, score: -2 },
  { key: 'volume', check: c => c.volRatio < 0.5,
    text: c => `量比${c.volRatio.toFixed(1)}极度缩量，交投清淡`, score: -3 },
  { key: 'volume', check: c => c.volRatio >= 0.5 && c.volRatio <= 1.5,
    text: c => `量比${c.volRatio.toFixed(1)}，量能正常`, score: 0 },
  // ── 基本面 ──
  { key: 'fundamental', check: c => c.pe > 0 && c.roe > 0 && c.pe / c.roe < 1,
    text: c => `PE(${c.pe.toFixed(1)})/ROE(${c.roe.toFixed(1)}%)比值${(c.pe/c.roe).toFixed(2)}<1，估值偏低有安全边际`, score: +5 },
  { key: 'fundamental', check: c => c.pe > 0 && c.roe > 0 && c.pe / c.roe >= 1 && c.pe / c.roe < 2,
    text: c => `PE(${c.pe.toFixed(1)})/ROE(${c.roe.toFixed(1)}%)比值${(c.pe/c.roe).toFixed(2)}，估值合理`, score: +2 },
  { key: 'fundamental', check: c => c.pe > 0 && c.roe > 0 && c.pe / c.roe >= 2,
    text: c => `PE(${c.pe.toFixed(1)})相对ROE(${c.roe.toFixed(1)}%)偏高，估值不便宜`, score: -3 },
  { key: 'fundamental', check: c => c.profitYoy > 20,
    text: c => `净利润同比+${c.profitYoy.toFixed(0)}%增长强劲`, score: +4 },
  { key: 'fundamental', check: c => c.profitYoy < -15,
    text: c => `净利润同比${c.profitYoy.toFixed(0)}%下滑明显，需警惕业绩风险`, score: -6 },
  // ── 今日盘面 ──
  { key: 'price', check: c => c.changePct > 5,
    text: c => `今日大涨+${c.changePct.toFixed(2)}%，短期动能强劲但注意追高风险`, score: 0 },
  { key: 'price', check: c => c.changePct > 2 && c.changePct <= 5,
    text: c => `今日上涨+${c.changePct.toFixed(2)}%，走势偏强`, score: +2 },
  { key: 'price', check: c => c.changePct < -5,
    text: c => `今日大跌${c.changePct.toFixed(2)}%，短期承压明显`, score: -3 },
  { key: 'price', check: c => c.changePct < -2 && c.changePct >= -5,
    text: c => `今日下跌${c.changePct.toFixed(2)}%，走势偏弱`, score: -2 },
]

export function buildAnalysisCtx(ind, fin, rt) {
  return {
    price: Number(rt?.price) || 0,
    changePct: Number(rt?.change_pct) || 0,
    ma5: Number(ind.MA5) || 0,
    ma10: Number(ind.MA10) || 0,
    ma20: Number(ind.MA20) || 0,
    ma60: Number(ind.MA60) || 0,
    macdSignal: ind.MACD_SIGNAL || '',
    kdjJ: Number(ind.KDJ_J) || 0,
    rsi6: Number(ind.RSI6) || 50,
    bollUp: Number(ind.BOLL_UP) || 0,
    bollMid: Number(ind.BOLL_MID) || 0,
    bollDn: Number(ind.BOLL_DN) || 0,
    volRatio: Number(ind.VOL_RATIO) || 1,
    pe: Number(fin?.pe) || 0,
    roe: Number(fin?.roe) || 0,
    profitYoy: Number(fin?.profit_yoy) || 0,
  }
}

export function runAnalysis(ctx) {
  try {
    const hits = ANALYSIS_RULES.filter(r => r.check(ctx))
    const textParts = hits.map(r => {
      try { return r.text(ctx) } catch { return '' }
    })
    const rawScore = hits.reduce((s, r) => s + r.score, 0)
    const score = Math.max(0, Math.min(100, 50 + rawScore))
    const conclusion = CONCLUSION_LEVELS.find(l => score >= l.min)
    return {
      hits,
      textParts,
      rawScore,
      score,
      conclusionText: conclusion?.text || '信号不足',
      conclusionType: conclusion?.type || 'neutral',
      groups: groupByDimension(hits, ctx),
      ctx,
    }
  } catch (e) {
    console.warn('[runAnalysis] 分析异常:', e)
    return { hits: [], textParts: [], rawScore: 0, score: 50, conclusionText: '信号不足', conclusionType: 'neutral', groups: {}, ctx }
  }
}

function groupByDimension(hits, ctx) {
  const map = {}
  for (const h of hits) {
    if (!map[h.key]) map[h.key] = []
    map[h.key].push(h.text(ctx))
  }
  return map
}

export function formatAnalysisText(textParts, conclusionText) {
  if (!textParts.length) return `综合判断：${conclusionText}`
  return `${textParts.join('；')}。综合判断：${conclusionText}`
}

// ── 行业分类映射 ──
const INDUSTRY_MAP = {
  '600': { name: '沪市主板', peThreshold: 25 },
  '601': { name: '金融/地产', peThreshold: 12 },
  '603': { name: '制造业', peThreshold: 25 },
  '605': { name: '消费/医药', peThreshold: 30 },
  '000': { name: '深市主板', peThreshold: 25 },
  '001': { name: '金融/地产', peThreshold: 12 },
  '002': { name: '中小板制造', peThreshold: 30 },
  '300': { name: '创业板科技', peThreshold: 45 },
  '688': { name: '科创板硬科技', peThreshold: 50 },
}

// 按股票名称关键词判断行业（优先级高于代码前缀）
const NAME_INDUSTRY_MAP = [
  { keys: ['银行'], industry: { name: '银行', peThreshold: 8 } },
  { keys: ['证券', '保险', '金融'], industry: { name: '金融', peThreshold: 15 } },
  { keys: ['地产', '置业', '控股'], industry: { name: '房地产', peThreshold: 12 } },
  { keys: ['药业', '制药', '生物', '医疗', '医药'], industry: { name: '医药', peThreshold: 35 } },
  { keys: ['酒', '食品', '乳', '味'], industry: { name: '消费', peThreshold: 30 } },
  { keys: ['科技', '电子', '软件', '信息', '智能', '芯'], industry: { name: '科技', peThreshold: 45 } },
  { keys: ['能源', '电力', '煤炭', '石油', '燃气', '光'], industry: { name: '能源', peThreshold: 18 } },
  { keys: ['钢铁', '有色', '矿', '铝', '铜'], industry: { name: '资源', peThreshold: 20 } },
  { keys: ['汽车', '机械', '重工', '设备'], industry: { name: '制造', peThreshold: 25 } },
  { keys: ['建', '材', '水泥'], industry: { name: '建材', peThreshold: 20 } },
  { keys: ['传媒', '影视', '游戏', '文'], industry: { name: '传媒', peThreshold: 30 } },
  { keys: ['交', '运', '航空', '港', '路'], industry: { name: '交运', peThreshold: 20 } },
]

function getIndustryInfo(stockCode, stockName) {
  if (stockName) {
    for (const item of NAME_INDUSTRY_MAP) {
      if (item.keys.some(k => stockName.includes(k))) {
        return item.industry
      }
    }
  }
  if (!stockCode || stockCode.length < 3) return { name: '综合', peThreshold: 25 }
  const prefix = stockCode.slice(0, 3)
  return INDUSTRY_MAP[prefix] || { name: '综合', peThreshold: 25 }
}

export function buildMultiPeriodAdvice(indicators, realtime, financial, stockCode, stockName) {
  if (!indicators || !realtime) return null

  const price = Number(realtime.price) || 0
  const changePct = Number(realtime.change_pct) || 0
  const ma5 = Number(indicators.MA5) || 0
  const ma20 = Number(indicators.MA20) || 0
  const ma60 = Number(indicators.MA60) || 0
  const macdSignal = indicators.MACD_SIGNAL || ''
  const kdjJ = Number(indicators.KDJ_J) || 50
  const rsi6 = Number(indicators.RSI6) || 50
  const volRatio = Number(indicators.VOL_RATIO) || 1

  // ── 短线（1-3日）：关注 KDJ/RSI/MACD/量能，结合趋势背景 ──
  let short = { text: '震荡观望，等待方向明确', type: 'neutral' }
  if ((/金叉|多头/.test(macdSignal)) && (kdjJ < 80 || rsi6 < 75) && (volRatio > 1 || kdjJ < 50)) {
    short = { text: 'MACD金叉+量能配合，可逢低关注', type: 'positive' }
  } else if (/死叉/.test(macdSignal) || (kdjJ > 90 || rsi6 > 80)) {
    short = { text: '短线超买/死叉信号，警惕回调', type: 'negative' }
  } else if (changePct > 3) {
    // 大涨时结合趋势判断：上升趋势中可追，下降趋势中不追
    if (ma5 > ma20 && price > ma20) {
      short = { text: '今日涨幅较大但趋势向上，注意回调后介入', type: 'neutral' }
    } else {
      short = { text: '今日涨幅较大，不建议追高', type: 'negative' }
    }
  } else if (changePct < -3) {
    // 急跌时结合趋势判断：上升趋势中的回调可抄底，下降趋势中不接飞刀
    if (ma5 > ma20 && price > ma20) {
      short = { text: '上升趋势中回调，关注支撑位反弹机会', type: 'positive' }
    } else if (kdjJ < 20 || rsi6 < 30) {
      short = { text: '急跌+指标超卖，存在技术性反弹可能但需谨慎', type: 'neutral' }
    } else {
      short = { text: '急跌且趋势偏弱，不宜盲目抄底', type: 'negative' }
    }
  }

  // ── 中线（1-2周）：关注均线排列 ──
  let mid = { text: '均线交织，方向不明', type: 'neutral' }
  if (ma5 > ma20 && ma20 > ma60) {
    mid = { text: '均线多头排列，中期趋势向好', type: 'positive' }
  } else if (ma5 < ma20 && ma20 < ma60) {
    mid = { text: '均线空头排列，中期趋势走弱', type: 'negative' }
  } else if (ma5 > ma20) {
    mid = { text: '短期转强，关注能否延续', type: 'positive' }
  } else if (ma5 < ma20) {
    mid = { text: '短期转弱，谨慎对待', type: 'negative' }
  }

  // ── 长线（1-3月）：关注财务+趋势+行业估值 ──
  const pe = Number(financial?.pe) || 0
  const roe = Number(financial?.roe) || 0
  const industryInfo = getIndustryInfo(stockCode)

  let long = { text: '建议结合行业景气度判断', type: 'neutral' }
  if (pe < 0) {
    long = { text: '当前亏损股，长期需观察业绩拐点', type: 'negative' }
  } else if (pe > 0 && roe > 10 && ma20 > ma60) {
    const threshold = industryInfo?.peThreshold ?? 25
    const iname = industryInfo?.name ?? ''
    if (pe < threshold) {
      long = { text: `${iname}PE=${pe}估值合理+ROE=${roe}%盈利优秀+长期趋势向好`, type: 'positive' }
    } else {
      long = { text: `${iname}PE=${pe}偏高(阈值${threshold})，但ROE=${roe}%尚可，关注估值消化`, type: 'neutral' }
    }
  } else if (pe > 0 && roe < 0) {
    const iname = industryInfo?.name ?? ''
    long = { text: `${iname}PE=${pe}但盈利下滑(ROE<0)，长期需谨慎`, type: 'negative' }
  } else if (ma20 < ma60) {
    long = { text: '长期趋势偏弱，建议等待右侧信号', type: 'negative' }
  }

  return { short, mid, long }
}
