<template>
  <div class="sector-comparison">
    <!-- Search Input -->
    <div class="search-row">
      <el-input
        v-model="inputNames"
        placeholder="输入板块名称，逗号分隔 (如: 半导体,新能源)"
        clearable
        class="search-input"
        @keyup.enter="fetchData"
      >
        <template #append>
          <el-button :icon="Search" @click="fetchData">查询</el-button>
        </template>
      </el-input>
      <el-radio-group v-model="sectorType" size="default">
        <el-radio-button value="industry">行业板块</el-radio-button>
        <el-radio-button value="concept">概念板块</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Loading -->
    <div v-if="loading || !hasData" class="loading-container">
      <el-skeleton :rows="8" animated />
    </div>

    <!-- Error -->
    <el-alert v-else-if="error" :title="error" type="error" show-icon :closable="false" class="mb-4">
      <template #default>
        <div class="error-message">{{ error }}</div>
      </template>
    </el-alert>
    <div v-if="error" class="retry-container">
      <el-button type="primary" size="small" :icon="Refresh" @click="fetchData">重新加载</el-button>
    </div>

    <div v-else-if="hasData && !error" class="comparison-scroll-area">
      <!-- 刷新时显示骨架屏覆盖层（后台静默刷新或手动刷新） -->
      <div v-if="refreshing || loading" class="skeleton-overlay">
        <el-skeleton :rows="6" animated />
      </div>
      <!-- Summary Banner -->
      <div class="summary-banner" v-if="data.summary.count > 0">
        <el-statistic title="对比板块数" :value="data.summary.count" />
        <el-statistic title="平均涨跌幅" :value="data.summary.avg_change">
          <template #suffix>%</template>
        </el-statistic>
        <div class="summary-extreme">
          <span class="strongest">最强: {{ data.summary.strongest }} ({{ data.summary.strongest_change?.toFixed(2) }}%)</span>
          <span class="weakest">最弱: {{ data.summary.weakest }} ({{ data.summary.weakest_change?.toFixed(2) }}%)</span>
        </div>
      </div>

      <!-- Comparison Table -->
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="comparisonData" stripe style="width: 100%" max-height="400" class="fit-table">
          <el-table-column type="index" label="排名" width="60" />
          <el-table-column prop="name" label="板块名称" min-width="120">
            <template #default="{ row }">
              <span class="sector-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅%" min-width="90" sortable>
            <template #default="{ row }">
              <span :class="row.change_pct >= 0 ? 'up' : 'down'">
                {{ row.change_pct?.toFixed(2) || '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="turnover_yi" label="成交额(亿)" min-width="110" sortable />
          <el-table-column prop="up_count" label="上涨家数" min-width="85" sortable />
          <el-table-column prop="down_count" label="下跌家数" min-width="85" sortable />
          <el-table-column prop="breadth_ratio" label="广度比%" min-width="130" sortable>
            <template #default="{ row }">
              <div class="breadth-cell">
                <el-progress
                  :percentage="row.breadth_ratio"
                  :color="row.breadth_ratio >= 60 ? '#67c23a' : row.breadth_ratio >= 40 ? '#e6a23c' : '#f56c6c'"
                  :stroke-width="12"
                  :show-text="false"
                />
                <span class="breadth-text">{{ row.breadth_ratio }}%</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="lifecycle" label="生命周期" min-width="90">
            <template #default="{ row }">
              <el-tag :type="lifecycleTagType(row.lifecycle)" size="small">
                {{ row.lifecycle }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="lead_stock" label="领涨股" min-width="100" />
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in comparisonData" :key="'cmp-'+idx" class="m-sector-card">
          <div class="m-card-top">
            <div class="m-rank">{{ idx + 1 }}</div>
            <div class="m-card-name">{{ row.name }}</div>
            <el-tag :type="lifecycleTagType(row.lifecycle)" size="small" round>{{ row.lifecycle }}</el-tag>
          </div>
          <div class="m-card-stats">
            <span class="m-stat" :class="(row.change_pct || 0) >= 0 ? 'up' : 'down'">{{ (row.change_pct || 0) >= 0 ? '+' : '' }}{{ Number(row.change_pct).toFixed(2) }}%</span>
            <span class="m-stat">成交<b>{{ row.turnover_yi }}</b>亿</span>
            <span class="m-stat">上涨<b>{{ row.up_count }}</b></span>
            <span class="m-stat">下跌<b>{{ row.down_count }}</b></span>
          </div>
          <div class="m-card-stats">
            <el-progress :percentage="row.breadth_ratio" :color="row.breadth_ratio >= 60 ? '#67c23a' : row.breadth_ratio >= 40 ? '#e6a23c' : '#f56c6c'" :stroke-width="8" style="flex:1;min-width:80px" />
            <span class="m-stat">广度{{ row.breadth_ratio }}%</span>
            <span class="m-stat" v-if="row.lead_stock">领涨:{{ row.lead_stock }}</span>
          </div>
        </div>
      </div>

      <!-- Visual Comparison Bar -->
      <div class="visual-comparison">
        <h4>涨跌幅对比</h4>
        <div class="bar-chart">
          <div
            v-for="(item, idx) in sortedData"
            :key="idx"
            class="bar-row"
          >
            <span class="bar-label">{{ item.name }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :class="item.change_pct >= 0 ? 'positive' : 'negative'"
                :style="{ width: barWidth(item.change_pct) + '%' }"
              >
                <span class="bar-value">{{ item.change_pct?.toFixed(2) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <transition name="empty-fade" v-else>
      <el-empty description="请输入板块名称或留空查看默认对比" />
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Search, Refresh } from '@element-plus/icons-vue'
import { sectorAnalysisApi } from '@/api/index.js'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

const emit = defineEmits(['loading', 'meta-update', 'loaded'])
const isMobile = ref(window.innerWidth < 768)
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const inputNames = ref('')
const sectorType = ref('industry')

const comparisonKey = computed(() => `sector:comparison:${inputNames.value.trim() || 'top'}:${sectorType.value}`)

const { data, loading, refreshing, error, refresh: cachedRefresh } = useCachedFetch({
  key: comparisonKey,
  fetcher: () => {
    const names = inputNames.value.trim() || undefined
    return sectorAnalysisApi.getComparison(names, sectorType.value)
  },
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
  const items = data.value.comparison_data || []
  return items.length > 0
})

let comparisonLoadedEmitted = false
watch(hasData, (val) => {
  if (val && !comparisonLoadedEmitted) {
    comparisonLoadedEmitted = true
    emit('loaded')
  }
})

const comparisonData = computed(() => {
  const items = data.value?.comparison_data || []
  return [...items].sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0))
})

const sortedData = computed(() => comparisonData.value)

function barWidth(value) {
  if (!value && value !== 0) return 0
  const normalized = Math.max(0, Math.min(100, (value + 10) * 5))
  return normalized
}

function lifecycleTagType(lifecycle) {
  const map = {
    '高潮期': 'danger',
    '发酵期': 'success',
    '启动期': '',
    '退潮期': 'warning',
    '冰点期': 'info',
  }
  return map[lifecycle] || ''
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
.sector-comparison {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.comparison-scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  position: relative;
}

.search-row {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.search-input {
  width: 400px;
  min-width: 250px;
}

.loading-container {
  max-width: 600px;
  margin: 40px auto;
}

.summary-banner {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
  margin-bottom: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.summary-banner :deep(.el-statistic) {
  text-align: center;
}

.summary-banner :deep(.el-statistic__head) {
  font-size: 11px;
}

.summary-banner :deep(.el-statistic__content) {
  font-size: 18px;
}

.summary-extreme {
  display: flex;
  gap: 16px;
  font-size: 12px;
  margin-left: auto;
}

.strongest { color: #f56c6c; }
.weakest { color: #67c23a; }

.sector-name {
  font-weight: 500;
}

.breadth-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.breadth-text {
  font-size: 12px;
  color: #909399;
  min-width: 35px;
}

.visual-comparison {
  margin-top: 10px;
  padding: 12px 14px;
  background: #f8fafc;
  border-radius: 6px;
}

.visual-comparison h4 {
  margin: 0 0 10px;
  font-size: 14px;
  color: #333;
}

.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-row {
  display: grid;
  grid-template-columns: 100px 1fr;
  align-items: center;
  gap: 12px;
}

.bar-label {
  font-size: 13px;
  color: #666;
  text-align: right;
}

.bar-track {
  height: 24px;
  background: #ebeef5;
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.bar-fill {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  transition: width 0.3s ease;
}

.bar-fill.positive {
  background: linear-gradient(90deg, #fde2e2, #f56c6c);
}

.bar-fill.negative {
  background: linear-gradient(90deg, #e1f3d8, #67c23a);
}

.bar-value {
  font-size: 11px;
  color: #fff;
  font-weight: 600;
}

.up { color: #f56c6c; font-weight: 600; }
.down { color: #67c23a; font-weight: 600; }

.table-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
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

/* ========== H5 移动端适配 ========== */
@media (max-width: 768px) {
  /* 移动端：滚动区域底部避开导航栏 */
  .comparison-scroll-area {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  .search-row {
    flex-direction: column;
    align-items: stretch;
    margin-bottom: 8px;
    gap: 6px;
  }

  .search-input {
    width: 100%;
    min-width: unset;
  }

  :deep(.el-radio-group) {
    width: 100%;
    display: flex !important;
  }

  :deep(.el-radio-button) {
    flex: 1;
  }

  :deep(.el-radio-button__inner) {
    width: 100%;
    padding: 6px 10px;
    font-size: 12px;
    text-align: center;
  }

  .summary-banner {
    flex-direction: row;
    gap: 10px;
    padding: 6px 8px;
    margin-bottom: 8px;
    align-items: center;
    flex-wrap: wrap;
  }

  .summary-extreme {
    margin-left: 0;
    flex-direction: row;
    gap: 8px;
    font-size: 11px;
    flex: 1;
    min-width: 100%;
  }

  .summary-banner :deep(.el-statistic__head) { font-size: 10px !important; }
  .summary-banner :deep(.el-statistic__content) { font-size: 14px !important; }

  /* 表格横向滚动 */
  .table-wrapper {
    margin: 0 -8px;
    padding: 0;
  }

  .table-wrapper::-webkit-scrollbar {
    display: none;
  }

  :deep(.el-table) {
    font-size: 12px !important;
  }

  :deep(.el-table__header-wrapper),
  :deep(.el-table__body-wrapper) {
    display: block !important;
    width: 100% !important;
    overflow-x: hidden !important;
    -webkit-overflow-scrolling: touch;
  }

  :deep(.el-table) {
    table-layout: fixed !important;
    min-width: 700px !important;
  }

  :deep(.el-table th),
  :deep(.el-table td) {
    padding: 6px 4px !important;
    word-break: keep-all !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
  }

  .breadth-cell {
    flex-direction: column;
    align-items: flex-start;
  }

  .visual-comparison {
    margin-top: 8px;
    padding: 8px 10px;
  }

  .visual-comparison h4 {
    font-size: 12px;
    margin-bottom: 6px;
  }

  .bar-row {
    grid-template-columns: 64px 1fr;
    gap: 6px;
  }

  .bar-label {
    font-size: 10px;
  }

  .bar-track {
    height: 18px;
  }

  .bar-value {
    font-size: 10px;
  }

  :deep(.el-tag) {
    transform: scale(0.85);
    display: inline-block;
  }
}

@media (max-width: 480px) {
  .search-input :deep(.el-input__wrapper) {
    padding: 5px 8px;
  }

  .bar-row {
    grid-template-columns: 56px 1fr;
  }

  /* 移动端卡片列表 */
  .mobile-card-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }

  .m-sector-card {
    background: var(--m-surface, #fff);
    border-radius: 12px;
    padding: 10px 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }

  .m-card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .m-rank { width: 22px; height: 22px; border-radius: 6px; background: var(--m-surface2, #f0f2f5); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: var(--m-text3, #8e99ab); flex-shrink: 0; }
  .m-card-name { flex: 1; font-size: 14px; font-weight: 600; color: var(--m-text, #1a2332); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .m-card-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--m-border, #e0e4ea); align-items: center; }
  .m-stat { font-size: 11px; color: var(--m-text2, #5a6577); white-space: nowrap; }
  .m-stat b { font-weight: 600; color: var(--m-text, #1a2332); }
  .m-stat.up { color: var(--m-up, #e74c3c) !important; }
  .m-stat.down { color: var(--m-down, #2ecc71) !important; }
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
