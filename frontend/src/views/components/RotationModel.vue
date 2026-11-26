<template>
  <div class="rotation-model">
    <!-- Controls -->
    <div class="controls-row">
      <el-radio-group v-model="sectorType" size="default">
        <el-radio-button value="industry">行业板块</el-radio-button>
        <el-radio-button value="concept">概念板块</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Loading -->
    <div v-if="loading || !hasData" class="loading-container">
      <el-skeleton :rows="10" animated />
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
      <div class="rotation-content-wrap">
        <!-- 刷新时显示骨架屏覆盖层（后台静默刷新或手动刷新） -->
        <div v-if="refreshing || loading" class="skeleton-overlay">
          <el-skeleton :rows="8" animated />
        </div>
      <!-- Rotation Signal Banner -->
      <div class="signal-banner" v-if="data.rotation_signal">
        <el-icon><Bell /></el-icon>
        <span>{{ data.rotation_signal }}</span>
      </div>

      <!-- Lifecycle Summary -->
      <div class="lifecycle-summary">
        <div
          v-for="(count, stage) in lifecycleSummary"
          :key="stage"
          class="lifecycle-item"
          :class="stageClass(stage)"
        >
          <span class="stage-name">{{ stage }}</span>
          <span class="stage-count">{{ count }}</span>
        </div>
      </div>

      <!-- Sector Table -->
              <!-- 桌面端表格 -->
              <div v-if="!isMobile" class="table-wrapper">
                <el-table :data="pagedSectors" stripe style="width: 100%" height="100%" class="fit-table">
                  <el-table-column type="index" label="排名" min-width="50" />
                  <el-table-column prop="name" label="板块名称" min-width="110">
                    <template #default="{ row }">
                      <div class="sector-name">{{ row.name }}</div>
                    </template>
                  </el-table-column>
                  <el-table-column prop="composite_score" label="综合评分" min-width="90" sortable>
                    <template #default="{ row }">
                      <el-tag :type="scoreType(row.composite_score)" effect="plain">
                        {{ row.composite_score }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="change_pct" label="涨跌幅%" min-width="80" sortable>
                    <template #default="{ row }">
                      <span :class="row.change_pct >= 0 ? 'up' : 'down'">
                        {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct.toFixed(2) }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="rps_score" label="RPS强度" min-width="85" sortable>
                    <template #default="{ row }">
                      <span :class="row.rps_score >= 70 ? 'up' : row.rps_score <= 30 ? 'down' : ''">
                        {{ row.rps_score }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="flow_net_yi" label="资金流(亿)" min-width="95" sortable>
                    <template #default="{ row }">
                      <span :class="(row.flow_net_yi || 0) >= 0 ? 'up' : 'down'">
                        {{ (row.flow_net_yi || 0) >= 0 ? '+' : '' }}{{ (row.flow_net_yi || 0).toFixed(2) }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="flow_score" label="资金得分" min-width="85" sortable />
                  <el-table-column prop="breadth_score" label="广度%" min-width="70" sortable />
                  <el-table-column prop="up_count" label="上涨" min-width="60" sortable />
                  <el-table-column prop="down_count" label="下跌" min-width="60" sortable />
                  <el-table-column prop="turnover_yi" label="成交额(亿)" min-width="100" sortable />
                  <el-table-column prop="lifecycle" label="生命周期" min-width="80">
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
                <div v-for="(row, idx) in pagedSectors" :key="'rot-'+idx" class="m-sector-card">
                  <div class="m-card-top">
                    <div class="m-rank">{{ idx + 1 }}</div>
                    <div class="m-card-name">{{ row.name }}</div>
                    <el-tag :type="lifecycleTagType(row.lifecycle)" size="small" round>{{ row.lifecycle }}</el-tag>
                  </div>
                  <div class="m-card-stats">
                    <span class="m-stat score"><b :class="scoreType(row.composite_score) === 'success' ? 'up' : scoreType(row.composite_score) === 'danger' ? 'down' : ''">{{ row.composite_score }}</b>分</span>
                    <span class="m-stat" :class="(row.change_pct || 0) >= 0 ? 'up' : 'down'">{{ row.change_pct >= 0 ? '+' : '' }}{{ Number(row.change_pct).toFixed(2) }}%</span>
                    <span class="m-stat">RPS<b>{{ row.rps_score }}</b></span>
                    <span class="m-stat" :class="(row.flow_net_yi || 0) >= 0 ? 'up' : 'down'">资金{{ (row.flow_net_yi || 0) >= 0 ? '+' : '' }}{{ Number(row.flow_net_yi).toFixed(2) }}亿</span>
                  </div>
                  <div class="m-card-stats">
                    <span class="m-stat">上涨<b>{{ row.up_count }}</b></span>
                    <span class="m-stat">下跌<b>{{ row.down_count }}</b></span>
                    <span class="m-stat">广度{{ row.breadth_score }}%</span>
                    <span class="m-stat" v-if="row.lead_stock">领涨:{{ row.lead_stock }}</span>
                  </div>
                </div>
              </div>

      <div class="pagination-bar" style="flex-shrink:0;display:flex;justify-content:flex-end;padding:6px 8px;border-top:1px solid #ebeef5;background:#fff;">
        <el-pagination v-model:current-page="currentPage" :page-size="PAGE_SIZE" :total="sectors.length" layout="total, prev, pager, next" small background />
      </div>
      </div>
    </template>

    <transition name="empty-fade" v-else>
      <el-empty description="暂无数据" />
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Refresh, Bell } from '@element-plus/icons-vue'
import { sectorAnalysisApi } from '@/api/index.js'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

const emit = defineEmits(['loading', 'meta-update', 'loaded'])
const isMobile = ref(window.innerWidth < 768)
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const sectorType = ref('industry')

const rotationKey = computed(() => `sector:rotation:${sectorType.value}`)

const { data, loading, refreshing, error, refresh: cachedRefresh } = useCachedFetch({
  key: rotationKey,
  fetcher: () => sectorAnalysisApi.getRotationModel(sectorType.value, 30),
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
  const sectors = data.value.sectors || []
  return sectors.length > 0
})

let rotationLoadedEmitted = false
watch(hasData, (val) => {
  if (val && !rotationLoadedEmitted) {
    rotationLoadedEmitted = true
    emit('loaded')
  }
})

const sectors = computed(() => data.value?.sectors || [])
const lifecycleSummary = computed(() => data.value?.lifecycle_summary || {})

const PAGE_SIZE = 20
const currentPage = ref(1)
const pagedSectors = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return sectors.value.slice(start, start + PAGE_SIZE)
})

function scoreType(score) {
  if (score >= 70) return 'success'
  if (score >= 50) return ''
  if (score >= 30) return 'warning'
  return 'danger'
}

function lifecycleTagType(lifecycle) {
  const map = {
    '高潮期': 'danger',
    '发酵期': 'success',
    '启动期': '',
    '拉锯期': '',
    '退潮期': 'warning',
    '冰点期': 'info',
  }
  return map[lifecycle] || ''
}

function stageClass(stage) {
  const map = {
    '高潮期': 'stage-climax',
    '发酵期': 'stage-ferment',
    '启动期': 'stage-start',
    '拉锯期': 'stage-sawtooth',
    '退潮期': 'stage-recede',
    '冰点期': 'stage-freeze',
  }
  return map[stage] || ''
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
.rotation-model {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.rotation-content-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.mobile-card-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.controls-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
}

.loading-container {
  max-width: 600px;
  margin: 40px auto;
}

.signal-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fef0f0;
  border: 1px solid #f5c6c6;
  border-radius: 6px;
  margin-bottom: 10px;
  color: #333;
  font-size: 13px;
  flex-shrink: 0;
}

.signal-banner :deep(.el-icon) {
  color: #e6a23c;
  font-size: 16px;
}

.lifecycle-summary {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.lifecycle-item {
  padding: 4px 10px;
  border-radius: 14px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.stage-climax { background: #fef0f0; color: #f56c6c; }
.stage-ferment { background: #f0f9eb; color: #67c23a; }
.stage-start { background: #ecf5ff; color: #409eff; }
.stage-sawtooth { background: #f0f9eb; color: #67c23a; }
.stage-recede { background: #fdf6ec; color: #e6a23c; }
.stage-freeze { background: #f4f4f5; color: #909399; }

.stage-name { font-weight: 500; }
.stage-count { font-weight: 700; font-size: 13px; }

.sector-name {
  font-weight: 500;
}

.up { color: #f56c6c; font-weight: 600; }
.down { color: #67c23a; font-weight: 600; }

.table-wrapper {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
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
  .mobile-card-list {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  .controls-row {
    flex-direction: row;
    margin-bottom: 8px;
  }

  :deep(.el-radio-button__inner) {
    padding: 6px 10px;
    font-size: 12px;
  }

  .signal-banner {
    padding: 6px 10px;
    font-size: 11px;
    margin-bottom: 8px;
    border-radius: 4px;
  }

  .signal-banner :deep(.el-icon) {
    font-size: 14px;
  }

  .lifecycle-summary {
    gap: 4px;
    margin-bottom: 8px;
  }

  .lifecycle-item {
    padding: 3px 8px;
    font-size: 10px;
    border-radius: 12px;
  }

  .stage-count {
    font-size: 11px;
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
    min-width: 900px !important;
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

  :deep(.el-tag) {
    transform: scale(0.85);
    display: inline-block;
  }

  .pagination-bar {
    padding: 4px 6px !important;
  }
}

@media (max-width: 480px) {
  .controls-row {
    flex-direction: column;
    align-items: stretch;
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
    text-align: center;
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

  .m-card-stats { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 8px; border-top: 1px solid var(--m-border, #e0e4ea); }
  .m-card-stats:first-of-type { margin-top: 0; }
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
