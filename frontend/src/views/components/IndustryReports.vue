<template>
  <div class="industry-reports">
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

    <template v-else-if="hasData && !error">
      <div class="reports-scroll-area">
        <!-- 刷新时显示骨架屏覆盖层（后台静默刷新或手动刷新） -->
        <div v-if="refreshing || loading" class="skeleton-overlay">
          <el-skeleton :rows="6" animated />
        </div>
        <!-- Rating Summary -->
        <div class="rating-summary">
          <h4>评级统计 (近90天)</h4>
          <div class="rating-bars">
            <div v-for="(count, rating) in ratingSummary" :key="rating" class="rating-bar-item">
              <span class="rating-label">{{ rating }}</span>
              <el-progress
                :percentage="ratingPercentage(count)"
                :color="ratingColor(rating)"
                :stroke-width="16"
                :show-text="false"
                class="rating-progress"
              />
              <span class="rating-count">{{ count }}篇</span>
            </div>
          </div>
        </div>

        <!-- Reports by Industry -->
        <div class="section-title">行业研报分布 ({{ data.total_count }}篇)</div>
        <!-- 桌面端表格 -->
        <div v-if="!isMobile" class="table-wrapper">
          <el-table :data="industryData" stripe style="width: 100%" max-height="400">
            <el-table-column type="index" label="排名" width="60" />
            <el-table-column prop="industry" label="行业名称" width="130" />
            <el-table-column prop="count" label="研报数" width="80" sortable>
              <template #default="{ row }">
                <el-tag type="primary" effect="plain">{{ row.count }}篇</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最新研报" min-width="400">
              <template #default="{ row }">
                <div class="report-list">
                  <div v-for="(r, idx) in row.reports" :key="idx" class="report-item">
                    <span class="report-date">{{ r.publish_date }}</span>
                    <a v-if="r.url" :href="r.url" target="_blank" rel="noopener noreferrer" class="report-title report-link" :title="r.title">
                      {{ r.title }}
                    </a>
                    <span v-else class="report-title" :title="r.title">{{ r.title }}</span>
                    <el-tag v-if="r.rating" size="small" :type="ratingTagType(r.rating)">
                      {{ r.rating }}
                    </el-tag>
                  </div>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <!-- 移动端卡片 -->
        <div v-else class="mobile-card-list">
          <div v-for="(row, idx) in industryData" :key="'ind-'+idx" class="m-sector-card">
            <div class="m-card-top">
              <div class="m-rank">{{ idx + 1 }}</div>
              <div class="m-card-name">{{ row.industry }}</div>
              <el-tag type="primary" effect="plain" size="small">{{ row.count }}篇</el-tag>
            </div>
            <div class="m-report-list">
              <div v-for="(r, ri) in row.reports.slice(0, 3)" :key="ri" class="m-report-item">
                <span class="report-date">{{ r.publish_date }}</span>
                <a v-if="r.url" :href="r.url" target="_blank" rel="noopener noreferrer" class="report-title report-link">{{ r.title }}</a>
                <span v-else class="report-title">{{ r.title }}</span>
                <el-tag v-if="r.rating" size="small" :type="ratingTagType(r.rating)">{{ r.rating }}</el-tag>
              </div>
            </div>
          </div>
        </div>

        <!-- Latest Reports -->
        <div class="section-title">最新研报</div>
        <el-timeline>
          <el-timeline-item
            v-for="(report, idx) in latestReports"
            :key="idx"
            :timestamp="report.publish_date"
            placement="top"
          >
            <el-card shadow="hover" class="report-card">
              <div class="report-header">
                <span class="report-industry">{{ report.industry }}</span>
                <el-tag v-if="report.rating" size="small" :type="ratingTagType(report.rating)">
                  {{ report.rating }}
                </el-tag>
              </div>
              <a v-if="report.url" :href="report.url" target="_blank" rel="noopener noreferrer" class="report-title-full report-link" :title="report.title">
                {{ report.title }}
              </a>
              <div v-else class="report-title-full" :title="report.title">{{ report.title }}</div>
              <div class="report-org">{{ report.org }}</div>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </div>
    </template>

    <transition name="empty-fade" v-else>
      <el-empty description="暂无研报数据" />
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
  key: 'sector:industry-reports',
  fetcher: () => sectorAnalysisApi.getIndustryReports(80),  // 优化：80条足够展示，减少后端拉取压力
  tier: CACHE_TIERS.REPORT,
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
  const reports = data.value.reports_by_industry || []
  const latest = data.value.latest_reports || []
  return reports.length > 0 || latest.length > 0
})

let reportsLoadedEmitted = false
watch(hasData, (val) => {
  if (val && !reportsLoadedEmitted) {
    reportsLoadedEmitted = true
    emit('loaded')
  }
})

const industryData = computed(() => data.value?.reports_by_industry || [])
const latestReports = computed(() => data.value?.latest_reports || [])
const ratingSummary = computed(() => data.value?.rating_summary || {})

function totalRatings() {
  return Object.values(ratingSummary.value).reduce((a, b) => a + b, 0)
}

function ratingPercentage(count) {
  const total = totalRatings()
  return total > 0 ? Math.round(count / total * 100) : 0
}

function ratingColor(rating) {
  const colors = { '买入': '#f56c6c', '增持': '#e6a23c', '中性': '#909399', '减持': '#67c23a' }
  return colors[rating] || '#409eff'
}

function ratingTagType(rating) {
  const types = { '买入': 'danger', '增持': 'warning', '中性': 'info', '减持': 'success' }
  return types[rating] || ''
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
.industry-reports {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.reports-scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  position: relative;
}

.loading-container {
  max-width: 600px;
  margin: 40px auto;
}

.rating-summary {
  padding: 10px 14px;
  background: #f8fafc;
  border-radius: 6px;
  margin-bottom: 10px;
}

.rating-summary h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #333;
}

.rating-bars {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.rating-bar-item {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 130px;
}

.rating-label {
  font-size: 12px;
  color: #666;
  width: 36px;
}

.rating-progress {
  flex: 1;
}

.rating-count {
  font-size: 11px;
  color: #999;
  min-width: 32px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin: 8px 0 6px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}

.report-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.report-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.report-date {
  color: #999;
  white-space: nowrap;
}

.report-title {
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.report-link {
  color: #409eff;
  text-decoration: none;
  cursor: pointer;
  transition: color 0.2s;
}

.report-link:hover {
  color: #66b1ff;
  text-decoration: underline;
}

.report-card {
  margin-bottom: 8px;
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.report-industry {
  font-size: 13px;
  color: #409eff;
  font-weight: 500;
}

.report-title-full {
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
  line-height: 1.5;
}

.report-org {
  font-size: 12px;
  color: #999;
}

.table-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

/* ========== H5 移动端适配 ========== */
@media (max-width: 768px) {
  /* 移动端：滚动区域底部避开导航栏 */
  .reports-scroll-area {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  .rating-summary {
    padding: 6px 10px;
    margin-bottom: 8px;
  }

  .rating-summary h4 {
    font-size: 12px;
    margin-bottom: 6px;
  }

  .rating-bars {
    gap: 4px;
    display: grid;
    grid-template-columns: repeat(2, 1fr);
  }

  .rating-bar-item {
    min-width: unset;
    width: 100%;
  }

  .section-title {
    font-size: 12px;
    margin: 6px 0 4px;
  }

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
    min-width: 500px !important;
  }

  :deep(.el-table th),
  :deep(.el-table td) {
    padding: 6px 4px !important;
    word-break: keep-all !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
  }

  :deep(.el-table .cell) {
    font-size: 11px !important;
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

  .report-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }

  .report-title {
    max-width: unset;
    white-space: normal;
    font-size: 11px;
  }

  .report-date { font-size: 10px; }

  :deep(.el-tag) {
    transform: scale(0.85);
    display: inline-block;
  }

  /* Timeline mobile */
  :deep(.el-timeline-item__timestamp) {
    font-size: 10px !important;
  }

  .report-card {
    margin-bottom: 4px;
  }

  :deep(.el-card__body) {
    padding: 8px !important;
  }

  .report-header {
    margin-bottom: 4px;
  }

  .report-industry { font-size: 11px; }

  .report-title-full {
    font-size: 12px;
    margin-bottom: 2px;
  }

  .report-org { font-size: 10px; }
}

@media (max-width: 480px) {
  .rating-label {
    width: 30px;
    font-size: 10px;
  }

  .rating-count {
    font-size: 10px;
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

  .m-report-list { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--m-border, #e0e4ea); }
  .m-report-item { display: flex; align-items: center; gap: 6px; font-size: 11px; flex-wrap: wrap; }
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
