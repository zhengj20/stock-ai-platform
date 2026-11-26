<template>
  <section class="card-section">
    <h3 class="section-title">🎯 市场概览</h3>
    <div v-if="loading" class="overview-loading">
      <div v-for="i in 8" :key="i" class="loading-card-skeleton"></div>
    </div>
    <div v-else class="overview-grid">
      <!-- 情绪评分 -->
      <div class="overview-card score-card">
        <div class="score-ring" :style="{ background: scoreGradient }">
          <span class="score-num">{{ sentimentScore }}</span>
        </div>
        <div class="score-info">
          <span class="score-status">{{ sentimentStatus }}</span>
          <el-tag :type="trendTagType" size="small" round class="trend-tag">
            {{ sentimentTrend }}
          </el-tag>
        </div>
      </div>

      <!-- 市场广度 -->
      <div class="overview-card breadth-card">
        <div class="breadth-title">涨跌家数</div>
        <div class="breadth-bars">
          <div class="bar-row">
            <span class="bar-label up">上涨</span>
            <el-progress :percentage="breadthUpPct" :stroke-width="16"
              color="#f56c6c" :show-text="false" class="breath-bar" />
            <span class="bar-value c-red">{{ breadthData.up }}</span>
          </div>
          <div class="bar-row">
            <span class="bar-label down">下跌</span>
            <el-progress :percentage="breadthDownPct" :stroke-width="16"
              color="#67c23a" :show-text="false" class="breath-bar" />
            <span class="bar-value c-green">{{ breadthData.down }}</span>
          </div>
        </div>
        <div class="breadth-ratio">
          <span class="ratio-label">涨跌比</span>
          <span class="ratio-val c-red">{{ breadthUpPct }}%</span>
          <span class="ratio-sep">/</span>
          <span class="ratio-val c-green">{{ breadthDownPct }}%</span>
          <span class="breadth-foot">（不含平盘 {{ breadthData.flat || 0 }} 只）</span>
        </div>
      </div>

      <!-- 资金流向（全市场净额 + 大/中/小单拆分） -->
      <div class="overview-card flow-card">
        <div class="flow-header">
          <span class="flow-title">主力净流入</span>
          <el-tooltip
            v-if="flowBreakdown.metric_note"
            placement="top"
            :content="flowBreakdown.metric_note"
          >
            <el-icon class="flow-info"><InfoFilled /></el-icon>
          </el-tooltip>
        </div>
        <div class="flow-amount" :class="moneyFlow.net >= 0 ? 'c-red' : 'c-green'">
          {{ moneyFlow.net >= 0 ? '+' : '' }}{{ moneyFlow.net?.toFixed(2) }}亿
        </div>
        <div class="flow-breakdown" v-if="flowBreakdown.hasData">
          <div class="bd-row">
            <span class="bd-label">超大单</span>
            <div class="bd-bar">
              <div
                class="bd-fill"
                :class="flowBreakdown.large >= 0 ? 'bd-up' : 'bd-dn'"
                :style="{ width: flowBreakdown.largePct + '%' }"
              ></div>
            </div>
            <span class="bd-val" :class="flowBreakdown.large >= 0 ? 'c-red' : 'c-green'">
              {{ flowBreakdown.large >= 0 ? '+' : '' }}{{ flowBreakdown.large?.toFixed(1) }}
            </span>
          </div>
          <div class="bd-row">
            <span class="bd-label">大单</span>
            <div class="bd-bar">
              <div
                class="bd-fill"
                :class="flowBreakdown.mid >= 0 ? 'bd-up' : 'bd-dn'"
                :style="{ width: flowBreakdown.midPct + '%' }"
              ></div>
            </div>
            <span class="bd-val" :class="flowBreakdown.mid >= 0 ? 'c-red' : 'c-green'">
              {{ flowBreakdown.mid >= 0 ? '+' : '' }}{{ flowBreakdown.mid?.toFixed(1) }}
            </span>
          </div>
          <div class="bd-row">
            <span class="bd-label">中单</span>
            <div class="bd-bar">
              <div
                class="bd-fill"
                :class="flowBreakdown.small >= 0 ? 'bd-up' : 'bd-dn'"
                :style="{ width: flowBreakdown.smallPct + '%' }"
              ></div>
            </div>
            <span class="bd-val" :class="flowBreakdown.small >= 0 ? 'c-red' : 'c-green'">
              {{ flowBreakdown.small >= 0 ? '+' : '' }}{{ flowBreakdown.small?.toFixed(1) }}
            </span>
          </div>
        </div>
        <div v-else class="flow-empty">
          <span class="inflow">流入 {{ moneyFlow.in?.toFixed(2) }}亿</span>
          <span class="outflow">流出 {{ moneyFlow.out?.toFixed(2) }}亿</span>
        </div>
        <el-tag :type="moneyFlow.net >= 0 ? 'danger' : 'success'" size="small" round>
          {{ moneyFlow.net >= 0 ? '净流入' : '净流出' }} · {{ moneyFlow.signal || '数据采集中' }}
        </el-tag>
        <div v-if="flowBreakdown.sampleSize" class="flow-foot">
          {{ flowBreakdown.sampleSize === '全市场' ? flowBreakdown.sampleSize : '样本 ' + flowBreakdown.sampleSize }}
          <span v-if="flowBreakdown.metric_note"> · {{ flowBreakdown.metric_note }}</span>
        </div>
      </div>

      <!-- 涨跌停 -->
      <div class="overview-card limit-card">
        <div class="limit-title">涨跌停</div>
        <div class="limit-grid">
          <div class="limit-item up">
            <span class="limit-num">{{ limitData.up }}</span>
            <span class="limit-label">涨停</span>
          </div>
          <div class="limit-item down">
            <span class="limit-num">{{ limitData.down }}</span>
            <span class="limit-label">跌停</span>
          </div>
        </div>
        <el-tag :type="limitTagType" size="small" round class="limit-signal-tag">
          {{ limitSignal }}
        </el-tag>
      </div>

      <!-- 赚钱效应（连板高度 / 封单强度 / 市场情绪标签） -->
      <div class="overview-card effect-card">
        <div class="effect-title">赚钱效应</div>
        <div class="effect-grid">
          <div class="ef-item">
            <span class="ef-num c-orange">{{ limitUpData.max_continuous || 0 }}</span>
            <span class="ef-label">连板高度</span>
          </div>
          <div class="ef-item">
            <span class="ef-num c-blue">{{ formatYi(limitUpData.total_sealed_yi) }}</span>
            <span class="ef-label">封单金额</span>
          </div>
        </div>
        <el-tag :type="effectTagType" size="small" round class="effect-tag">
          {{ effectSignal }}
        </el-tag>
      </div>

      <!-- 板块 Top 3（涨幅榜） -->
      <div class="overview-card sectors-card">
        <div class="sec-title">板块 Top3</div>
        <div class="sec-list" v-if="top3Sectors.length">
          <div v-for="(s, i) in top3Sectors" :key="s.name || i" class="sec-row">
            <span class="sec-rank">{{ i + 1 }}</span>
            <span class="sec-name" :title="s.name">{{ s.name }}</span>
            <span class="sec-pct" :class="(s.change_pct || 0) >= 0 ? 'c-red' : 'c-green'">
              {{ (s.change_pct || 0) >= 0 ? '+' : '' }}{{ (s.change_pct || 0).toFixed(2) }}%
            </span>
          </div>
        </div>
        <div v-else class="sec-empty">暂无数据</div>
      </div>

      <!-- 成交额 -->
      <div class="overview-card volume-card">
        <div class="volume-title">两市成交</div>
        <div class="volume-amount">{{ volumeDisplay }}</div>
        <el-tag :type="volumeSignalType" size="small" round>
          {{ volumeData.signal || '--' }}
        </el-tag>
      </div>

      <!-- 北向资金 -->
      <div class="overview-card northbound-card">
        <div class="nb-title">北向资金</div>
        <div v-if="northboundData.hasData" class="nb-rows">
          <div class="nb-row">
            <span class="nb-label">沪股通</span>
            <span class="nb-val" :class="northboundData.hgt >= 0 ? 'c-red' : 'c-green'">
              {{ northboundData.hgt >= 0 ? '+' : '' }}{{ northboundData.hgt?.toFixed(2) }}亿
            </span>
          </div>
          <div class="nb-row">
            <span class="nb-label">深股通</span>
            <span class="nb-val" :class="northboundData.sgt >= 0 ? 'c-red' : 'c-green'">
              {{ northboundData.sgt >= 0 ? '+' : '' }}{{ northboundData.sgt?.toFixed(2) }}亿
            </span>
          </div>
        </div>
        <div v-else class="nb-empty">
          <el-icon><InfoFilled /></el-icon>
          <span>暂无数据</span>
        </div>
        <div v-if="northboundData.hasData" class="nb-total" :class="northboundData.total >= 0 ? 'c-red' : 'c-green'">
          合计 {{ northboundData.total >= 0 ? '+' : '' }}{{ northboundData.total?.toFixed(2) }}亿
          <span v-if="!northboundData.hasMinuteData" class="nb-stale-note">（收盘数据）</span>
        </div>
        <div v-else class="nb-total nb-total--empty">合计 --</div>
      </div>

    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'

const props = defineProps({
  sentiment: { type: Object, default: () => ({}) },
  northbound: { type: Object, default: null },
  limitUpData: { type: Object, default: () => ({}) },
  sectorList: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const sentimentScore = computed(() => props.sentiment?.score ?? '--')
const sentimentStatus = computed(() => props.sentiment?.signal ?? '--')
const sentimentTrend = computed(() => {
  const b = props.sentiment?.breadth || {}
  const upRatio = b.up_ratio ?? 0
  if (upRatio > 65) return '上升'
  if (upRatio > 55) return '偏多'
  if (upRatio > 45) return '震荡'
  if (upRatio > 35) return '偏空'
  return '下降'
})

const breadthData = computed(() => {
  const b = props.sentiment?.breadth || {}
  return { up: b.up || 0, down: b.down || 0, flat: b.flat || 0 }
})
const breadthUpPct = computed(() => {
  const b = props.sentiment?.breadth || {}
  return Math.round(b.up_ratio || 0)
})
const breadthDownPct = computed(() => {
  // 涨跌比分母用 up+down（不含平盘），使两者之和 = 100%
  const b = props.sentiment?.breadth || {}
  const up = b.up || 0
  const down = b.down || 0
  const denom = up + down
  if (denom > 0) {
    return Math.round(down / denom * 100)
  }
  return 0
})

const moneyFlow = computed(() => {
  const m = props.sentiment?.money_flow || {}
  return {
    net: m.net_inflow_billion ?? 0,
    in: m.inflow_billion ?? 0,
    out: m.outflow_billion ?? 0,
    signal: m.signal || '--',
    superLarge: m.super_large_net ?? 0,
    large: m.large_net ?? 0,
    mid: m.mid_net ?? 0,
    small: m.small_net ?? 0,
    source: m.source || '',
  }
})

// 资金流拆分柱形（优先使用MX API数据，兜底同花顺行业合计）
const flowBreakdown = computed(() => {
  const m = props.sentiment?.money_flow || {}
  const bd = props.sentiment?.capital_flow_breakdown || {}

  // 优先: 东财大盘资金流拆分（超大单/大单/中单/小单）
  const emMain = Number(m.net_inflow_billion) || 0
  const emSuperLarge = Number(m.super_large_net) || 0
  const emLarge = Number(m.large_net) || 0
  const emMid = Number(m.mid_net) || 0

  // 兜底: 同花顺行业合计
  const thsMain = Number(bd.main_net_inflow_yi) || 0
  const thsLarge = Number(bd.large_net_yi ?? bd.main_net_inflow_yi) || 0
  const thsMid = Number(bd.mid_net_yi) || 0
  const thsSmall = Number(bd.small_net_yi) || 0

  const main = emMain || thsMain
  const large = emSuperLarge || thsLarge
  const mid = emLarge || thsMid
  const small = emMid || thsSmall
  const hasData = main !== 0 || large !== 0 || mid !== 0 || small !== 0

  // base 取所有项绝对值最大值，确保大额资金能完整显示且不互相挤占
  const base = Math.max(Math.abs(main), Math.abs(large), Math.abs(mid), Math.abs(small), 1)
  const toPct = (v) => Math.min(100, Math.round(Math.abs(v) / base * 100))

  return {
    main,
    large,
    mid,
    small,
    hasData,
    largePct: toPct(large),
    midPct: toPct(mid),
    smallPct: toPct(small),
    sampleSize: m.source === 'eastmoney' ? '全市场' : (bd.sample_size || 0),
    metric_note: m.source === 'eastmoney' ? '东方财富·主力资金' : (bd.metric_note || ''),
  }
})

const limitData = computed(() => {
  const l = props.sentiment?.limit_up_down || {}
  return { up: l.limit_up || 0, down: l.limit_down || 0 }
})

const volumeData = computed(() => {
  const v = props.sentiment?.volume || {}
  return { total: v.total_billion ?? 0, signal: v.signal || '--' }
})
// Format: show trillion (万亿) when >= 10000 billion
const volumeDisplay = computed(() => {
  const t = volumeData.value.total
  if (!t) return '0亿'
  if (t >= 10000) return `${(t / 10000).toFixed(2)}万亿`
  return `${Math.round(t)}亿`
})
const volumeSignalType = computed(() => {
  const s = volumeData.value.signal
  if (s === '放量') return 'danger'
  if (s === '缩量') return 'info'
  return 'success'
})

const northboundData = computed(() => {
  const s = props.northbound?.summary || {}
  const hgt = s.hgt_latest ?? 0
  const sgt = s.sgt_latest ?? 0
  const hasMinuteData = (props.northbound?.minute_data?.length || 0) > 0
  // 修复：非交易时段 minute_data 为空，但有汇总数据时仍应显示
  const hasSummary = hgt !== 0 || sgt !== 0
  return {
    hgt,
    sgt,
    total: hgt + sgt,
    hasData: hasMinuteData || hasSummary,
    hasMinuteData,
  }
})

const scoreGradient = computed(() => {
  const s = Number(sentimentScore.value)
  if (isNaN(s)) return 'linear-gradient(135deg, #667eea, #764ba2)'
  if (s >= 80) return 'linear-gradient(135deg, #f56c6c, #e6a23c)'
  if (s >= 60) return 'linear-gradient(135deg, #e6a23c, #f7ca18)'
  if (s >= 40) return 'linear-gradient(135deg, #667eea, #764ba2)'
  return 'linear-gradient(135deg, #67c23a, #85ce61)'
})

const trendTagType = computed(() => {
  const t = sentimentTrend.value
  if (t?.includes('上升') || t?.includes('偏多')) return 'danger'
  if (t?.includes('下降') || t?.includes('偏空')) return 'success'
  return 'warning'
})

// 涨跌停活跃度信号：同时考虑涨停和跌停
// 涨停 > 跌停 → 活跃；跌停远超涨停 → 恐慌；两者都少 → 平淡
const limitSignal = computed(() => {
  const up = limitData.value.up || 0
  const down = limitData.value.down || 0
  if (up === 0 && down === 0) return '平淡'
  // 跌停远多于涨停（市场恐慌/分化）优先判断
  if (down > up * 2 && down >= 30) return '恐慌分化'
  if (down > up * 1.5 && down >= 20) return '分化'
  // 涨停主导
  if (up >= 50) return '极度活跃'
  if (up >= 30 && up > down * 2) return '极度活跃'
  if (up >= 10 && up >= down) return '活跃'
  if (up >= 5) return '一般'
  return '平淡'
})

const limitTagType = computed(() => {
  const s = limitSignal.value
  if (s === '极度活跃' || s === '活跃') return 'danger'
  if (s === '恐慌分化') return 'danger'  // 红字强调（跌停过多）
  if (s === '分化') return 'warning'
  if (s === '一般') return 'success'
  return 'info'
})

// 赚钱效应信号：多维度加权综合评分
// 维度：连板高度(35%) + 封单金额(30%) + 涨停数量(20%) + 涨跌比(15%)
const effectSignal = computed(() => {
  const maxCont = props.limitUpData.max_continuous || 0
  const sealedYi = Number(props.limitUpData.total_sealed_yi) || 0
  const limitUpCount = props.limitUpData.total || 0
  const upRatio = props.sentiment?.breadth?.up_ratio || 0

  // 分段归一化到 0-100
  const boardScore = maxCont >= 10 ? 100 : maxCont >= 7 ? 80 : maxCont >= 5 ? 60 : maxCont >= 3 ? 40 : maxCont >= 2 ? 20 : 0
  const sealedScore = sealedYi >= 500 ? 100 : sealedYi >= 200 ? 75 : sealedYi >= 100 ? 55 : sealedYi >= 50 ? 35 : sealedYi >= 20 ? 15 : 0
  const countScore = limitUpCount >= 100 ? 100 : limitUpCount >= 60 ? 80 : limitUpCount >= 30 ? 55 : limitUpCount >= 10 ? 30 : 0
  const breadthScore = upRatio >= 80 ? 100 : upRatio >= 65 ? 80 : upRatio >= 55 ? 60 : upRatio >= 45 ? 45 : upRatio >= 35 ? 30 : 15

  const score = boardScore * 0.35 + sealedScore * 0.30 + countScore * 0.20 + breadthScore * 0.15

  if (score >= 75) return '极强'
  if (score >= 55) return '偏强'
  if (score >= 35) return '一般'
  if (score >= 15) return '偏弱'
  return '冰点'
})

const effectTagType = computed(() => {
  const s = effectSignal.value
  if (s === '极强') return 'danger'
  if (s === '偏强') return 'warning'
  if (s === '一般') return 'info'
  if (s === '偏弱') return 'info'
  return 'success'
})

// 板块 Top 3（按涨幅降序）
const top3Sectors = computed(() => {
  return [...(props.sectorList || [])]
    .sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0))
    .slice(0, 3)
})

// 格式化为「X.X 亿」/「XX.X 百亿」
const formatYi = (v) => {
  const n = Number(v) || 0
  if (n >= 100) return `${(n / 100).toFixed(1)}百亿`
  if (n === 0) return '0'
  return `${n.toFixed(1)}亿`
}
</script>

<style scoped>
/* 颜色工具类 */
.c-red { color: #f56c6c !important; }
.c-green { color: #67c23a !important; }
.c-orange { color: #e6a23c !important; }
.c-blue { color: #409eff !important; }

/* 一行 8 卡（宽屏 ≥1280px）— 中屏 4 列 / 窄屏 2 列响应式 */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 8px;
  min-width: 0;
}

.overview-card {
  background: #fff;
  border-radius: 8px;
  padding: 10px 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,.05);
  text-align: center;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

/* 共享标题样式（紧凑化） */
.score-card { display: flex; align-items: center; gap: 10px; justify-content: center; }
.score-ring {
  width: 52px; height: 52px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #fff; box-shadow: 0 2px 8px rgba(0,0,0,.15);
}
.score-num { font-size: 20px; font-weight: 700; line-height: 1; }

.score-info { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; min-width: 0; }
.score-status { font-size: 12px; color: #303133; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.trend-tag { margin-top: 0; }

.breadth-title, .flow-title, .limit-title, .volume-title, .nb-title, .effect-title, .sec-title {
  font-size: 12px; color: #909399; margin-bottom: 6px;
}
.bar-row {
  display: flex; align-items: center; gap: 4px; margin-bottom: 3px;
}
.bar-label { width: 30px; font-size: 11px; text-align: right; }
.bar-label.up { color: #f56c6c; }
.bar-label.down { color: #67c23a; }
.breath-bar { flex: 1; }
.bar-value { width: 32px; font-size: 11px; text-align: left; font-weight: 600; }
.breadth-ratio { font-size: 10px; color: #909399; margin-top: 4px; display: flex; align-items: baseline; justify-content: center; gap: 3px; flex-wrap: wrap; }
.ratio-label { color: #909399; }
.ratio-val { font-size: 11px; font-weight: 600; }
.ratio-sep { color: #dcdfe6; margin: 0 1px; }
.breadth-foot { color: #c0c4cc; font-size: 9px; }

.flow-amount { font-size: 18px; font-weight: 700; margin-bottom: 2px; }
.flow-detail { display: flex; justify-content: center; gap: 10px; font-size: 11px; color: #909399; margin-bottom: 4px; }
.inflow { color: #f56c6c; }
.outflow { color: #67c23a; }

/* 资金流向卡片 - 全市场净额 + 拆分（紧凑化） */
.flow-card { text-align: left; }
.flow-header {
  display: flex; align-items: center; justify-content: center;
  gap: 4px; margin-bottom: 4px;
}
.flow-info { color: #c0c4cc; font-size: 12px; cursor: help; transition: color .15s; }
.flow-info:hover { color: #409eff; }
.flow-breakdown { margin: 3px 0 4px; }
.bd-row {
  display: grid;
  grid-template-columns: 30px 1fr 38px;
  align-items: center;
  gap: 4px;
  margin-bottom: 2px;
  font-size: 10px;
}
.bd-label { color: #909399; text-align: right; white-space: nowrap; }
.bd-bar {
  height: 4px; background: #f0f2f5; border-radius: 2px; overflow: hidden;
  position: relative;
}
.bd-fill {
  height: 100%; border-radius: 2px; transition: width .4s ease;
  position: absolute; left: 0; top: 0;
}
.bd-fill.bd-up { background: linear-gradient(90deg, #f89898, #f56c6c); }
.bd-fill.bd-dn { background: linear-gradient(90deg, #85ce61, #67c23a); }
.bd-val { font-size: 10px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
.flow-empty {
  display: flex; justify-content: center; gap: 10px;
  font-size: 10px; margin: 3px 0 4px; color: #909399;
}
.flow-foot { font-size: 9px; color: #c0c4cc; margin-top: 2px; text-align: center; }

.limit-grid { display: flex; justify-content: center; gap: 18px; margin-bottom: 4px; }
.limit-item { text-align: center; }
.limit-num { font-size: 22px; font-weight: 700; display: block; line-height: 1.1; }
.limit-item.up .limit-num { color: #f56c6c; }
.limit-item.down .limit-num { color: #67c23a; }
.limit-label { font-size: 11px; color: #909399; }
.limit-signal-tag { margin-top: 4px; }
.limit-signal-tag :deep(.el-tag__content) { opacity: 1 !important; font-weight: 600; }

.volume-amount { font-size: 20px; font-weight: 700; color: #303133; margin-bottom: 4px; }

/* 赚钱效应卡片 */
.effect-card { padding: 10px 6px; }
.effect-grid { display: flex; justify-content: space-around; gap: 4px; }
.ef-item { display: flex; flex-direction: column; align-items: center; min-width: 0; flex: 1; }
.ef-num { font-size: 16px; font-weight: 700; line-height: 1.1; white-space: nowrap; font-variant-numeric: tabular-nums; }
.ef-label { font-size: 10px; color: #909399; margin-top: 2px; }
.effect-tag { margin-top: 4px; }
.effect-tag :deep(.el-tag__content) { opacity: 1 !important; }

/* 板块 Top 3 卡片 */
.sectors-card { text-align: left; padding: 8px 8px; }
.sec-list { display: flex; flex-direction: column; gap: 3px; }
.sec-row {
  display: grid;
  grid-template-columns: 16px 1fr auto;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}
.sec-rank {
  width: 14px; height: 14px; border-radius: 50%;
  background: #f0f2f5; color: #909399;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 9px; font-weight: 600;
}
.sec-row:nth-child(1) .sec-rank { background: linear-gradient(135deg, #f89898, #f56c6c); color: #fff; }
.sec-row:nth-child(2) .sec-rank { background: linear-gradient(135deg, #ffc966, #e6a23c); color: #fff; }
.sec-row:nth-child(3) .sec-rank { background: linear-gradient(135deg, #d4b483, #a0865a); color: #fff; }
.sec-name {
  color: #303133; font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sec-pct { font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
.sec-empty { text-align: center; color: #c0c4cc; font-size: 11px; padding: 8px 0; }

.nb-rows { display: flex; flex-direction: column; gap: 3px; margin-bottom: 4px; }
.nb-row { display: flex; justify-content: space-between; align-items: center; }
.nb-label { font-size: 11px; color: #909399; }
.nb-val { font-size: 12px; font-weight: 600; }
.nb-total { font-size: 12px; font-weight: 700; padding-top: 4px; border-top: 1px solid #f0f0f0; }
.nb-total--empty { color: #c0c4cc; font-weight: 400; }
.nb-stale-note { font-size: 9px; font-weight: 400; color: #c0c4cc; margin-left: 4px; }
.nb-empty {
  display: flex; align-items: center; justify-content: center;
  gap: 4px; font-size: 10px; color: #c0c4cc;
  padding: 6px 0; margin-bottom: 4px;
}

/* 响应式：中屏 4 列 */
@media (max-width: 1279px) {
  .overview-grid { grid-template-columns: repeat(4, 1fr); }
}

/* 窄屏 2 列 */
@media (max-width: 767px) {
  .overview-grid { grid-template-columns: repeat(2, 1fr); gap: 6px; }
  .score-ring { width: 44px; height: 44px; }
  .score-num { font-size: 17px; }
}

/* 加载骨架屏 */
.overview-loading {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 8px;
  min-width: 0;
}
.loading-card-skeleton {
  background: #fff;
  border-radius: 8px;
  padding: 10px 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,.05);
  min-height: 90px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.loading-card-skeleton::after {
  content: '';
  width: 24px;
  height: 24px;
  border: 2px solid #e5e7eb;
  border-top-color: #409eff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1279px) {
  .overview-loading { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 767px) {
  .overview-loading { grid-template-columns: repeat(2, 1fr); gap: 6px; }
}
</style>
