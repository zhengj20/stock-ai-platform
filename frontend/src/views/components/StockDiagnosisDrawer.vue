<template>
  <el-drawer :model-value="modelValue" @update:modelValue="onUpdateModelValue" :size="drawerSize" :show-close="false" @close="handleClose" direction="rtl" :with-header="false">
    <div class="custom-drawer-header">
      <span class="custom-drawer-title">{{ stockName || '个股诊断' }}<span v-if="stockCode" class="custom-drawer-code">{{ stockCode }}</span></span>
      <button class="custom-drawer-close" @click="onUpdateModelValue(false)" aria-label="关闭">
        <el-icon><Close /></el-icon>
      </button>
    </div>
    <div class="drawer-content">
      <!-- 加载状态：仅当没有任何数据时显示骨架 -->
      <el-skeleton :rows="12" animated v-if="loading && !techData" />

      <!-- 错误状态 -->
      <el-card v-else-if="diagnosisFailed && !techData" shadow="never" class="error-card">
        <div style="text-align:center;padding:20px">
          <el-icon :size="48" color="#E6A23C"><WarningFilled /></el-icon>
          <p style="margin:12px 0;color:#909399">{{ diagnosisErrorMsg }}</p>
          <el-button type="primary" @click="refreshData">重新加载</el-button>
        </div>
      </el-card>

      <!-- 主内容（任何时候只要 techData 有值就显示） -->
      <template v-else-if="techData">
        <!-- 调试状态（开发模式可见） -->
        <div v-if="false" class="debug-bar" style="background:#fdf6ec;padding:8px 12px;font-size:12px;border-radius:4px;margin-bottom:8px;">
          <div>stockCode: {{ stockCode }} | loading: {{ loading }} | techData: {{ techData ? '✓' : '✗' }} | assessData: {{ assessData ? '✓' : '✗' }} | score: {{ weightedScore }} | patterns: {{ patternList.length }} | news: {{ newsList.length }}</div>
        </div>

        <!-- 实时行情 -->
        <el-card shadow="hover" class="result-card" v-if="rtItems.length">
          <template #header><span>实时行情 — {{ stockName }} ({{ stockCode }})</span></template>
          <el-row :gutter="12">
            <el-col :xs="12" :sm="8" :md="4" :lg="3" v-for="item in rtItems" :key="item.label">
              <div class="rt-item">
                <div class="rt-label">{{ item.label }}</div>
                <div class="rt-value" :class="item.cls">{{ item.value }}</div>
              </div>
            </el-col>
          </el-row>
          <div class="section-analysis" v-if="rtAnalysis">
            <el-icon><DataLine /></el-icon>
            <span>{{ rtAnalysis }}</span>
          </div>
        </el-card>

        <!-- 综合诊断结论（核心决策信息前置） -->
        <el-card shadow="hover" class="result-card assess-card" v-if="techData">
          <template #header>
            <div class="card-header">
              <div class="title-block">
                <span class="title-main">综合诊断结论</span>
                <span class="title-sub">技术面65% + 基本面25% + 资金面10%</span>
                <span class="title-time" v-if="diagnoseTime">· 更新 {{ diagnoseTime }}</span>
              </div>
              <div class="header-right">
                <div class="score-box" :class="scoreClass">
                  <span class="score-value">{{ weightedScore ?? '--' }}</span>
                  <span class="score-max">/100</span>
                  <span class="score-level-title" v-if="weightedScore != null">{{ scoreLevelTitle }}</span>
                </div>
                <el-tooltip :content="riskReasons.length ? riskReasons.join('；') : '暂无风险提示'" placement="top" :show-after="200">
                  <div class="risk-stars" :class="riskClass">{{ riskStars }}</div>
                </el-tooltip>
              </div>
            </div>
          </template>

          <!-- 评分构成 + 风险提示（合并紧凑布局） -->
          <div class="score-risk-section" v-if="scoreBreakdown">
            <div class="score-breakdown">
              <div class="sb-row" v-for="item in scoreBreakdownList" :key="item.key">
                <div class="sb-label">
                  <span class="sb-name">{{ item.name }}</span>
                  <span class="sb-weight">{{ item.weightText }}</span>
                </div>
                <div class="sb-bar-wrap">
                  <div class="sb-bar" :style="{ width: item.score + '%', background: item.color }"></div>
                </div>
                <div class="sb-score" :style="{ color: item.color }">{{ item.score }}</div>
              </div>
            </div>
            <div class="risk-tags-inline" v-if="riskReasons.length">
              <el-icon class="risk-icon"><WarningFilled /></el-icon>
              <el-tag v-for="(r, i) in riskReasons.slice(0, 3)" :key="i" type="warning" size="small" effect="plain" class="risk-tag">{{ r }}</el-tag>
            </div>
          </div>

          <!-- 结论 + 关键位 + 消息面（合并一行） -->
          <div class="decision-strip">
            <el-alert :title="assessData?.title || '数据加载中'" :type="assessData?.type || 'info'" show-icon :closable="false" class="decision-alert" />
            <div class="key-levels" v-if="assessData?.support || assessData?.resist">
              <el-tag type="success" size="small" v-if="assessData?.resist">压力 ¥{{ assessData.resist }}</el-tag>
              <el-tag type="danger" size="small" v-if="assessData?.support">支撑 ¥{{ assessData.support }}</el-tag>
            </div>
            <div class="news-sentiment-inline" v-if="newsSentiment">
              <el-tag :type="newsSentiment.type === 'positive' ? 'danger' : newsSentiment.type === 'negative' ? 'success' : 'info'" size="small" effect="dark">
                {{ newsSentiment.text }}
              </el-tag>
            </div>
          </div>

          <!-- 风险与得分冲突警示 -->
          <el-alert v-if="riskConflict" type="warning" show-icon :closable="false" class="risk-conflict-alert"
            title="注意：综合评分偏高但存在多个风险因素" />

          <!-- 综合分析（紧凑列表） -->
          <div class="analysis-block" v-if="analysisLines.length">
            <ul class="analysis-list">
              <li v-for="(line, i) in analysisLines" :key="i" class="analysis-item">
                <span class="dot" :class="getAnalysisDotClass(i, analysisLines.length)"></span>
                <span class="text">{{ line }}</span>
              </li>
            </ul>
          </div>

          <div class="metrics-grid">
            <div class="metric-card">
              <div class="metric-title"><el-icon><Money /></el-icon><span>操作建议</span></div>
              <div class="metric-body" v-if="pricePlan">
                <div class="m-row"><span class="m-label">买入区间</span><span class="m-val">¥{{ pricePlan.buyLow }}-{{ pricePlan.buyHigh }}</span></div>
                <div class="m-row"><span class="m-label">止损位</span><span class="m-val">¥{{ pricePlan.stopLoss }}<em class="m-pct">{{ pricePlan.stopPct == null ? '--' : (pricePlan.stopPct > 0 ? '+' : '') + pricePlan.stopPct + '%' }}</em></span></div>
                <div class="m-row"><span class="m-label">保守目标</span><span class="m-val">¥{{ pricePlan.target1 }}<em class="m-pct">{{ pricePlan.target1Pct == null ? '--' : (pricePlan.target1Pct > 0 ? '+' : '') + pricePlan.target1Pct + '%' }}</em></span></div>
                <div class="m-row"><span class="m-label">中性目标</span><span class="m-val">¥{{ pricePlan.target2 }}<em class="m-pct">{{ pricePlan.target2Pct == null ? '--' : (pricePlan.target2Pct > 0 ? '+' : '') + pricePlan.target2Pct + '%' }}</em></span></div>
                <div class="m-row"><span class="m-label">乐观目标</span><span class="m-val">¥{{ pricePlan.target3 }}<em class="m-pct">{{ pricePlan.target3Pct == null ? '--' : (pricePlan.target3Pct > 0 ? '+' : '') + pricePlan.target3Pct + '%' }}</em></span></div>
                <div class="m-row position-row" v-if="positionAdvice"><span class="m-label">建议仓位</span><span class="m-val">{{ positionAdvice.ratio }} ({{ positionAdvice.text }})</span></div>
              </div>
              <div class="metric-empty" v-else>--</div>
            </div>

            <div class="metric-card">
              <div class="metric-title"><el-icon><Clock /></el-icon><span>分周期建议</span></div>
              <div class="metric-body" v-if="multiPeriodAdvice">
                <div class="m-row"><span class="m-label">短线1-3日</span><span class="m-val" :class="multiPeriodAdvice.short.type">{{ multiPeriodAdvice.short.text }}</span></div>
                <div class="m-row"><span class="m-label">中线1-2周</span><span class="m-val" :class="multiPeriodAdvice.mid.type">{{ multiPeriodAdvice.mid.text }}</span></div>
                <div class="m-row"><span class="m-label">长线1-3月</span><span class="m-val" :class="multiPeriodAdvice.long.type">{{ multiPeriodAdvice.long.text }}</span></div>
              </div>
              <div class="metric-empty" v-else>--</div>
            </div>

            <div class="metric-card">
              <div class="metric-title"><el-icon><DataLine /></el-icon><span>近期表现</span></div>
              <div class="metric-body" v-if="recentPerformance">
                <div class="m-row" v-for="r in recentPerformance" :key="r.label"><span class="m-label">{{ r.label }}</span><span class="m-val" :class="r.cls">{{ r.text }}</span></div>
              </div>
              <div class="metric-empty" v-else>--</div>
            </div>

            <div class="metric-card">
              <div class="metric-title"><el-icon><Coin /></el-icon><span>资金流</span></div>
              <div class="metric-body" v-if="flowTrend">
                <div class="m-row"><span class="m-label">今日主力</span><span class="m-val" :class="flowTrend.today.cls">{{ flowTrend.today.text }}</span></div>
                <div class="m-row"><span class="m-label">大单净额</span><span class="m-val" :class="flowTrend.bigNet.cls">{{ flowTrend.bigNet.text }}</span></div>
                <div class="m-row"><span class="m-label">中单净额</span><span class="m-val" :class="flowTrend.midNet.cls">{{ flowTrend.midNet.text }}</span></div>
                <div class="m-row"><span class="m-label">小单净额</span><span class="m-val" :class="flowTrend.smallNet.cls">{{ flowTrend.smallNet.text }}</span></div>
                <div class="m-row" v-if="flowTrend.flow3d.cls !== 'flow-na'"><span class="m-label">3日累计</span><span class="m-val" :class="flowTrend.flow3d.cls">{{ flowTrend.flow3d.text }}</span></div>
              </div>
              <div class="metric-empty" v-else>--</div>
            </div>
          </div>

          <!-- 买卖理由（紧凑标签式） -->
          <div class="signals-compact" v-if="topBuyReasons.length || topSellReasons.length">
            <div class="signal-row buy" v-if="topBuyReasons.length">
              <el-icon class="signal-icon"><CaretBottom /></el-icon>
              <el-tag v-for="(r, i) in topBuyReasons.slice(0, 3)" :key="i" type="danger" size="small" effect="plain" class="signal-tag">{{ r }}</el-tag>
            </div>
            <div class="signal-row sell" v-if="topSellReasons.length">
              <el-icon class="signal-icon"><CaretTop /></el-icon>
              <el-tag v-for="(r, i) in topSellReasons.slice(0, 3)" :key="i" type="success" size="small" effect="plain" class="signal-tag">{{ r }}</el-tag>
            </div>
          </div>
        </el-card>

        <!-- K线图 -->
        <el-card shadow="hover" class="result-card" v-if="techData && !loading">
          <template #header>
            <div class="kline-header">
              <span class="kline-title">K线图表 — {{ stockName }} ({{ stockCode }})</span>
              <el-radio-group v-model="klinePeriod" size="small" class="kline-period-group">
                <el-radio-button value="daily">日K</el-radio-button>
                <el-radio-button value="weekly">周K</el-radio-button>
                <el-radio-button value="monthly">月K</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <KlineChart v-if="stockCode" :stock-code="stockCode" :period="klinePeriod" :height="380" />
        </el-card>

        <!-- 技术指标信号 -->
        <el-card shadow="hover" class="result-card tech-card">
          <template #header>
            <div class="card-header">
              <div class="title-block">
                <span class="title-main">技术指标信号</span>
                <span class="title-sub">共 {{ techTable.length }} 项指标</span>
              </div>
              <div class="tech-summary">
                <div class="summary-item buy" v-if="buySignals.length">
                  <span class="summary-dot"></span>
                  <span>{{ buySignals.length }} 买入</span>
                </div>
                <div class="summary-item sell" v-if="sellSignals.length">
                  <span class="summary-dot"></span>
                  <span>{{ sellSignals.length }} 卖出</span>
                </div>
              </div>
            </div>
          </template>

          <div class="tech-grid">
            <div class="tech-section">
              <div class="tech-section-header trend">
                <div class="section-icon"><el-icon><DataLine /></el-icon></div>
                <div class="section-info">
                  <span class="section-title">趋势 / 动量</span>
                  <span class="section-count">{{ techTableLeft.length }} 项</span>
                </div>
                <div class="section-badge" :class="getTrendBadgeClass()">{{ getTrendSummary() }}</div>
              </div>
              <div class="tech-list-header">
                <span class="col-name">指标名称</span>
                <span class="col-value">数值</span>
                <span class="col-signal">信号</span>
              </div>
              <div class="tech-items">
                <div class="tech-item" v-for="item in techTableLeft" :key="item.name">
                  <div class="item-col item-name">
                    <span class="name-text">{{ item.name }}</span>
                    <span class="name-desc" v-if="item.desc">{{ item.desc }}</span>
                  </div>
                  <div class="item-col item-value" :class="'val-' + item.signalType">{{ formatTechVal(item.value) }}</div>
                  <div class="item-col item-signal">
                    <div class="signal-indicator" :class="item.signalType"></div>
                    <el-tag :type="item.signalType" size="small" effect="light" class="signal-tag">{{ item.signal }}</el-tag>
                  </div>
                </div>
              </div>
            </div>

            <div class="tech-section">
              <div class="tech-section-header oscillation">
                <div class="section-icon"><el-icon><Coin /></el-icon></div>
                <div class="section-info">
                  <span class="section-title">震荡 / 量能</span>
                  <span class="section-count">{{ techTableRight.length }} 项</span>
                </div>
                <div class="section-badge" :class="getOscillationBadgeClass()">{{ getOscillationSummary() }}</div>
              </div>
              <div class="tech-list-header">
                <span class="col-name">指标名称</span>
                <span class="col-value">数值</span>
                <span class="col-signal">信号</span>
              </div>
              <div class="tech-items">
                <div class="tech-item" v-for="item in techTableRight" :key="item.name">
                  <div class="item-col item-name">
                    <span class="name-text">{{ item.name }}</span>
                    <span class="name-desc" v-if="item.desc">{{ item.desc }}</span>
                  </div>
                  <div class="item-col item-value" :class="'val-' + item.signalType">{{ formatTechVal(item.value) }}</div>
                  <div class="item-col item-signal">
                    <div class="signal-indicator" :class="item.signalType"></div>
                    <el-tag :type="item.signalType" size="small" effect="light" class="signal-tag">{{ item.signal }}</el-tag>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="section-analysis" v-if="techAnalysis">
            <el-icon><DataLine /></el-icon>
            <span>{{ techAnalysis }}</span>
          </div>
        </el-card>

        <!-- K线形态识别 -->
        <el-card shadow="hover" class="result-card pattern-card" v-if="patternList.length">
          <template #header>
            <div class="pattern-header-bar">
              <span>K线形态识别</span>
              <el-radio-group v-model="patternDirectionFilter" size="small">
                <el-radio-button value="all">全部</el-radio-button>
                <el-radio-button value="bullish">看涨</el-radio-button>
                <el-radio-button value="bearish">看跌</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <div class="pattern-table">
            <div class="pattern-header">
              <span class="col-direction">方向</span>
              <span class="col-name">形态</span>
              <span class="col-date">日期</span>
              <span class="col-confidence">置信度</span>
            </div>
            <div class="pattern-body">
              <div class="pattern-row" v-for="(row, index) in displayPatterns" :key="index">
                <div class="col-direction">
                  <el-tag :type="row.direction === 'bullish' ? 'danger' : row.direction === 'bearish' ? 'success' : 'info'" size="small">
                    {{ row.direction === 'bullish' ? '看涨' : row.direction === 'bearish' ? '看跌' : '中性' }}
                  </el-tag>
                </div>
                <div class="col-name">{{ row.name }}</div>
                <div class="col-date">{{ row.date }}</div>
                <div class="col-confidence">
                  <span :style="{ color: getConfidenceColor(row), fontWeight: 'bold' }">
                    {{ Math.round((row.confidence||0.5)*100) }}%
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div class="pattern-footer" v-if="patternHasMore || patternShowAll">
            <el-button text type="primary" size="small" @click="patternShowAll = !patternShowAll">
              {{ patternShowAll ? '收起' : `查看全部 (${patternList.length}条)` }}
            </el-button>
          </div>
          <div class="section-analysis" v-if="patternAnalysis">
            <el-icon><DataLine /></el-icon>
            <span>{{ patternAnalysis }}</span>
          </div>
        </el-card>

        <!-- 财务数据 -->
        <el-card shadow="hover" class="result-card" v-if="financialData">
          <template #header><span>财务数据 (最新季报)</span></template>
          <el-row :gutter="16">
            <el-col :xs="6" :sm="4" :md="3" v-for="item in finItems" :key="item.label">
              <div class="fin-item">
                <div class="fin-label">{{ item.label }}</div>
                <div class="fin-value" :class="item.cls">{{ item.value }}</div>
              </div>
            </el-col>
          </el-row>
          <div class="section-analysis" v-if="finAnalysis">
            <el-icon><DataLine /></el-icon>
            <span>{{ finAnalysis }}</span>
          </div>
        </el-card>

        <!-- 消息面分析 -->
        <el-card shadow="hover" class="result-card news-section" v-if="stockCode && !loading">
          <template #header>
            <div class="news-header">
              <span><el-icon><Bell /></el-icon> 消息面 — {{ stockName }}</span>
              <span class="news-count">
                <template v-if="newsCount">{{ newsCount }}条相关</template>
                <el-icon v-else-if="newsRefreshing" class="is-loading"><Loading /></el-icon>
              </span>
            </div>
          </template>
          <div v-if="newsList.length > 0" class="news-list">
            <div v-for="(n, i) in newsList" :key="i" class="news-item">
              <el-tag size="small" :type="n.sentiment === 'positive' ? 'danger' : n.sentiment === 'negative' ? 'success' : ''" effect="light" class="news-sentiment">{{ n.source || '资讯' }}</el-tag>
              <span class="news-title" @click="openNews(n)">{{ n.title }}</span>
              <span class="news-date">{{ n.date }}</span>
            </div>
          </div>
          <div v-else class="news-empty">
            <el-icon v-if="newsError"><WarningFilled /></el-icon>
            <el-icon v-else><Bell /></el-icon>
            <span v-if="newsLoading && !newsDataVal && !newsTimedOut">加载中...</span>
            <span v-else-if="newsTimedOut">资讯服务响应超时，请稍后刷新</span>
            <span v-else-if="newsRefreshing">正在获取最新资讯...</span>
            <span v-else-if="newsError">消息面数据获取失败</span>
            <span v-else>暂无相关新闻/公告</span>
          </div>
        </el-card>
      </template>

      <!-- 空状态 -->
      <el-empty v-if="!loading && !techData && !diagnosisFailed" description="暂无诊断数据" />
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { stockApi } from '@/api'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import { DataLine, Money, Clock, Coin, CaretTop, CaretBottom, Bell, WarningFilled, Loading, Close, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import KlineChart from './KlineChart.vue'
import { useStockDiagnosisComputed } from '@/composables/useStockDiagnosisComputed.js'
import { buildAnalysisCtx, runAnalysis, buildMultiPeriodAdvice, getScoreLevel, getPositionAdvice } from '@/composables/useAnalysisRules.js'

const props = defineProps({
  modelValue: Boolean,
  stockCode: String,
})

const emit = defineEmits(['update:modelValue'])

// 数据获取
const diagnosis = useCachedFetch({
  key: () => `stock:diag:${props.stockCode}`,
  fetcher: () => {
    if (!props.stockCode) throw new Error('未设置股票代码')
    return stockApi.getDiagnosis(props.stockCode)
  },
  tier: CACHE_TIERS.STOCK,
  immediate: false,
})

const patterns = useCachedFetch({
  key: () => `stock:patterns:${props.stockCode}`,
  fetcher: () => {
    if (!props.stockCode) throw new Error('未设置股票代码')
    return stockApi.getPatterns(props.stockCode)
  },
  tier: CACHE_TIERS.STOCK,
  immediate: false,
})

const newsData = useCachedFetch({
  key: () => `stock:news:${props.stockCode}`,
  fetcher: ({ signal }) => {
    if (!props.stockCode) throw new Error('未设置股票代码')
    return stockApi.getNews(props.stockCode, 5, signal)
  },
  tier: CACHE_TIERS.STOCK,
  immediate: false,
  onSuccess: (res) => {
    console.log('[Drawer] news onSuccess:', { count: res?.count, newsLen: res?.news?.length, firstTitle: res?.news?.[0]?.title })
    return res
  },
  onError: (e) => {
    console.error('[Drawer] news fetch error:', e?.message, e?.response?.data)
  },
})

// 顶层解包：模板自动解包顶层 ref，普通对象属性需要手动解包
const newsDataVal = computed(() => newsData.data?.value)
const newsLoading = computed(() => newsData.loading?.value === true)
const newsRefreshing = computed(() => newsData.refreshing?.value === true)
const newsError = computed(() => newsData.error?.value)
const newsList = computed(() => newsDataVal.value?.news || [])
const newsCount = computed(() => newsDataVal.value?.count || 0)

const klinePeriod = ref('daily')

function loadAllData() {
  if (!props.stockCode) return
  console.log('[Drawer] loadAllData for', props.stockCode, 'visible=', props.modelValue)
  diagnosis.refresh().catch(() => {})
  patterns.refresh()
  newsData.refresh()
}

// 代码变化时加载（immediate 确保挂载时已有代码就触发）
watch(() => props.stockCode, (newCode) => {
  if (newCode) loadAllData()
}, { immediate: true })

// 抽屉打开时刷新（仅在数据为空时，避免和上面的重复）
watch(() => props.modelValue, (visible) => {
  if (visible && props.stockCode && !diagnosis.data.value) {
    loadAllData()
  }
})

// 兜底：挂载后有代码但无数据时强制加载
onMounted(() => {
  if (props.stockCode && !diagnosis.data.value) {
    loadAllData()
  }
})

const techData = computed(() => {
  const d = diagnosis.data.value
  if (!d) return null
  return d.technical_indicators || d
})
const stockName = computed(() => techData.value?.name || props.stockCode || '')
const patternList = computed(() => patterns.data.value?.patterns || [])
const loading = computed(() => diagnosis.loading.value)
const diagnosisFailed = computed(() => diagnosis.data.value?.error === true && !loading.value)
const diagnosisErrorMsg = computed(() => diagnosis.data.value?.error_msg || diagnosis.data.value?.message || '诊断服务异常，请稍后重试')

// 模式与方向过滤
const patternShowAll = ref(false)
const patternDirectionFilter = ref('all')
const displayPatterns = computed(() => {
  let list = patternList.value
  if (patternDirectionFilter.value !== 'all') {
    list = list.filter(p => p.direction === patternDirectionFilter.value)
  }
  return patternShowAll.value ? list : list.slice(-8)
})
const patternHasMore = computed(() => {
  let list = patternList.value
  if (patternDirectionFilter.value !== 'all') {
    list = list.filter(p => p.direction === patternDirectionFilter.value)
  }
  return list.length > 8
})

// 消息面超时
const newsTimedOut = ref(false)
let newsTimer = null
watch([() => newsData.loading, () => props.stockCode], ([ld, code]) => {
  if (newsTimer) { clearTimeout(newsTimer); newsTimer = null }
  newsTimedOut.value = false
  if (ld && code) {
    newsTimer = setTimeout(() => {
      if (newsData.loading?.value && !newsData.data?.value) newsTimedOut.value = true
    }, 8000)
  }
}, { immediate: true })

// 操作建议防御 — 委托给共享 composable（统一逻辑、防御 NaN/Infinity）
// ── 共享 computed ──
const financialData = computed(() => techData.value?.financial || techData.value?.financial_data || null)
const { assessData, buySignals, sellSignals, weightedScore, scoreClass, riskStars, riskClass, riskReasons, recentPerformance, flowTrend, finItems, rtItems, pricePlan, techTable, techTableLeft, techTableRight, getTrendSummary, getTrendBadgeClass, getOscillationSummary, getOscillationBadgeClass } = useStockDiagnosisComputed(techData, financialData)
const multiPeriodAdvice = computed(() =>
  buildMultiPeriodAdvice(techData.value?.indicators, techData.value?.realtime, financialData.value, props.stockCode, stockName.value)
)

// ── P2/P3 新增 computed（与 StockDiagnosis.vue 同步）──
const scoreBreakdown = computed(() => techData.value?.score_breakdown ?? null)
const diagnoseTime = computed(() => techData.value?.diagnose_time ?? null)
const riskLevel = computed(() => techData.value?.risk_level ?? null)
const riskConflict = computed(() => {
  const r = riskLevel.value
  if (!r) return false
  return r.score_conflict === true || (r.level >= 4 && (weightedScore.value ?? 0) >= 70)
})
const positionAdvice = computed(() => getPositionAdvice(weightedScore.value))
const conclusionLevel = computed(() => getScoreLevel(weightedScore.value))
const scoreLevelTitle = computed(() => conclusionLevel.value.title)

// 技术面分项标签
const subScoreLabel = {
  trend: '趋势', volume: '量能', macd: 'MACD',
  kdj: 'KDJ', rsi: 'RSI', boll: 'BOLL',
}
// 评分构成可视化列表
const scoreBreakdownList = computed(() => {
  const sb = scoreBreakdown.value
  if (!sb) return []
  const weights = sb.weights || { technical: 0.65, fundamental: 0.25, capital_flow: 0.10 }
  const colorFor = (s) => {
    if (s >= 75) return '#f56c6c'
    if (s >= 60) return '#e6a23c'
    if (s >= 45) return '#909399'
    if (s >= 30) return '#67c23a'
    return '#4e9a4e'
  }
  return [
    { key: 'technical',    name: '技术面', score: sb.technical ?? 0,    weightText: (weights.technical * 100).toFixed(0) + '%',  color: colorFor(sb.technical ?? 0) },
    { key: 'fundamental',  name: '基本面', score: sb.fundamental ?? 0,  weightText: (weights.fundamental * 100).toFixed(0) + '%', color: colorFor(sb.fundamental ?? 0) },
    { key: 'capital_flow', name: '资金面', score: sb.capital_flow ?? 0, weightText: (weights.capital_flow * 100).toFixed(0) + '%', color: colorFor(sb.capital_flow ?? 0) },
  ]
})

// 综合分析
const analysisResult = computed(() => {
  const ind = techData.value?.indicators
  const fin = financialData.value || {}
  const rt = techData.value?.realtime
  if (!ind) return null
  try {
    const ctx = buildAnalysisCtx(ind, fin, rt)
    return runAnalysis(ctx)
  } catch (e) {
    return null
  }
})

const analysisLines = computed(() => {
  if (!analysisResult.value) return []
  const text = analysisResult.value.conclusionText || ''
  return text.split(/[；;]/).map(s => s.trim()).filter(Boolean)
})

function getAnalysisDotClass(index, total) {
  return index === total - 1 ? 'dot-conclusion' : 'dot-normal'
}

// 顶部买入/卖出理由（基于评分排序）
const topBuyReasons = computed(() => {
  const r = analysisResult.value
  if (!r?.hits) return []
  return r.hits
    .filter(h => h.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(h => typeof h.text === 'function' ? h.text(r.ctx) : String(h.text))
})

const topSellReasons = computed(() => {
  const r = analysisResult.value
  if (!r?.hits) return []
  return r.hits
    .filter(h => h.score < 0)
    .sort((a, b) => a.score - b.score)
    .slice(0, 3)
    .map(h => typeof h.text === 'function' ? h.text(r.ctx) : String(h.text))
})

// 消息面情感
const newsSentiment = computed(() => {
  const list = newsData.data?.value?.news || []
  if (list.length === 0) return null
  const counts = { positive: 0, negative: 0, neutral: 0 }
  list.forEach(n => {
    const s = n.sentiment || 'neutral'
    if (counts[s] != null) counts[s]++
  })
  const total = list.length
  if (counts.positive > counts.negative * 1.5) {
    return { type: 'positive', text: `消息面偏多(${counts.positive}/${total}条利好)`, counts }
  }
  if (counts.negative > counts.positive * 1.5) {
    return { type: 'negative', text: `消息面偏空(${counts.negative}/${total}条利空)`, counts }
  }
  return { type: 'neutral', text: `消息面中性(${total}条)`, counts }
})

// 技术指标表格（来自共享 composable）

function formatTechVal(v) {
  if (v == null || isNaN(v)) return '--'
  return typeof v === 'number' ? v.toFixed(2) : String(v)
}

const rtAnalysis = computed(() => null)
const finAnalysis = computed(() => null)
const techAnalysis = computed(() => null)
const patternAnalysis = computed(() => null)

function getConfidenceColor(row) {
  const c = row?.confidence || 0.5
  if (c >= 0.7) return '#67c23a'
  if (c >= 0.5) return '#e6a23c'
  return '#909399'
}

async function openNews(n) {
  try {
    await ElMessageBox.alert(`${n.title}\n\n${n.content || ''}\n\n${n.date || ''}`, '资讯详情', {
      confirmButtonText: '关闭',
      customClass: 'news-message-box',
    })
  } catch (e) {}
}

const isMobile = ref(window.innerWidth < 768)
const drawerSize = computed(() => isMobile.value ? '100%' : '70%')
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

function onUpdateModelValue(val) { emit('update:modelValue', val) }
function handleClose() { emit('update:modelValue', false) }
</script>

<style scoped>
.drawer-content { padding: 12px; flex: 1; min-height: 0; overscroll-behavior: contain; overflow-y: auto; }
:deep(.el-drawer) { overflow: hidden !important; display: flex; flex-direction: column; height: 100% !important; }
:deep(.el-drawer__body) { padding: 0 !important; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden !important; -webkit-overflow-scrolling: touch; overscroll-behavior: contain; }
.result-card { margin-bottom: 12px; overflow: visible; }
.assess-card :deep(.el-card__body) { padding: 8px 14px 10px !important; }
.assess-card :deep(.el-card__header) { padding: 8px 14px !important; min-height: auto; }
.rt-item { text-align: center; padding: 4px; }
.rt-label { font-size: 12px; color: #909399; }
.rt-value { font-size: 16px; font-weight: bold; margin-top: 2px; }
.fin-item { text-align: center; padding: 4px; }
.fin-label { font-size: 12px; color: #909399; }
.fin-value { font-size: 14px; font-weight: bold; margin-top: 2px; }

.kline-header { display: flex; justify-content: space-between; align-items: center; }
.kline-title { font-size: 14px; }
.kline-period-group { flex-shrink: 0; }

.card-header { display: flex; justify-content: space-between; align-items: center; }
.title-block { display: flex; flex-direction: column; gap: 2px; }
.title-main { font-size: 16px; font-weight: bold; }
.title-sub { font-size: 11px; color: #909399; }
.header-right { display: flex; align-items: center; gap: 12px; }
.score-box { font-size: 22px; font-weight: bold; position: relative; }
/* 5 档颜色（与 useAnalysisRules.js CONCLUSION_LEVELS 对齐） */
.score-box.score-strong-bull { color: #d94a4a; }   /* 强势偏多 深红 */
.score-box.score-bull { color: #f56c6c; }          /* 偏多 红 */
.score-box.score-mid { color: #909399; }            /* 中性 灰 */
.score-box.score-bear { color: #67c23a; }           /* 偏空 绿 */
.score-box.score-strong-bear { color: #4e9a4e; }    /* 弱势偏空 深绿 */
.score-box .score-level-title { display: block; font-size: 11px; color: #909399; font-weight: 500; text-align: center; margin-top: 2px; }
.risk-stars { font-size: 16px; cursor: pointer; }
.risk-low { color: #67c23a; }
.risk-mid { color: #e6a23c; }
.risk-high { color: #f56c6c; }

/* 评分 + 风险合并区块（紧凑布局） */
.score-risk-section { margin-bottom: 6px; }
.score-breakdown { padding: 6px 4px 8px; border-bottom: 1px dashed #ebeef5; margin-bottom: 6px; }
.score-breakdown .sb-row { display: grid; grid-template-columns: 80px 1fr 36px; align-items: center; gap: 8px; padding: 2px 0; }
.score-breakdown .sb-label { display: flex; flex-direction: column; gap: 1px; }
.score-breakdown .sb-name { font-size: 12px; color: #303133; font-weight: 500; }
.score-breakdown .sb-weight { font-size: 10px; color: #909399; }
.score-breakdown .sb-bar-wrap { height: 6px; background: #f0f2f5; border-radius: 3px; overflow: hidden; }
.score-breakdown .sb-bar { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
.score-breakdown .sb-score { font-size: 13px; font-weight: 600; text-align: right; }

/* 风险标签内联显示 */
.risk-tags-inline { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; padding: 4px 0 0; }
.risk-tags-inline .risk-icon { color: #e6a23c; font-size: 12px; flex-shrink: 0; }
.risk-tags-inline .risk-tag { font-size: 11px; padding: 0 6px; height: 20px; line-height: 18px; }

/* 风险与得分冲突警示 */
.risk-conflict-alert { margin: 4px 0 6px; }

/* 评分标题时间 */
.title-time { font-size: 10px; color: #c0c4cc; font-weight: 400; }

/* 决策条（结论 + 关键位 + 消息面） */
.decision-strip { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 5px 8px; background: linear-gradient(135deg, #f5f7fa, #fafbfc); border-radius: 6px; border: 1px solid #ebeef5; margin-bottom: 6px; }
.decision-strip .decision-alert { flex: 1; min-width: 0; }
.decision-strip :deep(.el-alert__title) { font-size: 12px; font-weight: 600; }
.decision-strip :deep(.el-alert__content) { padding: 1px 0; }
.decision-strip :deep(.el-alert) { padding: 4px 8px; }
.key-levels { display: flex; align-items: center; gap: 3px; flex-shrink: 0; }
.key-levels .el-tag { font-size: 11px; padding: 0 5px; height: 20px; line-height: 18px; }
.news-sentiment-inline { flex-shrink: 0; }
.news-sentiment-inline .el-tag { font-size: 11px; padding: 0 6px; height: 20px; line-height: 18px; }

/* 综合分析（紧凑列表） */
.analysis-block { background: #fffbf5; border-radius: 6px; padding: 6px 10px; border-left: 3px solid #e6a23c; margin-bottom: 6px; }
.analysis-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 2px; }
.analysis-item { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; line-height: 1.35; color: #606266; }
.analysis-item .dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; margin-top: 7px; background: #c0c4cc; }
.analysis-item .dot.dot-conclusion { width: 8px; height: 8px; margin-top: 6px; background: #e6a23c; box-shadow: 0 0 0 2px rgba(230, 162, 60, 0.15); }
.analysis-item .text { flex: 1; min-width: 0; word-break: break-word; }

/* 操作建议仓位行 */
.metric-body .position-row .m-val { color: #409eff; font-weight: 500; }

/* 2 列指标卡（更紧凑） */
.metrics-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 6px; }
.metric-card { background: #fafbfc; border: 1px solid #ebeef5; border-radius: 6px; padding: 6px 8px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.metric-title { display: flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 600; color: #606266; padding-bottom: 4px; border-bottom: 1px solid #ebeef5; }
.metric-title .el-icon { color: #409eff; font-size: 12px; }
.metric-body { display: flex; flex-direction: column; gap: 3px; }
.m-row { display: flex; justify-content: space-between; align-items: center; font-size: 11px; gap: 6px; }
.m-label { color: #909399; flex-shrink: 0; }
.m-val { font-weight: 600; color: #303133; text-align: right; word-break: break-all; }
.m-val .m-pct { font-style: normal; font-size: 9px; color: #909399; margin-left: 3px; font-weight: normal; }
.m-val.positive { color: #f56c6c; }
.m-val.negative { color: #67c23a; }
.m-val.neutral { color: #606266; }
.metric-empty { text-align: center; color: #c0c4cc; font-size: 11px; padding: 4px 0; }

/* 买卖理由（紧凑标签式） */
.signals-compact { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.signal-row { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.signal-row .signal-icon { font-size: 14px; flex-shrink: 0; }
.signal-row.buy .signal-icon { color: #f56c6c; }
.signal-row.sell .signal-icon { color: #67c23a; }
.signal-row .signal-tag { font-size: 11px; padding: 0 6px; height: 20px; line-height: 18px; }

.tech-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.tech-section { background: #fafafa; border-radius: 6px; padding: 8px; }
.tech-section-header { display: flex; align-items: center; gap: 8px; padding-bottom: 8px; border-bottom: 1px solid #ebeef5; margin-bottom: 8px; }
.section-icon { width: 28px; height: 28px; border-radius: 4px; display: flex; align-items: center; justify-content: center; background: #409eff; color: #fff; }
.section-info { flex: 1; }
.section-title { font-size: 13px; font-weight: bold; }
.section-count { font-size: 11px; color: #909399; margin-left: 4px; }
.section-badge { font-size: 11px; padding: 2px 6px; border-radius: 3px; }
.badge-strong { background: #f56c6c; color: #fff; }
.badge-mid { background: #e6a23c; color: #fff; }
.badge-weak { background: #67c23a; color: #fff; }

.tech-list-header { display: grid; grid-template-columns: 1fr 60px 80px; gap: 8px; font-size: 11px; color: #909399; padding: 4px 0; }
.tech-items { display: block; }
.tech-item { display: grid; grid-template-columns: 1fr 60px 80px; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.tech-item:last-child { border-bottom: none; }
.item-name { display: flex; flex-direction: column; min-width: 0; }
.name-text { font-size: 13px; font-weight: 500; color: #303133; }
.name-desc { font-size: 10px; color: #909399; margin-top: 2px; }
.item-value { text-align: center; font-weight: bold; font-size: 13px; }
.item-signal { display: flex; align-items: center; justify-content: center; gap: 4px; }
.signal-indicator { width: 6px; height: 6px; border-radius: 50%; }
.signal-indicator.primary { background: #409eff; }
.signal-indicator.success { background: #67c23a; }
.signal-indicator.danger { background: #f56c6c; }
.signal-indicator.warning { background: #e6a23c; }
.signal-indicator.info { background: #909399; }
.val-primary { color: #409eff; }
.val-success { color: #67c23a; }
.val-danger { color: #f56c6c; }
.val-warning { color: #e6a23c; }
.val-info { color: #909399; }

.tech-summary { display: flex; gap: 8px; }
.summary-item { display: flex; align-items: center; gap: 4px; font-size: 12px; }
.summary-item.buy { color: #f56c6c; }
.summary-item.sell { color: #67c23a; }
.summary-dot { width: 6px; height: 6px; border-radius: 50%; }
.summary-item.buy .summary-dot { background: #f56c6c; }
.summary-item.sell .summary-dot { background: #67c23a; }

.pattern-header-bar { display: flex; justify-content: space-between; align-items: center; }
.pattern-table { background: #fafafa; border-radius: 6px; padding: 4px; }
.pattern-header, .pattern-row { display: grid; grid-template-columns: 60px 1fr 100px 80px; gap: 8px; padding: 6px 4px; align-items: center; }
.pattern-header { font-size: 11px; color: #909399; }
.pattern-row { border-bottom: 1px solid #f0f0f0; font-size: 12px; }
.pattern-row:last-child { border-bottom: none; }
.col-name, .col-direction, .col-date, .col-confidence { text-align: center; }
.col-name { text-align: left; }
.col-confidence { text-align: right; }
.pattern-footer { text-align: center; padding: 8px 0 0; }
.section-analysis { display: flex; align-items: flex-start; gap: 6px; padding: 8px 10px; margin-top: 8px; background: #f0f9ff; border-radius: 4px; font-size: 12px; color: #606266; }

.news-header { display: flex; align-items: center; gap: 6px; font-weight: bold; }
.news-count { font-size: 12px; color: #909399; font-weight: normal; margin-left: auto; }
.news-list { display: flex; flex-direction: column; gap: 4px; }
.news-item { display: flex; align-items: center; gap: 8px; padding: 8px 4px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.news-item:last-child { border-bottom: none; }
.news-sentiment { flex-shrink: 0; }
.news-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.news-title:hover { color: #409eff; }
.news-date { flex-shrink: 0; font-size: 11px; color: #909399; }
.news-empty { display: flex; align-items: center; gap: 6px; padding: 12px; color: #909399; font-size: 13px; }
.is-loading { animation: rotating 1.4s linear infinite; color: #909399; }
@keyframes rotating { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .drawer-content { padding: 8px; }
  :deep(.el-drawer__body) { padding-top: calc(72px + env(safe-area-inset-top, 0)) !important; }
  .result-card { margin-bottom: 8px; }
  .result-card :deep(.el-card__body) { padding: 10px !important; }
  .result-card :deep(.el-card__header) { padding: 10px !important; }

  /* 评分 + 风险合并区块（移动端紧凑） */
  .score-risk-section { margin-bottom: 6px; }
  .score-breakdown { padding: 4px 0 6px; }
  .score-breakdown .sb-row { grid-template-columns: 64px 1fr 28px; gap: 4px; }
  .score-breakdown .sb-name { font-size: 11px; }
  .score-breakdown .sb-weight { font-size: 9px; }
  .score-breakdown .sb-bar-wrap { height: 5px; }
  .score-breakdown .sb-score { font-size: 11px; }

  /* 风险标签内联（移动端） */
  .risk-tags-inline { gap: 3px; }
  .risk-tags-inline .risk-icon { font-size: 11px; }
  .risk-tags-inline .risk-tag { font-size: 10px; padding: 0 5px; height: 18px; line-height: 16px; }

  /* 决策条（移动端） */
  .decision-strip { flex-direction: column; gap: 6px; padding: 6px 8px; }
  .decision-strip .decision-alert { width: 100%; }
  .key-levels { align-self: flex-start; flex-wrap: wrap; gap: 3px; }
  .key-levels .el-tag { font-size: 10px; padding: 0 4px; height: 20px; line-height: 18px; }
  .news-sentiment-inline .el-tag { font-size: 10px; padding: 0 5px; height: 18px; line-height: 16px; }

  /* 综合分析（移动端） */
  .analysis-block { padding: 4px 8px; }
  .analysis-item { font-size: 11px; line-height: 1.4; }

  /* 指标卡（移动端单列） */
  .metrics-grid { grid-template-columns: 1fr !important; gap: 6px; }
  .metric-card { padding: 6px 8px; }
  .metric-title { font-size: 11px; margin-bottom: 3px; }
  .m-row { font-size: 11px; padding: 1px 0; }
  .m-label { min-width: 56px; font-size: 10px; }
  .m-val { font-size: 11px; }

  /* 买卖理由（移动端） */
  .signals-compact { gap: 3px; }
  .signal-row { gap: 3px; }
  .signal-row .signal-icon { font-size: 12px; }
  .signal-row .signal-tag { font-size: 10px; padding: 0 5px; height: 18px; line-height: 16px; }

  /* 评分等级标题隐藏，避免手机端拥挤 */
  .score-box .score-level-title { display: none; }
  .title-time { display: none; }

  .tech-grid { grid-template-columns: 1fr; gap: 8px; }
  .tech-section { padding: 6px; }
  .tech-section-header { padding-bottom: 6px; margin-bottom: 6px; }
  .section-title { font-size: 12px; }
  .tech-list-header { font-size: 10px; grid-template-columns: 1fr 50px 65px; gap: 6px; }
  .tech-item { grid-template-columns: 1fr 50px 65px; gap: 6px; padding: 6px 0; }
  .name-text { font-size: 12px; }
  .name-desc { font-size: 9px; }
  .item-value { font-size: 12px; }

  .pattern-header, .pattern-row { grid-template-columns: 50px 1fr 70px 55px; font-size: 11px; gap: 6px; padding: 5px 2px; }

  .card-header { flex-direction: column; align-items: flex-start; gap: 6px; }
  .header-right { width: 100%; justify-content: space-between; }
  .score-box { font-size: 20px; }
  .risk-stars { font-size: 14px; }

  .title-main { font-size: 14px; }
  .title-sub { font-size: 10px; }

  .kline-header { flex-direction: column; align-items: flex-start; gap: 6px; }
  .kline-title { font-size: 13px; }

  .news-item { font-size: 12px; padding: 6px 2px; }
  .news-date { font-size: 10px; }
  .news-empty { font-size: 12px; padding: 8px; }

  .rt-item { padding: 3px; }
  .rt-label { font-size: 11px; }
  .rt-value { font-size: 14px; }

  .fin-item { padding: 3px; }
  .fin-label { font-size: 11px; }
  .fin-value { font-size: 13px; }

  .section-analysis { font-size: 11px; padding: 6px 8px; }
}
</style>

<style>
/* Drawer 层级控制：移动端弹窗在 app-header(z-index:90) 下方，不遮挡系统菜单栏 */
@media (max-width: 768px) {
  .el-overlay {
    z-index: 85 !important;
    top: 48px !important;
  }
  .el-drawer {
    z-index: 88 !important;
  }
  /* header fixed 脱离文档流，body 需要 padding-top 补偿 */
  .el-drawer__body {
    padding-top: 50px !important;
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px) !important;
  }
}
@media (max-width: 480px) {
  .el-overlay {
    top: 44px !important;
  }
  .el-drawer__body {
    padding-top: 46px !important;
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px) !important;
  }
}

/* 自定义 drawer header（始终明显的关闭按钮，全局样式因为 el-drawer teleport 到 body） */
.custom-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
  position: sticky;
  top: 0;
  z-index: 100;
  flex-shrink: 0;
}
.custom-drawer-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.custom-drawer-code {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 8px;
}
.custom-drawer-close {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: #f5f7fa;
  color: #606266;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
  margin-left: 12px;
  transition: all 0.2s;
}
.custom-drawer-close:hover {
  background: #ecf5ff;
  color: #409eff;
}
.custom-drawer-close .el-icon {
  font-size: 22px;
}

/* 移动端适配：header fixed 定位在 app-header 正下方 */
@media (max-width: 768px) {
  .custom-drawer-header {
    padding: 4px 12px;
    position: fixed !important;
    top: 48px !important;
    left: 0 !important;
    right: 0 !important;
    z-index: 95 !important;
  }
  .custom-drawer-title { font-size: 15px; }
  .custom-drawer-close {
    width: 36px;
    height: 36px;
    font-size: 20px;
    background: #f5f7fa;
    color: #909399;
  }
  .custom-drawer-close:hover {
    background: #e6a23c;
    color: #fff;
  }
  .custom-drawer-close .el-icon { font-size: 22px; }
}

@media (max-width: 480px) {
  .custom-drawer-header { top: 44px !important; padding: 2px 10px; }
  .custom-drawer-title { font-size: 14px; }
}
</style>
