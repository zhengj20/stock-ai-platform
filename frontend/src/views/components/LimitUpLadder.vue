<template>
  <div class="limit-up-ladder">
    <!-- Loading State -->
    <div v-if="loading || !hasData" class="loading-container">
      <el-skeleton :rows="8" animated />
    </div>

    <!-- Error State -->
    <el-alert v-else-if="error" :title="error" type="error" show-icon :closable="false" class="mb-4">
      <template #default>
        <div class="error-message">{{ error }}</div>
      </template>
    </el-alert>
    <div v-if="error" class="retry-container">
      <el-button type="primary" size="small" :icon="Refresh" @click="fetchData">重新加载</el-button>
    </div>

    <!-- Data Display -->
    <div v-else-if="hasData && !error" class="ladder-scroll-area">
      <!-- 刷新时显示骨架屏覆盖层（后台静默刷新或手动刷新） -->
      <div v-if="refreshing || loading" class="skeleton-overlay">
        <el-skeleton :rows="6" animated />
      </div>
      <!-- Speculation Signal Banner -->
      <div v-if="data.speculation_signal" class="signal-banner" :class="emotionClass(data.speculation_signal.emotion_score)">
        <div class="signal-header">
          <span class="signal-icon">{{ emotionIcon(data.speculation_signal.emotion_score) }}</span>
          <span class="signal-title">市场情绪指数: {{ data.speculation_signal.emotion_score }}/100</span>
        </div>
        <div class="signal-content">{{ data.speculation_signal.signal }}</div>
        <div class="signal-advice"><strong>操作建议:</strong> {{ data.speculation_signal.advice }}</div>
      </div>

      <!-- Overview Stats -->
      <div class="stats-row">
        <el-statistic title="日期" :value="data.date" />
        <el-statistic title="涨停数" :value="data.zt_count">
          <template #suffix>只</template>
        </el-statistic>
        <el-statistic title="炸板数" :value="data.zb_count">
          <template #suffix>只</template>
        </el-statistic>
        <el-statistic title="跌停数" :value="data.dt_count">
          <template #suffix>只</template>
        </el-statistic>
        <el-statistic title="炸板率" :value="data.break_rate">
          <template #suffix>%</template>
        </el-statistic>
        <el-statistic title="最高连板" :value="data.max_height">
          <template #suffix>板</template>
        </el-statistic>
        <el-statistic title="晋级率" :value="data.promotion_rate">
          <template #suffix>%</template>
        </el-statistic>
      </div>

      <!-- Ladder Distribution -->
      <div class="section-title">连板梯队分布</div>
      <div class="ladder-grid">
        <div v-for="(count, days) in sortedLadder" :key="days" class="ladder-item"
          :class="{ 'highlight': parseInt(days) >= 3 }">
          <div class="board-count">{{ days }}板</div>
          <div class="stock-count">{{ count }}</div>
        </div>
      </div>

      <!-- Sector ZT Stats -->
      <div class="section-title">板块涨停分布（综合评分排序）</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="sectorZtData" stripe style="width: 100%" max-height="400">
          <el-table-column prop="name" label="板块" width="120" />
          <el-table-column prop="composite_score" label="综合评分" width="90" sortable>
            <template #default="{ row }">
              <span class="score-tag" :class="scoreClass(row.composite_score)">
                {{ row.composite_score?.toFixed?.(1) || '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="zt_count" label="涨停数" width="80" sortable />
          <el-table-column prop="max_limit_days" label="最高连板" width="90" sortable />
          <el-table-column prop="total_seal_fund_yi" label="封单(亿)" width="100" sortable>
            <template #default="{ row }">
              {{ row.total_seal_fund_yi != null ? Number(row.total_seal_fund_yi).toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="评分构成" width="240">
            <template #default="{ row }">
              <div class="score-detail" v-if="row.score_detail">
                <span title="涨停数量分">数:{{ row.score_detail.zt_count_score?.toFixed?.(0) }}</span>
                <span title="连板高度分">高:{{ row.score_detail.height_score?.toFixed?.(0) }}</span>
                <span title="梯队完整分">梯:{{ row.score_detail.ladder_score?.toFixed?.(0) }}</span>
                <span title="封单强度分">封:{{ row.score_detail.seal_score?.toFixed?.(0) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="代表股票">
            <template #default="{ row }">
              <div class="stock-list">
                <span v-for="s in row.stocks" :key="s.code" class="stock-tag">
                  {{ s.name }}({{ s.limit_days }}板)
                </span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in sectorZtData" :key="'sector-'+idx" class="m-sector-card">
          <div class="m-card-top">
            <div class="m-card-name">{{ row.name }}</div>
            <span class="score-tag" :class="scoreClass(row.composite_score)">{{ row.composite_score?.toFixed?.(1) || '-' }}</span>
          </div>
          <div class="m-card-stats">
            <span class="m-stat"><b>{{ row.zt_count }}</b>涨停</span>
            <span class="m-stat"><b>{{ row.max_limit_days }}</b>最高连板</span>
            <span class="m-stat">封单<b>{{ row.total_seal_fund_yi != null ? Number(row.total_seal_fund_yi).toFixed(2) : '-' }}</b>亿</span>
          </div>
          <div class="m-card-stocks" v-if="row.stocks && row.stocks.length">
            <span v-for="s in row.stocks.slice(0, 5)" :key="s.code" class="stock-tag">{{ s.name }}({{ s.limit_days }}板)</span>
          </div>
        </div>
      </div>

      <!-- ZT Stocks Table -->
      <div class="section-title">涨停股票详情</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="ztStocks" stripe style="width: 100%" max-height="400">
          <el-table-column prop="code" label="代码" width="80" />
          <el-table-column prop="name" label="名称" width="90" />
          <el-table-column prop="price" label="价格" width="70" />
          <el-table-column prop="pct" label="涨幅%" width="75" sortable />
          <el-table-column prop="limit_days" label="连板数" width="80" sortable />
          <el-table-column prop="zt_stat" label="涨停统计" width="100" />
          <el-table-column prop="first_seal" label="首次封板" width="90" />
          <el-table-column prop="seal_fund_yi" label="封单(亿)" width="95" sortable>
            <template #default="{ row }">
              {{ row.seal_fund_yi != null ? Number(row.seal_fund_yi).toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="break_times" label="炸板次数" width="90" />
          <el-table-column prop="industry" label="行业" width="110" />
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in ztStocks" :key="'zt-'+row.code+idx" class="m-stock-card">
          <div class="m-card-top">
            <div class="m-card-info">
              <span class="m-card-name">{{ row.name }}</span>
              <span class="m-card-code">{{ row.code }}</span>
            </div>
            <div class="m-price-col">
              <div class="m-price up">¥{{ row.price || '--' }}</div>
              <div class="m-chg up">{{ row.pct >= 0 ? '+' : '' }}{{ Number(row.pct).toFixed(2) }}%</div>
            </div>
          </div>
          <div class="m-card-stats">
            <span class="m-stat" :class="row.limit_days > 1 ? 'highlight' : ''">{{ row.limit_days > 1 ? row.limit_days + '连板' : '首板' }}</span>
            <span class="m-stat">封单{{ row.seal_fund_yi != null ? Number(row.seal_fund_yi).toFixed(2) : '-' }}亿</span>
            <span class="m-stat" v-if="row.break_times">炸板{{ row.break_times }}</span>
            <span class="m-stat" v-if="row.industry">{{ row.industry }}</span>
          </div>
        </div>
      </div>

      <!-- Broken ZT Stocks -->
      <div class="section-title">炸板股票</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="zbStocks" stripe style="width: 100%" max-height="300">
          <el-table-column prop="code" label="代码" width="80" />
          <el-table-column prop="name" label="名称" width="90" />
          <el-table-column prop="price" label="现价" width="70" />
          <el-table-column prop="limit_price" label="涨停价" width="75" />
          <el-table-column prop="pct" label="涨幅%" width="75" />
          <el-table-column prop="amplitude" label="振幅%" width="75" />
          <el-table-column prop="break_times" label="炸板次数" width="90" />
          <el-table-column prop="industry" label="行业" width="110" />
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in zbStocks" :key="'zb-'+row.code+idx" class="m-stock-card">
          <div class="m-card-top">
            <div class="m-card-info">
              <span class="m-card-name">{{ row.name }}</span>
              <span class="m-card-code">{{ row.code }}</span>
            </div>
            <div class="m-price-col">
              <div class="m-price">¥{{ row.price || '--' }}</div>
              <div class="m-chg" :class="(row.pct || 0) >= 0 ? 'up' : 'down'">{{ row.pct >= 0 ? '+' : '' }}{{ Number(row.pct).toFixed(2) }}%</div>
            </div>
          </div>
          <div class="m-card-stats">
            <span class="m-stat">涨停价¥{{ row.limit_price || '-' }}</span>
            <span class="m-stat">振幅{{ Number(row.amplitude).toFixed(2) }}%</span>
            <span class="m-stat warn">炸板{{ row.break_times }}次</span>
            <span class="m-stat" v-if="row.industry">{{ row.industry }}</span>
          </div>
        </div>
      </div>

      <!-- DT Stocks -->
      <div class="section-title">跌停股票</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="dtStocks" stripe style="width: 100%" max-height="300">
          <el-table-column prop="code" label="代码" width="80" />
          <el-table-column prop="name" label="名称" width="90" />
          <el-table-column prop="price" label="现价" width="70" />
          <el-table-column prop="pct" label="跌幅%" width="75" />
          <el-table-column prop="seal_fund_yi" label="封单(亿)" width="95">
            <template #default="{ row }">
              {{ row.seal_fund_yi != null ? Number(row.seal_fund_yi).toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="dt_days" label="连续跌停" width="90" />
          <el-table-column prop="industry" label="行业" width="110" />
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in dtStocks" :key="'dt-'+row.code+idx" class="m-stock-card">
          <div class="m-card-top">
            <div class="m-card-info">
              <span class="m-card-name">{{ row.name }}</span>
              <span class="m-card-code">{{ row.code }}</span>
            </div>
            <div class="m-price-col">
              <div class="m-price down">¥{{ row.price || '--' }}</div>
              <div class="m-chg down">{{ Number(row.pct).toFixed(2) }}%</div>
            </div>
          </div>
          <div class="m-card-stats">
            <span class="m-stat" :class="row.dt_days > 1 ? 'highlight' : ''">{{ row.dt_days > 1 ? row.dt_days + '连跌' : '首跌' }}</span>
            <span class="m-stat">封单{{ row.seal_fund_yi != null ? Number(row.seal_fund_yi).toFixed(2) : '-' }}亿</span>
            <span class="m-stat" v-if="row.industry">{{ row.industry }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <transition name="empty-fade" v-else>
      <el-empty description="暂无数据（非交易日或盘后未更新）" />
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { sectorAnalysisApi } from '@/api/index.js'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

const emit = defineEmits(['loading', 'meta-update', 'loaded'])
const isMobile = ref(window.innerWidth < 768)
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const { data, loading, refreshing, error, refresh: cachedRefresh } = useCachedFetch({
  key: 'sector:limit-ladder',
  fetcher: () => sectorAnalysisApi.getLimitUpLadder(),
  tier: CACHE_TIERS.STOCK,
  tradingAware: true,
  onSuccess: (result) => {
    if (result && !result.error) {
      emit('meta-update', { data_date: result.data_date, update_time: result.update_time })
    }
    return result
  },
})

const hasData = computed(() => {
  if (!data.value) return false
  // Check if any meaningful data exists (not just empty shell from backend)
  const zt = data.value.zt_stocks || []
  const zb = data.value.zb_stocks || []
  const dt = data.value.dt_stocks || []
  const sectors = data.value.sector_zt_stats || []
  return zt.length > 0 || zb.length > 0 || dt.length > 0 || sectors.length > 0
})

// Emit loaded once when data first becomes available
let ladderLoadedEmitted = false
watch(hasData, (val) => {
  if (val && !ladderLoadedEmitted) {
    ladderLoadedEmitted = true
    emit('loaded')
  }
})

const sortedLadder = computed(() => {
  if (!data.value?.ladder) return {}
  const ladder = data.value.ladder
  return Object.fromEntries(
    Object.entries(ladder).sort((a, b) => parseInt(b[0]) - parseInt(a[0]))
  )
})

const sectorZtData = computed(() => data.value?.sector_zt_stats || [])
const ztStocks = computed(() => data.value?.zt_stocks || [])
const zbStocks = computed(() => data.value?.zb_stocks || [])
const dtStocks = computed(() => data.value?.dt_stocks || [])

function emotionClass(score) {
  if (score >= 70) return 'emotion-high'
  if (score >= 45) return 'emotion-mid'
  return 'emotion-low'
}

function emotionIcon(score) {
  if (score >= 80) return '🔥'
  if (score >= 60) return '📈'
  if (score >= 40) return '😐'
  if (score >= 25) return '📉'
  return '❄️'
}

function scoreClass(score) {
  if (!score && score !== 0) return ''
  if (score >= 70) return 'score-high'
  if (score >= 40) return 'score-mid'
  return 'score-low'
}

async function fetchData() {
  emit('loading', true)
  try {
    await cachedRefresh()
  } finally {
    emit('loading', false)
  }
}

defineExpose({ fetchData })
</script>

<style scoped>
.limit-up-ladder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.ladder-scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  position: relative;
}

.signal-banner {
  padding: 10px 14px;
  border-radius: 6px;
  margin-bottom: 10px;
  border-left: 4px solid;
}

.signal-banner.emotion-high {
  background: #fef0f0;
  border-color: #f56c6c;
}

.signal-banner.emotion-mid {
  background: #ecf5ff;
  border-color: #409eff;
}

.signal-banner.emotion-low {
  background: #f4f4f5;
  border-color: #909399;
}

.signal-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.signal-icon { font-size: 16px; }

.signal-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.signal-content {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
  line-height: 1.5;
}

.signal-advice {
  font-size: 12px;
  color: #333;
}

.signal-advice strong {
  color: #e6a23c;
}

.loading-container { max-width: 600px; margin: 40px auto; }

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 6px;
  margin-bottom: 12px;
}

.stats-row :deep(.el-statistic) { text-align: center; }
.stats-row :deep(.el-statistic__head) { font-size: 11px; }
.stats-row :deep(.el-statistic__content) { font-size: 18px; }

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin: 10px 0 6px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}

.ladder-grid { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }

.ladder-item {
  padding: 6px 12px;
  background: #f0f9ff;
  border-radius: 6px;
  text-align: center;
  min-width: 64px;
}

.ladder-item.highlight { background: #fef0f0; border: 1px solid #f56c6c; }
.board-count { font-size: 12px; color: #666; margin-bottom: 2px; }
.stock-count { font-size: 16px; font-weight: 600; color: #333; }

.stock-list { display: flex; flex-wrap: wrap; gap: 4px; }
.stock-tag { padding: 2px 8px; background: #ecf5ff; border-radius: 4px; font-size: 12px; color: #409eff; }

.score-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}
.score-tag.score-high { background: #fef0f0; color: #f56c6c; }
.score-tag.score-mid { background: #fdf6ec; color: #e6a23c; }
.score-tag.score-low { background: #f4f4f5; color: #909399; }

.score-detail {
  display: flex;
  flex-wrap: nowrap;
  gap: 4px;
  font-size: 11px;
  color: #909399;
}
.score-detail span {
  padding: 1px 5px;
  background: #f5f7fa;
  border-radius: 3px;
}

.table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }

/* 表格列对齐修复：强制 header/body 同宽，防止错位 */
.table-wrapper :deep(.el-table__header-wrapper) {
  width: 100% !important;
  overflow-hidden: hidden !important;
}
.table-wrapper :deep(.el-table__body-wrapper) {
  width: 100% !important;
}
.table-wrapper :deep(.el-table__header) {
  table-layout: fixed !important;
  width: 100% !important;
}
.table-wrapper :deep(.el-table__body) {
  table-layout: fixed !important;
  width: 100% !important;
}
.table-wrapper :deep(.el-table__header th.el-table__cell),
.table-wrapper :deep(.el-table__body td.el-table__cell) {
  box-sizing: border-box;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.retry-container {
  text-align: center;
  margin-top: 16px;
}

.mb-4 :deep(.el-alert__content) {
  display: flex;
  align-items: center;
}

.error-message {
  font-size: 13px;
  color: #909399;
}

@media (max-width: 768px) {
  /* 移动端：滚动区域底部避开导航栏 */
  .ladder-scroll-area {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  .signal-banner {
    padding: 6px 10px;
    margin-bottom: 8px;
  }

  .signal-title { font-size: 12px; }
  .signal-content { font-size: 10px; margin-bottom: 2px; }
  .signal-advice { font-size: 10px; }
  .signal-icon { font-size: 14px; }

  .stats-row { grid-template-columns: repeat(4, 1fr); gap: 4px; padding: 6px 8px; margin-bottom: 8px; }
  .stats-row :deep(.el-statistic__head) { font-size: 10px !important; }
  .stats-row :deep(.el-statistic__content) { font-size: 14px !important; }
  .stats-row :deep(.el-statistic__suffix) { font-size: 10px !important; }
  .section-title { font-size: 13px; margin: 8px 0 4px; }
  .ladder-grid { gap: 6px; flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; -webkit-overflow-scrolling: touch; margin-bottom: 6px; }
  .ladder-item { padding: 4px 8px; min-width: 52px; flex-shrink: 0; }
  .board-count { font-size: 10px; }
  .stock-count { font-size: 13px; }
  .table-wrapper { margin: 0 -8px; padding: 0 8px; }
  .table-wrapper::-webkit-scrollbar { display: none; }
  :deep(.el-table) { font-size: 12px !important; }

  :deep(.el-table__header-wrapper),
  :deep(.el-table__body-wrapper) {
    display: block !important;
    width: 100% !important;
    overflow-x: hidden !important;
    -webkit-overflow-scrolling: touch;
  }

  :deep(.el-table) {
    table-layout: fixed !important;
    min-width: 650px !important;
  }

  :deep(.el-table th), :deep(.el-table td) {
    padding: 6px 4px !important;
    word-break: keep-all !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
  }

  :deep(.el-table .cell) { font-size: 11px !important; }
  .stock-tag { font-size: 10px; padding: 1px 5px; }
}

@media (max-width: 480px) {
  /* 统计卡片一行横向滚动显示 */
  .stats-row {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    gap: 6px;
    padding: 6px 8px;
    -webkit-overflow-scrolling: touch;
  }
  .stats-row::-webkit-scrollbar { display: none; }
  .stats-row :deep(.el-statistic) {
    min-width: 60px;
    flex-shrink: 0;
  }
  .stats-row :deep(.el-statistic__head) { font-size: 9px !important; }
  .stats-row :deep(.el-statistic__content) { font-size: 13px !important; }
  .stats-row :deep(.el-statistic__suffix) { font-size: 9px !important; }
  .ladder-item { min-width: 52px; padding: 4px 8px; }

  /* 移动端卡片列表 */
  .mobile-card-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }

  /* 板块卡片 */
  .m-sector-card {
    background: var(--m-surface, #fff);
    border-radius: 12px;
    padding: 10px 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }

  /* 股票卡片 */
  .m-stock-card {
    background: var(--m-surface, #fff);
    border-radius: 12px;
    padding: 10px 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }

  /* 卡片顶部：名称+代码 vs 价格 */
  .m-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .m-card-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .m-card-name { font-size: 14px; font-weight: 600; color: var(--m-text, #1a2332); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .m-card-code { font-size: 11px; color: var(--m-text3, #8e99ab); }

  /* 价格列 */
  .m-price-col { text-align: right; flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
  .m-price { font-size: 15px; font-weight: 700; color: var(--m-text, #1a2332); }
  .m-price.up { color: var(--m-up, #e74c3c); }
  .m-price.down { color: var(--m-down, #2ecc71); }
  .m-chg { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 4px; display: inline-block; }
  .m-chg.up { background: var(--m-up-bg, rgba(231,76,60,0.08)); color: var(--m-up, #e74c3c); }
  .m-chg.down { background: var(--m-down-bg, rgba(46,204,113,0.08)); color: var(--m-down, #2ecc71); }

  /* 卡片统计行 */
  .m-card-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--m-border, #e0e4ea); }
  .m-stat { font-size: 11px; color: var(--m-text2, #5a6577); white-space: nowrap; }
  .m-stat b { font-weight: 600; color: var(--m-text, #1a2332); }
  .m-stat.highlight { color: var(--m-up, #e74c3c); font-weight: 600; }
  .m-stat.warn { color: #e6a23c; font-weight: 600; }

  /* 板块卡片顶部 */
  .m-sector-card .m-card-top { justify-content: space-between; align-items: center; }
  .m-sector-card .m-card-name { font-size: 14px; font-weight: 600; color: var(--m-text, #1a2332); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* 板块代表股票 */
  .m-card-stocks { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
}

/* 刷新时骨架屏覆盖层 */
.skeleton-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.85);
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: skeleton-fade-in 0.3s ease;
}

@keyframes skeleton-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.empty-fade-enter-active,
.empty-fade-leave-active {
  transition: opacity 0.3s ease;
}
.empty-fade-enter-from,
.empty-fade-leave-to {
  opacity: 0;
}
</style>
