// 个股诊断共享 computed — 接收 techData ref，返回所有常用计算属性
import { computed } from 'vue'

export function useStockDiagnosisComputed(techData, financialData) {
  // ── 加权评分 / 风险等级（先定义，避免 assessData TDZ） ──
  const weightedScore = computed(() => techData.value?.weighted_score ?? null)

  // ── 综合评估 — 标题基于后端加权评分分档（与 CONCLUSION_LEVELS 5 档对齐）──
  // 注意：techData 有值时永远返回非 null（避免 v-if 提前 false 整张卡片不显示）
  const assessData = computed(() => {
    try {
      const t = techData.value
      if (!t) return null
      const ind = t.indicators || {}
      const score = weightedScore.value
      const support = ind.BOLL_DN || null
      const resist = ind.BOLL_UP || null

      // 5 档统一（与后端 SCORE_THRESHOLDS 对齐）
      let title, type
      if (score == null) {
        title = '数据不足'
        type = 'info'
      } else {
        // 直接复用 useAnalysisRules.js 中的 getScoreLevel 口径
        // 强势偏多 ≥75 / 偏多 ≥60 / 中性 ≥45 / 偏空 ≥30 / 弱势偏空 <30
        if (score >= 75) { title = `强势偏多 ${score}分`; type = 'error' }
        else if (score >= 60) { title = `偏多 ${score}分`; type = 'error' }
        else if (score >= 45) { title = `中性 ${score}分`; type = 'info' }
        else if (score >= 30) { title = `偏空 ${score}分`; type = 'success' }
        else { title = `弱势偏空 ${score}分`; type = 'success' }
      }

      if (ind && Object.keys(ind).length > 0) {
        const macd = ind.MACD_SIGNAL || ''
        const kdj = ind.KDJ_SIGNAL || ''
        const rsi = ind.RSI_SIGNAL || ''
        const boll = ind.BOLL_SIGNAL || ''
        const buyCount = [macd, kdj, rsi, boll].filter(v => /买入|金叉|多头|超卖/.test(v)).length
        const sellCount = [macd, kdj, rsi, boll].filter(v => /卖出|死叉|空头|超买/.test(v)).length
        title += ` · ${buyCount}买/${sellCount}卖`
      }

      return { title, type, support, resist }
    } catch (e) {
      console.warn('[assessData] 计算失败:', e?.message)
      return { title: '数据加载中', type: 'info', support: null, resist: null }
    }
  })

  // ── 买卖信号 ──
  const BUY_SIGNAL_CONFIG = [
    { label: 'MACD多头', key: 'MACD_SIGNAL', regex: /金叉|多头/ },
    { label: 'KDJ偏强', key: 'KDJ_SIGNAL', regex: /超卖|偏强/ },
    { label: 'RSI偏强', key: 'RSI_SIGNAL', regex: /偏强/ },
    { label: '布林带突破', key: 'BOLL_SIGNAL', regex: /突破上轨/ },
  ]

  const SELL_SIGNAL_CONFIG = [
    { label: 'MACD空头', key: 'MACD_SIGNAL', regex: /死叉|空头/ },
    { label: 'KDJ偏弱', key: 'KDJ_SIGNAL', regex: /超买|偏弱/ },
    { label: 'RSI超买', key: 'RSI_SIGNAL', regex: /超买/ },
    { label: '布林带跌破', key: 'BOLL_SIGNAL', regex: /跌破下轨/ },
  ]

  const buySignals = computed(() => {
    const ind = techData.value?.indicators
    if (!ind) return []
    return BUY_SIGNAL_CONFIG.filter(s => s.regex.test(ind[s.key] || '')).map(s => s.label)
  })

  const sellSignals = computed(() => {
    const ind = techData.value?.indicators
    if (!ind) return []
    return SELL_SIGNAL_CONFIG.filter(s => s.regex.test(ind[s.key] || '')).map(s => s.label)
  })

  const scoreClass = computed(() => {
    // 与 useAnalysisRules.js 的 CONCLUSION_LEVELS 5 档对齐
    const s = weightedScore.value
    if (s == null) return ''
    if (s >= 75) return 'score-strong-bull'
    if (s >= 60) return 'score-bull'
    if (s >= 45) return 'score-mid'
    if (s >= 30) return 'score-bear'
    return 'score-strong-bear'
  })

  const riskStars = computed(() => {
    const rl = techData.value?.risk_level
    if (!rl || !rl.level) return '☆☆☆☆☆'
    return '★'.repeat(rl.level) + '☆'.repeat(5 - rl.level)
  })

  const riskClass = computed(() => {
    const rl = techData.value?.risk_level
    if (!rl || !rl.level) return ''
    if (rl.level <= 2) return 'risk-low'
    if (rl.level <= 3) return 'risk-mid'
    return 'risk-high'
  })

  const riskReasons = computed(() => {
    const rl = techData.value?.risk_level
    if (!rl) return []
    if (Array.isArray(rl.reasons)) return rl.reasons
    if (typeof rl.reasons === 'string') return rl.reasons.split(/[，,；;]/).map(s => s.trim()).filter(Boolean)
    return []
  })

  // ── 近期表现 / 资金流 ──
  const recentPerformance = computed(() => {
    const perf = techData.value?.recent_performance || {}
    const map = [
      { label: '1周', key: 'PCT_1W' },
      { label: '1月', key: 'PCT_1M' },
      { label: '3月', key: 'PCT_3M' },
      { label: '1年', key: 'PCT_1Y' },
    ]
    const result = []
    for (const m of map) {
      if (perf[m.key] !== undefined) {
        const v = perf[m.key]
        result.push({
          label: m.label,
          text: (v >= 0 ? '+' : '') + v + '%',
          cls: v > 0 ? 'c-red' : v < 0 ? 'c-green' : '',
        })
      }
    }
    return result.length ? result : null
  })

  const flowTrend = computed(() => {
    const cf = techData.value?.capital_flow
    if (!cf) return null
    const fmt = (v) => {
      if (v == null) return { text: '暂无数据', cls: 'flow-na' }
      const n = Number(v)
      if (Math.abs(n) < 0.05) return { text: '±0', cls: '' }
      return { text: (n >= 0 ? '+' : '') + n.toFixed(2) + '亿', cls: n > 0 ? 'c-red' : 'c-green' }
    }
    const net = (buy, sell) => {
      const b = Number(buy) || 0
      const s = Number(sell) || 0
      return b - s
    }
    return {
      today: fmt(cf.main_net),
      flow3d: fmt(cf.flow_3d),
      flow5d: fmt(cf.flow_5d),
      flow10d: fmt(cf.flow_10d),
      bigNet: fmt(net(cf.big_buy, cf.big_sell)),
      midNet: fmt(net(cf.mid_buy, cf.mid_sell)),
      smallNet: fmt(net(cf.small_buy, cf.small_sell)),
    }
  })

  // ── K线形态分析 ──
  const patternAnalysis = computed(() => {
    const list = techData.value?.kline_patterns?.patterns || []
    if (!list.length) return ''
    const bullish = list.filter(p => p.direction === 'bullish').length
    const bearish = list.filter(p => p.direction === 'bearish').length
    let trend = '中性'
    if (bullish > bearish + 2) trend = '偏多'
    else if (bearish > bullish + 2) trend = '偏空'
    const recent = list.slice(-3).map(p => p.name).join('、')
    return `近期出现${recent}等形态，整体${trend}。`
  })

  // ── 财务数据展示 ──
  const finItems = computed(() => {
    const f = financialData?.value || financialData
    if (!f || !Object.keys(f).length) return []
    const fmtVal = (v, suffix = '') => v != null ? Number(v).toFixed(2) + suffix : '--'
    return [
      { label: 'PE(动)', value: fmtVal(f.pe_ttm ?? f.pe), cls: '' },
      { label: 'PB', value: fmtVal(f.pb), cls: '' },
      { label: 'ROE', value: fmtVal(f.roe, '%'), cls: '' },
      { label: 'EPS', value: f.eps != null ? '¥' + Number(f.eps).toFixed(2) : '--', cls: '' },
      { label: '毛利率', value: fmtVal(f.gross_margin, '%'), cls: '' },
      { label: '资产负债率', value: fmtVal(f.debt_ratio, '%'), cls: '' },
      { label: '营收同比', value: f.revenue_yoy != null ? (f.revenue_yoy >= 0 ? '+' : '') + Number(f.revenue_yoy).toFixed(1) + '%' : '--', cls: f.revenue_yoy > 0 ? 'c-red' : f.revenue_yoy < 0 ? 'c-green' : '' },
      { label: '净利润同比', value: f.profit_yoy != null ? (f.profit_yoy >= 0 ? '+' : '') + Number(f.profit_yoy).toFixed(1) + '%' : '--', cls: f.profit_yoy > 0 ? 'c-red' : f.profit_yoy < 0 ? 'c-green' : '' },
    ]
  })

  const finAnalysis = computed(() => {
    const f = financialData?.value || financialData
    if (!f) return ''
    let parts = []
    const pe = Number(f.pe_ttm ?? f.pe ?? 0)
    const roe = Number(f.roe ?? 0)
    const debtRatio = Number(f.debt_ratio)
    const revGrowth = Number(f.revenue_yoy ?? 0)
    const profitGrowth = Number(f.profit_yoy ?? 0)

    if (pe > 0) {
      if (pe < 15) parts.push('估值偏低')
      else if (pe < 30) parts.push('估值合理')
      else parts.push('估值偏高')
    }
    if (roe > 0) {
      if (roe > 15) parts.push('盈利能力优秀')
      else if (roe > 8) parts.push('盈利尚可')
      else parts.push('盈利能力偏弱')
    }
    if (revGrowth > 20 && profitGrowth > 20) parts.push('业绩高增长')
    else if (revGrowth < -10 && profitGrowth < -10) parts.push('业绩下滑明显')
    else if (profitGrowth > revGrowth) parts.push('利润增速优于营收')
    if (!isNaN(debtRatio)) {
      if (debtRatio > 80) parts.push('负债率较高，注意风险')
      else if (debtRatio < 40) parts.push('财务稳健')
    }
    return parts.length ? parts.join('；') + '。' : '财务数据正常。'
  })

  // ── 技术指标分析 ──
  const techAnalysis = computed(() => {
    const ind = techData.value?.indicators
    if (!ind) return ''
    let buyCount = 0, sellCount = 0
    for (const sig of [ind.MACD_SIGNAL, ind.KDJ_SIGNAL, ind.RSI_SIGNAL, ind.BOLL_SIGNAL]) {
      if (/买入|金叉|多头|超卖/.test(sig)) buyCount++
      else if (/卖出|死叉|空头|超买/.test(sig)) sellCount++
    }
    let trend = '多空均衡'
    if (buyCount > sellCount + 1) trend = '偏多格局'
    else if (sellCount > buyCount + 1) trend = '偏空格局'

    const ma5 = Number(ind.MA5), ma20 = Number(ind.MA20)
    let maTrend = ''
    if (ma5 > 0 && ma20 > 0) {
      maTrend = ma5 > ma20 ? '短期均线向上' : '短期均线向下'
    }
    return `${trend}，${maTrend || '信号不足'}。`
  })

  // ── 实时行情展示 ──
  const rtItems = computed(() => {
    const d = techData.value?.realtime
    if (!d) return []
    const pctClass = (d.change_pct || 0) >= 0 ? 'c-red' : 'c-green'
    return [
      { label: '最新价', value: '¥' + d.price, cls: pctClass },
      { label: '涨跌幅', value: ((d.change_pct || 0) >= 0 ? '+' : '') + (d.change_pct || 0) + '%', cls: pctClass },
      { label: '今开', value: '¥' + d.open, cls: '' },
      { label: '昨收', value: '¥' + d.last_close, cls: '' },
      { label: '最高', value: '¥' + d.high, cls: 'c-red' },
      { label: '最低', value: '¥' + d.low, cls: 'c-green' },
    ]
  })

  const rtAnalysis = computed(() => {
    const d = techData.value?.realtime
    if (!d) return ''
    const pct = d.change_pct || 0
    let parts = []
    if (pct > 3) parts.push('今日强势上涨')
    else if (pct > 1) parts.push('温和上涨')
    else if (pct > -1) parts.push('窄幅震荡')
    else if (pct > -3) parts.push('小幅回调')
    else parts.push('明显下跌')
    const amt = parseFloat(d.amount || 0)
    if (amt > 500000) parts.push('成交活跃')
    else if (amt < 100000) parts.push('交投清淡')
    return `${parts.join('，')}。现价¥${d.price}，涨跌${pct >= 0 ? '+' : ''}${pct}%`
  })

  // ── 价格计划（防御 NaN/Infinity/0） ──
  const pricePlan = computed(() => {
    const ind = techData.value?.indicators
    const rt = techData.value?.realtime
    if (!ind || !rt || rt.price == null) return null
    const price = Number(rt.price)
    const ma20 = Number(ind.MA20) || 0
    const bollUp = Number(ind.BOLL_UP) || 0
    const bollDn = Number(ind.BOLL_DN) || 0
    if (price <= 0 || ma20 <= 0 || bollUp <= 0 || bollDn <= 0) return null
    let buyLow = Math.min(ma20, price * 0.985)
    let buyHigh = Math.max(ma20, price * 0.995)
    if (buyLow <= 0 || !isFinite(buyLow) || !isFinite(buyHigh)) return null
    const stopLoss = round2(bollDn * 0.98)
    const stopPct = round1((stopLoss / price - 1) * 100)
    const target1 = round2(bollUp)
    const target1Pct = round1((target1 / price - 1) * 100)
    const target2 = round2(price + (bollUp - bollDn))
    const target2Pct = round1((target2 / price - 1) * 100)
    const target3 = round2(price + (bollUp - bollDn) * 2)
    const target3Pct = round1((target3 / price - 1) * 100)
    return { buyLow: round2(buyLow), buyHigh: round2(buyHigh), stopLoss, stopPct, target1, target1Pct, target2, target2Pct, target3, target3Pct }
  })

  function round1(n) { return Math.round(n * 10) / 10 }
  function round2(n) { return Math.round(n * 100) / 100 }

  // ── 技术指标表格（共享） ──
  function _calcSignal(key, val, price) {
    if (val === undefined || val === null) return '--'
    if (key.startsWith('MA') && price > 0) {
      const diff = Math.abs((price - val) / val * 100).toFixed(2)
      return price > val ? `上方+${diff}%` : `下方${diff}%`
    }
    if (key === 'MACD_BAR') return val > 0 ? '红柱(多头)' : val < 0 ? '绿柱(空头)' : '零轴'
    if (key.startsWith('KDJ')) {
      // 与后端 _calc_indicators 对齐：J>100 才算超买，J<0 才算超卖
      // KDJ_J 实际可超出 0-100 区间（K、D 一般在 0-100 内）
      if (key === 'KDJ_J') {
        if (val > 100) return '超买'
        if (val < 0) return '超卖'
        if (val > 50) return '偏强'
        return '偏弱'
      }
      // KDJ_K / KDJ_D 仍按 80/20 判定（这两个值通常不会突破 0-100）
      if (val > 80) return '超买'
      if (val < 20) return '超卖'
      if (val > 50) return '偏强'
      return '偏弱'
    }
    if (key.startsWith('RSI')) {
      if (val > 80) return '超买'
      if (val > 60) return '偏强'
      if (val > 40) return '中性'
      if (val > 20) return '偏弱'
      return '超卖'
    }
    if (key === 'BOLL_UP') return '上轨压力'
    if (key === 'BOLL_MID') return '中轨'
    if (key === 'BOLL_DN') return '下轨支撑'
    if (key === 'VOL_RATIO') {
      if (val > 2) return '明显放量'
      if (val > 1.5) return '温和放量'
      if (val > 0.8) return '量能平稳'
      return '缩量'
    }
    return '--'
  }
  function _signalType(s) {
    const v = String(s)
    if (/上方|红柱|多头|超卖|买入|金叉|突破上轨/.test(v)) return 'danger'
    if (/下方|绿柱|空头|超买|卖出|死叉|跌破下轨/.test(v)) return 'success'
    return 'info'
  }

  const techTable = computed(() => {
    const t = techData.value
    if (!t) return []
    const ind = t.indicators
    const price = t.realtime?.price || 0
    const result = []
    if (ind && Object.keys(ind).length > 0) {
      const sections = [
        { name: 'MA5', key: 'MA5', desc: '5日均线' },
        { name: 'MA10', key: 'MA10', desc: '10日均线' },
        { name: 'MA20', key: 'MA20', desc: '20日均线' },
        { name: 'MA60', key: 'MA60', desc: '60日均线' },
        { name: 'DIF', key: 'MACD_DIF', desc: 'MACD快线' },
        { name: 'DEA', key: 'MACD_DEA', desc: 'MACD慢线' },
        { name: 'MACD柱', key: 'MACD_BAR', desc: 'MACD柱状图' },
        { name: 'KDJ-K', key: 'KDJ_K', desc: '随机指标K值' },
        { name: 'KDJ-D', key: 'KDJ_D', desc: '随机指标D值' },
        { name: 'KDJ-J', key: 'KDJ_J', desc: '随机指标J值' },
        { name: 'RSI6', key: 'RSI6', desc: '相对强弱指数(6日)' },
        { name: 'RSI12', key: 'RSI12', desc: '相对强弱指数(12日)' },
        { name: 'RSI24', key: 'RSI24', desc: '相对强弱指数(24日)' },
        { name: '布林上轨', key: 'BOLL_UP', desc: '布林带上轨' },
        { name: '布林中轨', key: 'BOLL_MID', desc: '布林带中轨' },
        { name: '布林下轨', key: 'BOLL_DN', desc: '布林带下轨' },
        { name: '量比', key: 'VOL_RATIO', desc: '' },
      ]
      for (const s of sections) {
        const v = ind[s.key]
        if (v !== undefined && v !== null) {
          const sig = _calcSignal(s.key, v, price)
          result.push({ name: s.name, value: v, signal: sig, signalType: _signalType(sig), desc: s.desc })
        }
      }
      const signalMap = [
        { name: 'MACD', key: 'MACD_SIGNAL' },
        { name: 'KDJ', key: 'KDJ_SIGNAL' },
        { name: 'RSI', key: 'RSI_SIGNAL' },
        { name: '布林带', key: 'BOLL_SIGNAL' },
        { name: '量能', key: 'VOL_SIGNAL' },
      ]
      for (const s of signalMap) {
        const val = ind[s.key]
        if (val) {
          result.push({ name: `${s.name}信号`, value: '--', signal: val, signalType: _signalType(val), desc: '' })
        }
      }
    }
    return result
  })

  // 趋势组：MA + MACD；震荡组：KDJ + RSI + BOLL + 量比（KDJ 属震荡指标，与 RSI 同类）
  const techTableLeft = computed(() => techTable.value.filter(r => /^(MA|MACD)/.test(r.name)))
  const techTableRight = computed(() => techTable.value.filter(r => !/^(MA|MACD)/.test(r.name)))

  function getTrendSummary() {
    const left = techTableLeft.value
    const buy = left.filter(i => i.signalType === 'danger').length
    const sell = left.filter(i => i.signalType === 'success').length
    if (buy > sell + 1) return '偏多'
    if (sell > buy + 1) return '偏空'
    return '中性'
  }
  function getTrendBadgeClass() {
    const s = getTrendSummary()
    return s === '偏多' ? 'badge-strong' : s === '偏空' ? 'badge-weak' : 'badge-mid'
  }
  function getOscillationSummary() {
    const right = techTableRight.value
    const buy = right.filter(i => i.signalType === 'danger').length
    const sell = right.filter(i => i.signalType === 'success').length
    if (buy > sell + 1) return '偏多'
    if (sell > buy + 1) return '偏空'
    return '中性'
  }
  function getOscillationBadgeClass() {
    const s = getOscillationSummary()
    return s === '偏多' ? 'badge-strong' : s === '偏空' ? 'badge-weak' : 'badge-mid'
  }

  return {
    assessData,
    buySignals,
    sellSignals,
    weightedScore,
    scoreClass,
    riskStars,
    riskClass,
    riskReasons,
    recentPerformance,
    flowTrend,
    patternAnalysis,
    finItems,
    finAnalysis,
    techAnalysis,
    rtItems,
    rtAnalysis,
    pricePlan,
    techTable,
    techTableLeft,
    techTableRight,
    getTrendSummary,
    getTrendBadgeClass,
    getOscillationSummary,
    getOscillationBadgeClass,
  }
}
