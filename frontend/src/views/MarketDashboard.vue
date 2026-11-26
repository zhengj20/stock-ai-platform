<template>
  <div class="market-dashboard">
    <!-- Header -->
    <div class="dashboard-header">
      <div class="header-left">
        <h2 class="page-title">市场看板</h2>
        <span class="header-divider">|</span>
        <span class="update-time" v-if="headerInfoText">{{ headerInfoText }}</span>
        <span class="update-time placeholder" v-else>加载中…</span>
        <el-tag size="small" type="info" effect="plain" round v-if="anyFromCache" class="ml-1">缓存</el-tag>
      </div>
      <div class="header-right">
        <el-button :icon="Refresh" @click="refreshAll" :loading="anyLoading" size="default" plain>
          刷新数据
        </el-button>
      </div>
    </div>

    <!-- 后台刷新提示（不遮挡） -->
    <RefreshingIndicator :show="anyRefreshing" text="后台数据更新中" />

    <!-- 全屏加载失败 -->
    <el-empty
      v-if="allFailed && !hasAnyData"
      description="数据加载失败"
      class="fetch-error-empty"
    >
      <template #image>
        <el-icon class="fetch-error-icon"><WarningFilled /></el-icon>
      </template>
      <template #default>
        <div class="fetch-error-text">{{ firstErrorMsg || '请检查网络或后端服务后重试' }}</div>
        <el-button type="primary" :icon="Refresh" @click="refreshAll" :loading="anyLoading">重新加载</el-button>
      </template>
    </el-empty>

    <!-- 全屏空数据 -->
    <el-empty
      v-else-if="allEmpty"
      :description="emptyHint"
      class="fetch-error-empty"
    >
      <template #image>
        <el-icon class="fetch-error-icon"><InfoFilled /></el-icon>
      </template>
      <template #default>
        <div class="fetch-error-text">非交易时段可能暂无最新数据</div>
        <el-button type="primary" :icon="Refresh" @click="refreshAll" :loading="anyLoading">重新加载</el-button>
      </template>
    </el-empty>

    <!-- 移动端内容：使用 mobile.css 设计系统类 -->
    <template v-else-if="isMobile && hasAnyData">
      <div class="mobile-page">

        <!-- 指数卡片横向滑动 -->
        <IndexCards :indices="indices" :loading="indicesKline.loading.value" />

        <!-- 市场概览卡片 -->
        <div class="m-section-header">市场概览</div>
        <div class="m-card m-overview-card">
          <!-- 第一行：涨跌统计 + 情绪分 -->
          <div class="m-sentiment-row">
            <div class="m-stat-item"><span class="num up">{{ breadthData.up || 0 }}</span><span class="label">上涨</span></div>
            <div class="m-stat-item"><span class="num down">{{ breadthData.down || 0 }}</span><span class="label">下跌</span></div>
            <div class="m-stat-item"><span class="num up">{{ limitUpCount }}</span><span class="label">涨停</span></div>
            <div class="m-stat-item"><span class="num down">{{ limitDownCount }}</span><span class="label">跌停</span></div>
            <div class="m-stat-item"><span class="num warn">{{ sentimentScoreVal }}</span><span class="label">情绪</span></div>
          </div>

          <!-- 第二行：资金流向 -->
          <template v-if="sentiment.money_flow">
            <div class="m-divider"></div>
            <div class="m-flow-row">
              <div class="m-flow-item">
                <span class="flow-label">主力净流入</span>
                <span class="flow-val" :class="moneyFlowNet >= 0 ? 'up' : 'down'">{{ moneyFlowNet >= 0 ? '+' : '' }}{{ formatYi(moneyFlowNet) }}亿</span>
              </div>
              <div class="m-flow-item">
                <span class="flow-label">超大单</span>
                <span class="flow-val" :class="(sentiment.money_flow.super_large_net || 0) >= 0 ? 'up' : 'down'">{{ sentiment.money_flow.super_large_net != null ? (sentiment.money_flow.super_large_net >= 0 ? '+' : '') + formatYi(sentiment.money_flow.super_large_net) : '—' }}亿</span>
              </div>
              <div class="m-flow-item">
                <span class="flow-label">大单</span>
                <span class="flow-val" :class="(sentiment.money_flow.large_net || 0) >= 0 ? 'up' : 'down'">{{ sentiment.money_flow.large_net != null ? (sentiment.money_flow.large_net >= 0 ? '+' : '') + formatYi(sentiment.money_flow.large_net) : '—' }}亿</span>
              </div>
            </div>
          </template>

          <!-- 第三行：北向资金 -->
          <template v-if="northboundHasData">
            <div class="m-divider"></div>
            <div class="m-north-row">
              <div class="m-flow-item">
                <span class="flow-label">北向资金</span>
                <span class="flow-val" :class="(northboundNet || 0) >= 0 ? 'up' : 'down'">{{ northboundNet >= 0 ? '+' : '' }}{{ formatYi(northboundNet) }}亿</span>
              </div>
              <div class="m-flow-item">
                <span class="flow-label">沪股通</span>
                <span class="flow-val" :class="(northboundHgt || 0) >= 0 ? 'up' : 'down'">{{ formatYi(northboundHgt) }}亿</span>
              </div>
              <div class="m-flow-item">
                <span class="flow-label">深股通</span>
                <span class="flow-val" :class="(northboundSgt || 0) >= 0 ? 'up' : 'down'">{{ formatYi(northboundSgt) }}亿</span>
              </div>
            </div>
          </template>

          <!-- 第四行：大盘成交额 -->
          <template v-if="volumeTotal">
            <div class="m-divider"></div>
            <div class="m-meta-row">
              <span class="meta-label">两市成交</span>
              <span class="meta-val">{{ formatTurnover(volumeTotal) }}</span>
            </div>
          </template>
        </div>

        <!-- 热门板块标签 (m-section-header + m-hscroll/m-tag) -->
        <div class="m-section-header">热门板块<span class="meta" @click="$router.push('/sector-analysis')">更多 ›</span></div>
        <div class="m-card m-card-compact">
          <div class="m-sector-grid">
            <span v-for="s in sectorList.slice(0, 20)" :key="s.name" class="m-tag" @click="$router.push('/sector-analysis')">
              {{ s.name }}
              <span :class="s.change_pct && s.change_pct >= 0 ? 'up' : 'down'">{{ s.change_pct ? (s.change_pct >= 0 ? '+' : '') + s.change_pct.toFixed(1) + '%' : '' }}</span>
            </span>
          </div>
        </div>

        <!-- 热门股票列表 (m-section-header + m-rank-list/m-rank-item) -->
        <div class="m-section-header">热门股票<span class="meta" @click="$router.push('/dragon')">更多 ›</span></div>
        <div class="m-rank-list m-rank-scroll">
          <div v-for="(s, i) in hotStocks.slice(0, 15)" :key="s.code || i" class="m-rank-item m-hot-stock-card" @click="$router.push(`/stock?code=${s.code}`)">
            <span class="rank" :class="i === 0 ? 'r1' : i === 1 ? 'r2' : i === 2 ? 'r3' : ''">{{ i + 1 }}</span>
            <div class="body">
              <div class="hs-top-row">
                <div class="name">{{ s.name || s.code }}</div>
                <div class="aside">
                  <div class="price" :class="(s.change_pct || 0) >= 0 ? 'up' : 'down'">{{ Number(s.price || 0).toFixed(2) }}</div>
                  <div class="chg" :class="(s.change_pct || 0) >= 0 ? 'up' : 'down'">{{ s.change_pct >= 0 ? '+' : '' }}{{ Number(s.change_pct || 0).toFixed(1) }}%</div>
                </div>
              </div>
              <div class="hs-bottom-row">
                <span class="hs-code">{{ s.code }}</span>
                <span v-if="s.composite_score != null" class="hs-stat hs-heat"><span class="label">热度</span><strong>{{ Math.round(s.composite_score) }}</strong></span>
                <span v-if="s.reason" class="hs-reason" :title="s.reason">{{ s.reason }}</span>
                <span v-if="s.tag" class="hs-tag">{{ s.tag }}</span>
              </div>
            </div>
          </div>
          <div v-if="!hotStocks.length" class="m-empty">暂无数据</div>
        </div>

        <!-- 涨停揭秘 -->
        <div class="m-section-header">
          涨停揭秘
          <template v-if="limitUpData.total != null">
            <span class="meta">{{ limitUpData.total }}家涨停</span>
            <span v-if="limitUpData.total_sealed_yi" class="meta">{{ formatYi(limitUpData.total_sealed_yi) }}亿封单</span>
          </template>
          <span class="meta" @click="$router.push('/strategy?tab=rank&subTab=limit_up')">更多 ›</span>
        </div>
        <div v-if="limitUpStocks.length" class="m-limitup-list">
          <div v-for="(s, i) in limitUpStocks" :key="s.code || i" class="m-limitup-card" @click="$router.push(`/stock?code=${s.code}`)">
            <div class="m-lu-left">
              <span class="m-lu-rank" :class="i === 0 ? 'r1' : i === 1 ? 'r2' : i === 2 ? 'r3' : ''">{{ i + 1 }}</span>
              <div class="m-lu-info">
                <div class="m-lu-name">{{ s.name }}<small>{{ s.code }}</small></div>
                <div class="m-lu-tags">
                  <span v-if="s.pattern" class="m-tag-sm m-pattern-tag" :class="'pat-' + s.pattern">{{ s.pattern }}</span>
                  <span v-if="s.continuous_limit_num > 1" class="m-tag-sm m-continuous">{{ s.continuous_limit_num }}连板</span>
                  <span v-if="s.reason && s.reason !== '—'" class="m-tag-sm m-reason">{{ truncate(s.reason, 8) }}</span>
                </div>
              </div>
            </div>
            <div class="m-lu-right">
              <div class="m-lu-pct up">{{ formatPct(s.change_pct) }}%</div>
              <div v-if="s.sealed_amount_yi" class="m-lu-seal" :class="sealClass(s.sealed_amount_yi)">{{ formatYi(s.sealed_amount_yi) }}亿</div>
            </div>
          </div>
        </div>
        <div v-else-if="!limitUpPool.loading.value" class="m-card m-empty">暂无涨停数据</div>
        <div v-else class="m-card m-empty">加载中...</div>

        <!-- 板块轮动信号 -->
        <template v-if="signalsData.leading_style || signalsData.flow_leading_style || signalsData.heat_score !== undefined || signalsData.concentration_ratio !== undefined || (signalsData.top_inflow_sectors && signalsData.top_inflow_sectors.length) || (signalsData.accumulation_divergence && signalsData.accumulation_divergence.length) || (signalsData.warning_divergence && signalsData.warning_divergence.length)">
          <div class="m-section-header">板块轮动<span class="meta" @click="$router.push('/sector-analysis')">更多 ›</span></div>
          <div class="m-card">
            <!-- 领涨风格 -->
            <div v-if="signalsData.leading_style" class="m-rotation-row">
              <span class="lbl">领涨风格</span>
              <span class="val accent">{{ signalsData.leading_style }}</span>
            </div>
            <div v-if="signalsData.flow_leading_style" class="m-rotation-row">
              <span class="lbl">资金领涨</span>
              <span class="val accent">{{ signalsData.flow_leading_style }}</span>
            </div>
            <!-- 热度评分 -->
            <div v-if="signalsData.heat_score !== undefined" class="m-rotation-row">
              <span class="lbl">市场热度</span>
              <div class="m-heat-bar">
                <div class="m-heat-fill" :style="{ width: signalsData.heat_score + '%' }"></div>
              </div>
              <span class="val" :class="signalsData.heat_score >= 70 ? 'up' : signalsData.heat_score <= 30 ? 'down' : ''">{{ signalsData.heat_score }}</span>
            </div>
            <!-- 集中度 -->
            <div v-if="signalsData.concentration_ratio !== undefined" class="m-rotation-row">
              <span class="lbl">资金集中度</span>
              <div class="m-heat-bar">
                <div class="m-heat-fill" :style="{ width: signalsData.concentration_ratio + '%' }"></div>
              </div>
              <span class="val">{{ signalsData.concentration_ratio }}%</span>
            </div>
            <!-- 流入板块 -->
            <div v-if="signalsData.top_inflow_sectors && signalsData.top_inflow_sectors.length" class="m-rotation-row m-wrap-row">
              <span class="lbl">资金流入</span>
              <div class="m-inflow-tags">
                <span v-for="(sec, idx) in signalsData.top_inflow_sectors.slice(0, 5)" :key="idx" class="m-tag-sm up">{{ sec.name || sec }}</span>
              </div>
            </div>
            <!-- 逆势吸筹 -->
            <div v-if="signalsData.accumulation_divergence && signalsData.accumulation_divergence.length" class="m-rotation-row m-wrap-row">
              <span class="lbl">💡 逆势吸筹</span>
              <div class="m-inflow-tags">
                <span v-for="(d, idx) in signalsData.accumulation_divergence.slice(0, 5)" :key="'acc-' + idx" class="m-tag-sm up">{{ d.name }} +{{ d.flow_net?.toFixed(1) }}亿</span>
              </div>
            </div>
            <!-- 量价背离 -->
            <div v-if="signalsData.warning_divergence && signalsData.warning_divergence.length" class="m-rotation-row m-wrap-row">
              <span class="lbl">⚠️ 量价背离</span>
              <div class="m-warn-tags">
                <span v-for="(d, idx) in signalsData.warning_divergence.slice(0, 5)" :key="'warn-' + idx" class="m-tag-sm warn">{{ d.name }} {{ d.flow_net?.toFixed(1) }}亿</span>
              </div>
            </div>
          </div>
        </template>

        <!-- 综合建议 -->
        <template v-if="signalsData.advice">
          <div class="m-section-header">综合建议</div>
          <div class="m-card m-advice-card">
            <div class="m-advice-icon">💡</div>
            <div class="m-advice-text">{{ signalsData.advice }}</div>
          </div>
        </template>

      </div>
    </template>

    <!-- 桌面端内容 -->
    <template v-else>
      <!-- 部分失败提示条 -->
      <el-alert
        v-if="errorCount > 0 && hasAnyData"
        :title="`部分数据加载失败（${errorCount}/${totalModules}），已显示缓存`"
        type="warning"
        :closable="false"
        show-icon
        class="fetch-error-alert"
      >
        <template #default>
          <div class="alert-content">
            <span class="alert-msg">{{ firstErrorMsg }}</span>
            <el-button size="small" type="warning" :icon="Refresh" @click="refreshFailed" :loading="anyLoading">重试失败项</el-button>
          </div>
        </template>
      </el-alert>

      <!-- 1. 大盘指数卡片 (含迷你K线) -->
      <IndexCards :indices="indices" :loading="indicesKline.loading.value" />

      <!-- 2. 市场概览 (8 项核心指标) -->
      <OverviewPanel
        :sentiment="sentiment"
        :northbound="northboundData"
        :limit-up-data="limitUpData"
        :sector-list="sectorList"
        :loading="overviewLoading"
      />

      <!-- 3. 板块排行 + 热点题材 -->
      <section class="card-section">
        <div class="section-head">
          <h3 class="section-title">板块与热点</h3>
          <span class="section-meta">{{ dataDateStr }} 板块涨跌 + 题材归因</span>
        </div>
        <div class="sector-grid">
          <SectorTable
            title="板块涨幅"
            :items="sectorList"
            :loading="sectors.loading.value"
            :columns="['板块', '涨跌幅', '净额(亿)', '成交额(亿)']"
            :show-flow="true"
          >
            <template #header-actions>
              <el-radio-group v-model="sectorType" size="small">
                <el-radio-button value="industry">行业</el-radio-button>
                <el-radio-button value="concept">概念</el-radio-button>
              </el-radio-group>
            </template>
          </SectorTable>

          <SectorTable
            title="热点题材"
            :items="hotList"
            :loading="hot.loading.value"
            :columns="['题材', '涨跌幅', '净额(亿)', '成交额(亿)']"
            :show-flow="true"
          />
        </div>
      </section>

      <!-- 4. 涨停揭秘 + 热门榜 (双列卡片) -->
      <section class="card-section">
        <div class="dupont-grid">
          <div class="card-wrap">
            <LimitUpPool :data="limitUpData" :loading="limitUpPool.loading.value" />
          </div>
          <div class="card-wrap">
            <HotRank :data="thsHotData" :loading="dashboardCombined.loading.value" />
          </div>
        </div>
      </section>

      <!-- 5. 板块轮动信号 -->
      <RotationSignals :signals="signalsData" :loading="signals.loading.value" />
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, onActivated, watch } from 'vue'
import { Refresh, WarningFilled, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { marketApi } from '@/api'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import { writeCache } from '@/composables/useIndexedDB'
import IndexCards from './components/IndexCards.vue'
import OverviewPanel from './components/OverviewPanel.vue'
import SectorTable from './components/SectorTable.vue'
import RotationSignals from './components/RotationSignals.vue'
import LimitUpPool from './components/LimitUpPool.vue'
import HotRank from './components/HotRank.vue'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'

defineOptions({ name: 'MarketDashboard' })

const isMobile = ref(window.innerWidth < 768)
function checkMobile() { isMobile.value = window.innerWidth < 768 }
onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})
onBeforeUnmount(() => window.removeEventListener('resize', checkMobile))

// ── Mobile computed data ──────────────────────────────
const breadthData = computed(() => {
  const b = sentimentQuick.data.value?.breadth || {}
  return { up: b.up || 0, down: b.down || 0, flat: b.flat || 0 }
})

const sentimentScoreVal = computed(() => sentimentQuick.data.value?.score ?? 50)

const limitUpCount = computed(() => { const l = sentimentQuick.data.value?.limit_up_down; return l ? (l.limit_up ?? 0) : '-' })
const limitDownCount = computed(() => { const l = sentimentQuick.data.value?.limit_up_down; return l ? (l.limit_down ?? 0) : '-' })

const volumeTotal = computed(() => sentimentQuick.data.value?.volume?.total_billion || null)
const hotStocks = computed(() => {
  const data = dashboardCombined.data.value?.ths_hot_rank
  if (Array.isArray(data?.stocks)) return data.stocks
  if (Array.isArray(data)) return data
  return []
})

const limitUpStocks = computed(() => limitUpData.value?.stocks || [])

const moneyFlowNet = computed(() => {
  const mf = sentimentQuick.data.value?.money_flow
  if (!mf) return 0
  return Number(mf.net_inflow_billion ?? (mf.inflow_billion && mf.outflow_billion ? mf.inflow_billion - mf.outflow_billion : 0)) || 0
})

const northboundHasData = computed(() => {
  const s = northboundData.value?.summary
  if (!s) return false
  return (s.hgt_latest ?? 0) !== 0 || (s.sgt_latest ?? 0) !== 0
})

const northboundHgt = computed(() => Number(northboundData.value?.summary?.hgt_latest ?? 0))
const northboundSgt = computed(() => Number(northboundData.value?.summary?.sgt_latest ?? 0))

const northboundNet = computed(() => {
  const s = northboundData.value?.summary
  if (!s) return 0
  return (Number(s.hgt_latest ?? 0) + Number(s.sgt_latest ?? 0)) || 0
})

function formatPct(v) { return (Number(v) || 0).toFixed(2) }
function formatYi(v) { const n = Number(v) || 0; if (!n) return '—'; return n >= 10 ? n.toFixed(1) : n.toFixed(2) }
function truncate(s, len) { return s && s.length > len ? s.slice(0, len) + '…' : s }
function sealClass(v) { const n = Number(v) || 0; return n >= 5 ? 'seal-strong' : n >= 1 ? 'seal-mid' : '' }
function formatTurnover(v) { const n = Number(v) || 0; if (!n) return '—'; return n >= 10000 ? (n / 10000).toFixed(2) + '万亿' : n.toFixed(0) + '亿' }

const sectorType = ref('industry')

// ═══ 独立缓存（每个后台静默刷新，作为 fallback）══════════════════════════

// 快路径：sentiment 不含资金流拆分（30s 超时，全市场breadth首次需10-15s）
const sentimentQuick = useCachedFetch({
  key: 'market:sentiment:quick',
  fetcher: ({ force } = {}) => marketApi.getSentimentQuick(force ? 1 : null),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
  onSuccess: mapSentiment,
})

// 合并端点：资金流拆分 + THS热门榜，共享底层数据源（45s 超时）
const dashboardCombined = useCachedFetch({
  key: 'market:dashboard_combined',
  fetcher: ({ force } = {}) => marketApi.getDashboardCombined(30, force ? 1 : null),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
})

// 合并为 OverviewPanel 使用的 sentiment 视图对象
const sentiment = computed(() => {
  const q = sentimentQuick.data.value || {}
  return {
    ...q,
    capital_flow_breakdown: dashboardCombined.data.value?.capital_flow_breakdown || {},
  }
})

const sectors = useCachedFetch({
  key: () => `market:sectors:${sectorType.value}:30`,
  fetcher: ({ force } = {}) => marketApi.getSectors(sectorType.value, 30, force ? 1 : null),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
})

const hot = useCachedFetch({
  key: 'market:hot:10',
  fetcher: ({ force } = {}) => marketApi.getHotSectors(10, force ? 1 : null),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
})

const signals = useCachedFetch({
  key: 'market:signals',
  fetcher: ({ force } = {}) => marketApi.getSignals(force ? 1 : null),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
  onSuccess: mapSignals,
})

const northbound = useCachedFetch({
  key: 'market:northbound',
  fetcher: ({ force } = {}) => marketApi.getNorthboundFlow(),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
})

// 指数 + 迷你K线 (新接口)
const indicesKline = useCachedFetch({
  key: 'market:indices:kline',
  fetcher: ({ force } = {}) => marketApi.getIndicesWithKline(
    '000001,399001,399006,000300,000016,000688,000905,399005,000852',
    30
  ),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
})

// 涨停板池
const limitUpPool = useCachedFetch({
  key: 'market:limit_up_pool',
  fetcher: ({ force } = {}) => marketApi.getLimitUpPool(force ? 1 : 0),
  tier: CACHE_TIERS.MARKET,
  noAutoRefresh: true,
})

// THS 热门榜（从 combined 端点获取）
const thsHotData = computed(() => dashboardCombined.data.value?.ths_hot_rank || {})

// ═══ 完整聚合接口（一次性返回所有数据，减少 80% 请求数）═══════════════
const dashboardFull = useCachedFetch({
  key: 'market:dashboard:full:v1',
  fetcher: ({ force } = {}) => marketApi.getDashboardFull(force ? 1 : 0),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
})

// 聚合数据到达后，分发到各个子模块（子模块有数据后就不会再发请求了）
watch(() => dashboardFull.data.value, (fullData) => {
  if (!fullData) return
  const ttl = CACHE_TIERS.MARKET.storageTTL

  if (fullData.sentiment_quick) {
    sentimentQuick.data.value = mapSentiment(fullData.sentiment_quick)
    sentimentQuick.lastUpdate.value = Date.now()
    sentimentQuick.fromCache.value = false
    writeCache('market:sentiment:quick', sentimentQuick.data.value, ttl).catch(() => {})
  }
  if (fullData.sectors_industry) {
    writeCache('market:sectors:industry:30', fullData.sectors_industry, ttl).catch(() => {})
  }
  if (fullData.sectors_concept) {
    writeCache('market:sectors:concept:30', fullData.sectors_concept, ttl).catch(() => {})
  }
  // 根据当前 tab 类型更新板块数据
  const currentSectorKey = sectorType.value === 'industry' ? 'sectors_industry' : 'sectors_concept'
  if (fullData[currentSectorKey]?.sectors) {
    sectors.data.value = fullData[currentSectorKey]
    sectors.lastUpdate.value = Date.now()
    sectors.fromCache.value = false
  }
  if (fullData.hot_sectors) {
    hot.data.value = fullData.hot_sectors
    hot.lastUpdate.value = Date.now()
    hot.fromCache.value = false
    writeCache('market:hot:10', fullData.hot_sectors, ttl).catch(() => {})
  }
  if (fullData.rotation_signals) {
    signals.data.value = mapSignals(fullData.rotation_signals)
    signals.lastUpdate.value = Date.now()
    signals.fromCache.value = false
    writeCache('market:signals', signals.data.value, ttl).catch(() => {})
  }
  if (fullData.indices_kline) {
    indicesKline.data.value = fullData.indices_kline
    indicesKline.lastUpdate.value = Date.now()
    indicesKline.fromCache.value = false
    writeCache('market:indices:kline', fullData.indices_kline, ttl).catch(() => {})
  }
  if (fullData.northbound_flow) {
    northbound.data.value = fullData.northbound_flow
    northbound.lastUpdate.value = Date.now()
    northbound.fromCache.value = false
    writeCache('market:northbound', fullData.northbound_flow, ttl).catch(() => {})
  }
  if (fullData.limit_up_pool) {
    limitUpPool.data.value = fullData.limit_up_pool
    limitUpPool.lastUpdate.value = Date.now()
    limitUpPool.fromCache.value = false
    writeCache('market:limit_up_pool', fullData.limit_up_pool, ttl).catch(() => {})
  }
  if (fullData.dashboard_combined) {
    dashboardCombined.data.value = fullData.dashboard_combined
    dashboardCombined.lastUpdate.value = Date.now()
    dashboardCombined.fromCache.value = false
    writeCache('market:dashboard_combined', fullData.dashboard_combined, ttl).catch(() => {})
  }
}, { deep: false })

// 聚合接口失败 fallback：全部子模块独立请求
watch(() => dashboardFull.error.value, (err) => {
  if (err && !hasAnyData.value) {
    console.warn('[MarketDashboard] 聚合接口失败，降级为子模块独立请求:', err?.message)
    modules.forEach(m => m.silentRefresh())
  }
}, { flush: 'post' })

// 聚合部分字段 None fallback：未命中的字段触发对应子模块独立请求
watch(() => dashboardFull.data.value, (fullData) => {
  if (!fullData) return
  const fieldModuleMap = [
    ['sentiment_quick', sentimentQuick, 'score'],
    ['sectors_industry', sectors, 'sectors'],
    ['sectors_concept', sectors, 'sectors'],
    ['hot_sectors', hot, 'sectors'],
    ['rotation_signals', signals, 'leading_style'],
    ['indices_kline', indicesKline, 'indices'],
    ['northbound_flow', northbound, 'summary'],
    ['limit_up_pool', limitUpPool, 'total_stocks'],
    ['dashboard_combined', dashboardCombined, 'ths_hot_rank'],
  ]
  const checkedModules = new Set()
  for (const [field, module, checkKey] of fieldModuleMap) {
    if (checkedModules.has(module)) continue
    const hasData = module.data.value?.[checkKey] != null || Array.isArray(module.data.value?.sectors) || Array.isArray(module.data.value?.indices) || Array.isArray(module.data.value?.stocks)
    if (!fullData[field] && !hasData) {
      checkedModules.add(module)
      module.silentRefresh()
    }
  }
}, { flush: 'post' })

// keep-alive 切回：无数据的子模块触发独立请求
onActivated(() => {
  modules.forEach(m => {
    if (m.data.value == null) {
      m.silentRefresh()
    }
  })
})

// ═══ 模块聚合（用于错误状态）══════════════════════════════════
const modules = [sentimentQuick, dashboardCombined, sectors, hot, signals, northbound, indicesKline, limitUpPool]
const totalModules = modules.length

// 初始加载守卫：页面挂载后延迟判定，避免部分模块快速失败时误触发 allFailed
const initialLoadDone = ref(false)
onMounted(() => { setTimeout(() => { initialLoadDone.value = true }, 15000) })

// 初始加载超时 fallback：聚合接口较慢时（>10s），启动子模块独立请求
let initialFallbackTimer = null
onMounted(() => {
  initialFallbackTimer = setTimeout(() => {
    if (!hasAnyData.value && !dashboardFull.data.value) {
      console.warn('[MarketDashboard] 聚合接口超时，启动子模块独立加载')
      modules.forEach(m => m.silentRefresh())
    }
  }, 10000)
})

// 聚合数据到达后清除 fallback 定时器
watch(() => dashboardFull.data.value, (fullData) => {
  if (fullData && initialFallbackTimer) {
    clearTimeout(initialFallbackTimer)
    initialFallbackTimer = null
  }
})

onBeforeUnmount(() => {
  if (initialFallbackTimer) {
    clearTimeout(initialFallbackTimer)
    initialFallbackTimer = null
  }
})

const lastUpdate = computed(() => {
  const updates = modules.map(c => c.lastUpdate.value).filter(t => t > 0)
  return updates.length ? Math.max(...updates) : 0
})
const lastUpdateStr = computed(() => {
  if (!lastUpdate.value) return ''
  return new Date(lastUpdate.value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
})

// 从后端响应获取实际数据日期（优先用 sentimentQuick，其次用本地日期）
const dataDateStr = computed(() => {
  const sentimentData = sentimentQuick.data.value
  if (sentimentData?.data_date) return sentimentData.data_date
  // 兜底：用本地日期
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
})

// 统一显示格式：数据日期 X | 更新于 Y
const headerInfoText = computed(() => {
  if (!lastUpdate.value) return ''
  return `数据日期 ${dataDateStr.value} | 更新于 ${lastUpdateStr.value}`
})
const anyLoading = computed(() => modules.some(c => c.loading.value))
const anyRefreshing = computed(() => modules.some(c => c.refreshing.value))
const anyFromCache = computed(() => modules.some(c => c.fromCache.value))

// 市场概览面板的加载状态（包含情绪、北向资金、板块）
const overviewLoading = computed(() =>
  sentimentQuick.loading.value || dashboardCombined.loading.value || northbound.loading.value || sectors.loading.value
)

const errorCount = computed(() => modules.filter(c => c.error.value && !c.loading.value && c.data.value == null).length)
const allFailed = computed(() => initialLoadDone.value && modules.every(c => c.error.value && !c.loading.value && c.data.value == null))
const hasAnyData = computed(() => modules.some(c => c.data.value != null))
const allEmpty = computed(() =>
  initialLoadDone.value && !hasAnyData.value && modules.every(c => !c.loading.value && !c.refreshing.value)
)
const emptyHint = computed(() => {
  const now = new Date()
  const day = now.getDay()
  const hour = now.getHours()
  const isWeekend = day === 0 || day === 6
  const isOffHours = hour < 9 || hour >= 15
  if (isWeekend) return '周末休市，无最新数据'
  if (isOffHours) return '当前为非交易时段'
  return '暂无数据'
})
const firstErrorMsg = computed(() => {
  const failed = modules.find(c => c.error.value && !c.loading.value && c.data.value == null)
  return failed?.error.value?.message || ''
})

async function refreshFailed() {
  const failed = modules.filter(c => c.error.value && c.data.value == null)
  await Promise.all(failed.map(c => c.refresh()))
}

// ═══ 数据转换（API → 视图模型）══════════════════════════════════

// 指数 (优先使用 indicesKline 接口带 K 线数据，回退 sentiment)
const indices = computed(() => {
  const kline = indicesKline.data.value
  if (kline?.indices?.length) {
    return kline.indices.map(idx => ({
      code: idx.code,
      name: idx.name,
      price: idx.price,
      change_pct: idx.change_pct,
      kline: Array.isArray(idx.kline) ? idx.kline : [],
    }))
  }
  // 回退到 sentimentQuick
  const s = sentimentQuick.data.value
  if (!s?.indices) return []
  const result = []
  for (const key of ['shanghai', 'shenzhen', 'chiNext', 'sh50', 'hs300', 'star50', 'csi500', 'small_cap', 'csi1000']) {
    const idx = s.indices[key]
    if (idx) result.push(idx)
  }
  return result
})

// 北向资金
const northboundData = computed(() => northbound.data.value || {})

// 板块（结构化 → fallback 文本解析）
const sectorList = computed(() => {
  const s = sectors.data.value
  if (s?.sectors && Array.isArray(s.sectors)) return s.sectors
  const raw = s?.raw_output || ''
  if (!raw) return []
  const result = []
  for (const line of raw.split('\n')) {
    const m = line.match(/^\s*(\d+)\s+(\S+)\s+[+-]?\s*([-\d.]+)%\s+([-\d.]+)\s+([+-]?\s*[-\d.]+)/)
    if (m) {
      result.push({
        name: m[2],
        change_pct: parseFloat(m[3]),
        turnover: parseFloat(m[4]),
        flow_net: parseFloat(m[5].replace(/\s/g, '')),
      })
    }
  }
  return result
})

const hotList = computed(() => {
  const h = hot.data.value
  if (h?.sectors && Array.isArray(h.sectors)) return h.sectors
  const raw = h?.raw_output || ''
  if (!raw) return []
  const result = []
  for (const line of raw.split('\n')) {
    const m = line.match(/^\s*(\d+)\s+(\S+)\s+[+-]?\s*([-\d.]+)%\s+([-\d.]+)/)
    if (m) {
      result.push({ name: m[2], change_pct: parseFloat(m[3]), turnover: parseFloat(m[4]) })
    }
  }
  return result
})

// 涨停板池数据
const limitUpData = computed(() => limitUpPool.data.value || {})

// THS 热门榜数据（从 combined 端点获取）

// 轮动信号
const signalsData = computed(() => {
  const s = signals.data.value
  if (!s) return {}
  if (s.leading_style || s.heat_score !== undefined) {
    return {
      leading_style: s.leading_style || '',
      style_performance: s.style_performance || {},
      flow_leading_style: s.flow_leading_style || '',
      style_flow: s.style_flow || {},
      heat_score: Number(s.heat_score ?? 50),
      warning_divergence: s.warning_divergence || [],
      accumulation_divergence: s.accumulation_divergence || [],
      concentration_ratio: Number(s.concentration_ratio ?? 50),
      top_inflow_sectors: s.top_inflow_sectors || [],
      advice: s.advice || '',
    }
  }
  const raw = s.raw_output || ''
  if (!raw) return {}
  const getVal = (key) => {
    const m = raw.match(new RegExp(`${key}[:：]\\s*(.+)`))
    return m ? m[1].trim() : ''
  }
  return {
    leading_style: getVal('领涨风格'),
    style_performance: {},
    flow_leading_style: '',
    style_flow: {},
    heat_score: 50,
    warning_divergence: [],
    accumulation_divergence: [],
    concentration_ratio: 50,
    top_inflow_sectors: [],
    advice: getVal('操作建议'),
  }
})

// ═══ 交互 ═══════════════════════════════════════════════════════

async function loadSectors() {
  await sectors.refresh()
}

async function refreshAll() {
  // 优先使用聚合接口刷新（1个请求替代8个），失败再 fallback 到分别刷新
  try {
    await dashboardFull.refresh()
    if (dashboardFull.error.value) {
      throw dashboardFull.error.value
    }
    ElMessage.success('已刷新')
    return
  } catch (e) {
    console.warn('聚合刷新失败，降级为分别刷新:', e?.message)
    ElMessage.warning('聚合接口响应较慢，正在逐项加载...')
  }
  // fallback：分别刷新各个模块
  const results = await Promise.allSettled(modules.map(c => c.refresh()))
  const failed = results.filter(r => r.status === 'rejected').length
  if (failed > 0) {
    if (failed === results.length) {
      ElMessage.error('全部数据加载失败，请检查网络后重试')
    } else {
      ElMessage.warning(`刷新完成，${failed}项失败，可稍后手动重试`)
    }
  } else {
    ElMessage.success('已刷新')
  }
}

// ═══ 转换函数（缓存回调）════════════════════════════════════════

function mapSentiment(raw) {
  if (!raw) return raw
  const idxMap = {
    '000001': 'shanghai', '399001': 'shenzhen', '399006': 'chiNext',
    '000016': 'sh50', '000300': 'hs300', '399005': 'small_cap',
    '000688': 'star50', '000905': 'csi500', '000852': 'csi1000',
  }
  const indices = {}
  if (raw.indices) {
    for (const [code, key] of Object.entries(idxMap)) {
      if (raw.indices[code]) indices[key] = raw.indices[code]
    }
  }
  const mf = raw.money_flow || {}
  const net = mf.net_inflow_billion ?? 0
  let money_flow
  if (mf.inflow_billion != null && mf.outflow_billion != null) {
    money_flow = { ...mf }
  } else {
    money_flow = {
      ...mf,
      inflow_billion: Math.max(0, net),
      outflow_billion: Math.abs(Math.min(0, net)),
      source: mf.source || 'estimate',
    }
  }
  return { ...raw, indices, money_flow }
}

function mapSignals(raw) {
  if (!raw) return raw
  return {
    ...raw,
    leading_style: raw.leading_style || '',
    style_performance: raw.style_performance || {},
    flow_leading_style: raw.flow_leading_style || '',
    style_flow: raw.style_flow || {},
    heat_score: Number(raw.heat_score ?? 50),
    warning_divergence: raw.warning_divergence || [],
    accumulation_divergence: raw.accumulation_divergence || [],
    concentration_ratio: Number(raw.concentration_ratio ?? 50),
    top_inflow_sectors: raw.top_inflow_sectors || [],
    advice: raw.advice || '',
  }
}
</script>

<style scoped>
.market-dashboard {
  position: relative;
  padding: 16px 16px 32px;
  max-width: 100%;
  width: 100%;
  overflow-x: hidden;
  background: #f5f6f8;
}

/* ── Header ─────────────────────────────────────── */
.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding: 14px 18px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2329;
  margin: 0;
  letter-spacing: 0.3px;
}

.header-divider {
  color: #dcdfe6;
  font-weight: 300;
  margin: 0 2px;
}

.update-time {
  font-size: 13px;
  color: #4e5969;
  font-variant-numeric: tabular-nums;
}
.update-time.placeholder { color: #c0c4cc; }

.ml-1 { margin-left: 4px; }

/* ── 错误状态 ───────────────────────────────────── */
.fetch-error-empty { padding: 80px 0; }
.fetch-error-icon { font-size: 64px; color: #f56c6c; }
.fetch-error-text {
  color: #909399;
  font-size: 13px;
  margin-bottom: 16px;
}
.fetch-error-alert { margin-bottom: 12px; }
.fetch-error-alert .alert-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
}
.fetch-error-alert .alert-msg {
  color: #606266;
  font-size: 13px;
  flex: 1;
}

/* ── 段落标题 ───────────────────────────────────── */
.card-section {
  margin-bottom: 14px;
  background: transparent;
}

.section-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
  padding: 0 4px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #1d2129;
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.section-title::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 14px;
  background: #165dff;
  border-radius: 1px;
}

.section-meta {
  font-size: 12px;
  color: #86909c;
  font-weight: 400;
}

/* ── 板块双列 ───────────────────────────────────── */
.sector-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  min-width: 0;
}

/* ── 双列卡片 ─────────────────────────── */
.dupont-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  min-width: 0;
}
.card-wrap {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  padding: 12px 14px 14px;
}
.card-wrap > .card-section { margin-bottom: 0; }

/* ── 响应式 ───────────────────────────────────── */
@media (max-width: 1200px) {
  .sector-grid, .dupont-grid { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .market-dashboard { padding: 0; background: var(--m-bg, #f5f7fa); overflow-x: hidden; height: auto !important; min-height: 100%; }
  .market-dashboard .dashboard-header { display: none; }
  .market-dashboard .fetch-error-alert { display: none; }
  .market-dashboard .fetch-error-empty { padding: 40px 16px 70px; }

  /* ── 移动端页面容器：底部空白由 App.vue .app-main 统一控制 ── */
  .mobile-page {
    padding: 0 12px;
  }

  /* ── IndexCards 子组件在移动端的覆盖样式 ── */
  .mobile-page :deep(.index-grid) {
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    margin-bottom: 12px;
  }

  /* ── Desktop content hidden on mobile ── */
  .market-dashboard .sector-grid,
  .market-dashboard .dupont-grid,
  .market-dashboard > .card-section:not(.mobile-page *) { display: none; }
}
</style>
