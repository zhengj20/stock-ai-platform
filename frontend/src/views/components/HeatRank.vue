<template>
  <div class="heat-rank">
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
      <div class="heat-scroll-area">
        <!-- 刷新时显示骨架屏覆盖层（后台静默刷新或手动刷新） -->
        <div v-if="refreshing || loading" class="skeleton-overlay">
          <el-skeleton :rows="6" animated />
        </div>
      <!-- Concept Heat Rank -->
      <div class="section-title">概念热度排行（关联板块实际表现）</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="conceptRank" stripe style="width: 100%" max-height="450" table-layout="auto">
          <el-table-column type="index" label="排名" min-width="50" />
          <el-table-column prop="concept" label="概念名称" min-width="100">
            <template #default="{ row }">
              <span class="concept-name">{{ row.concept }}</span>
              <el-tag v-if="row.heat_type" :type="heatTypeTag(row.heat_type)" size="small" effect="plain" class="ml-4">
                {{ row.heat_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="hit_count" label="命中数" min-width="60" sortable />
          <el-table-column prop="total_heat" label="总人气值" min-width="70" sortable />
          <el-table-column label="板块涨跌幅%" min-width="90" sortable>
            <template #default="{ row }">
              <span v-if="row.sector_change_pct !== null && row.sector_change_pct !== undefined"
                :class="row.sector_change_pct >= 0 ? 'up' : 'down'">
                {{ row.sector_change_pct >= 0 ? '+' : '' }}{{ Number(row.sector_change_pct).toFixed(2) }}
              </span>
              <span v-else class="no-data">--</span>
            </template>
          </el-table-column>
          <el-table-column label="板块资金流(亿)" min-width="100" sortable>
            <template #default="{ row }">
              <span v-if="row.sector_flow_net_yi !== null && row.sector_flow_net_yi !== undefined"
                :class="(row.sector_flow_net_yi || 0) >= 0 ? 'up' : 'down'">
                {{ (row.sector_flow_net_yi || 0) >= 0 ? '+' : '' }}{{ Number(row.sector_flow_net_yi).toFixed(2) }}
              </span>
              <span v-else class="no-data">--</span>
            </template>
          </el-table-column>
          <el-table-column label="热门股票" min-width="200">
            <template #default="{ row }">
              <div class="stock-list">
                <span v-for="s in row.stocks" :key="s.code" class="heat-stock-tag">
                  {{ s.name }} ({{ s.pct >= 0 ? '+' : '' }}{{ s.pct?.toFixed(2) || 0 }}%)
                </span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in conceptRank" :key="'concept-'+idx" class="m-sector-card">
          <div class="m-card-top">
            <div class="m-rank">{{ idx + 1 }}</div>
            <div style="flex:1;min-width:0">
              <span class="concept-name">{{ row.concept }}</span>
              <el-tag v-if="row.heat_type" :type="heatTypeTag(row.heat_type)" size="small" effect="plain" class="ml-2">{{ row.heat_type }}</el-tag>
            </div>
          </div>
          <div class="m-card-stats">
            <span class="m-stat"><b>{{ row.hit_count }}</b>命中</span>
            <span class="m-stat">人气<b>{{ row.total_heat }}</b></span>
            <span class="m-stat" v-if="row.sector_change_pct !== null" :class="(row.sector_change_pct || 0) >= 0 ? 'up' : 'down'">涨跌{{ row.sector_change_pct >= 0 ? '+' : '' }}{{ Number(row.sector_change_pct).toFixed(2) }}%</span>
            <span class="m-stat" v-if="row.sector_flow_net_yi !== null" :class="(row.sector_flow_net_yi || 0) >= 0 ? 'up' : 'down'">资金{{ (row.sector_flow_net_yi || 0) >= 0 ? '+' : '' }}{{ Number(row.sector_flow_net_yi).toFixed(2) }}亿</span>
          </div>
          <div class="m-card-stocks" v-if="row.stocks && row.stocks.length">
            <span v-for="s in row.stocks.slice(0, 4)" :key="s.code" class="heat-stock-tag">{{ s.name }}({{ s.pct >= 0 ? '+' : '' }}{{ Number(s.pct).toFixed(2) }}%)</span>
          </div>
        </div>
      </div>

      <!-- Hot Stocks -->
      <div class="section-title">人气榜 TOP20</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="hotStocks" stripe style="width: 100%" max-height="400" class="fit-table" table-layout="auto">
          <el-table-column prop="rank" label="排名" min-width="50" />
          <el-table-column prop="code" label="代码" min-width="70" />
          <el-table-column prop="name" label="名称" min-width="90" />
          <el-table-column prop="price" label="价格" min-width="60" />
          <el-table-column prop="pct" label="涨跌幅%" min-width="80" sortable>
            <template #default="{ row }">
              <span :class="row.pct >= 0 ? 'up' : 'down'" v-if="row.pct !== null && row.pct !== undefined">
                {{ row.pct >= 0 ? '+' : '' }}{{ Number(row.pct).toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="rank_chg" label="排名变化" min-width="80">
            <template #default="{ row }">
              <span v-if="row.rank_chg" :class="row.rank_chg > 0 ? 'up' : 'down'">
                {{ row.rank_chg > 0 ? '↑' : '↓' }}{{ Math.abs(row.rank_chg) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in hotStocks" :key="'hot-'+row.code+idx" class="m-stock-card">
          <div class="m-card-top">
            <div class="m-rank">{{ row.rank || idx + 1 }}</div>
            <div class="m-card-info">
              <span class="m-card-name">{{ row.name }}</span>
              <span class="m-card-code">{{ row.code }}</span>
            </div>
            <div class="m-price-col">
              <div class="m-price">¥{{ row.price || '--' }}</div>
              <div class="m-chg" :class="(row.pct ?? 0) >= 0 ? 'up' : 'down'" v-if="row.pct !== null">{{ row.pct >= 0 ? '+' : '' }}{{ Number(row.pct).toFixed(2) }}%</div>
            </div>
          </div>
          <div class="m-card-stats" v-if="row.rank_chg">
            <span class="m-stat" :class="row.rank_chg > 0 ? 'up' : 'down'">排名{{ row.rank_chg > 0 ? '↑' : '↓' }}{{ Math.abs(row.rank_chg) }}</span>
          </div>
        </div>
      </div>

      <!-- THS Hot List -->
      <div class="section-title">同花顺热榜</div>
      <!-- 桌面端表格 -->
      <div v-if="!isMobile" class="table-wrapper">
        <el-table :data="thsHotList" stripe style="width: 100%" max-height="400" table-layout="auto">
          <el-table-column prop="rank" label="排名" min-width="50" />
          <el-table-column prop="name" label="名称" min-width="90" />
          <el-table-column prop="code" label="代码" min-width="70" />
          <el-table-column prop="heat" label="人气值" min-width="70" sortable />
          <el-table-column prop="pct" label="涨跌幅%" min-width="70">
            <template #default="{ row }">
              <span :class="row.pct >= 0 ? 'up' : 'down'" v-if="row.pct !== null && row.pct !== undefined">
                {{ row.pct >= 0 ? '+' : '' }}{{ Number(row.pct).toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="rank_chg" label="排名变化" min-width="80">
            <template #default="{ row }">
              <span v-if="row.rank_chg" :class="row.rank_chg > 0 ? 'up' : 'down'">
                {{ row.rank_chg > 0 ? '↑' : '↓' }}{{ Math.abs(row.rank_chg) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="概念标签" min-width="150">
            <template #default="{ row }">
              <div class="concept-tags">
                <el-tag v-for="(c, idx) in row.concepts" :key="idx" size="small" effect="plain">
                  {{ c }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <!-- 移动端卡片 -->
      <div v-else class="mobile-card-list">
        <div v-for="(row, idx) in thsHotList" :key="'ths-'+row.code+idx" class="m-stock-card">
          <div class="m-card-top">
            <div class="m-rank">{{ row.rank || idx + 1 }}</div>
            <div class="m-card-info">
              <span class="m-card-name">{{ row.name }}</span>
              <span class="m-card-code">{{ row.code }} · 人气{{ row.heat }}</span>
            </div>
            <div class="m-price-col">
              <div class="m-chg" :class="(row.pct ?? 0) >= 0 ? 'up' : 'down'" v-if="row.pct !== null">{{ row.pct >= 0 ? '+' : '' }}{{ Number(row.pct).toFixed(2) }}%</div>
            </div>
          </div>
          <div class="m-card-stats" v-if="row.concepts && row.concepts.length">
            <el-tag v-for="(c, ci) in row.concepts.slice(0, 3)" :key="ci" size="small" effect="plain">{{ c }}</el-tag>
          </div>
        </div>
      </div>
      </div>
    </template>

    <transition name="empty-fade" v-else>
      <el-empty description="暂无热度数据" />
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
  key: 'sector:heat-rank',
  fetcher: () => sectorAnalysisApi.getHeatRank(30),
  tier: CACHE_TIERS.MARKET,
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
  const concepts = data.value.concept_heat_rank || []
  const hotStocks = data.value.hot_stocks || []
  const thsList = data.value.ths_hot_list || []
  return concepts.length > 0 || hotStocks.length > 0 || thsList.length > 0
})

let heatLoadedEmitted = false
watch(hasData, (val) => {
  if (val && !heatLoadedEmitted) {
    heatLoadedEmitted = true
    emit('loaded')
  }
})

const conceptRank = computed(() => data.value?.concept_heat_rank || [])
const hotStocks = computed(() => data.value?.hot_stocks || [])
const thsHotList = computed(() => data.value?.ths_hot_list || [])

function heatTypeTag(type) {
  const map = { '真热': 'danger', '虚热⚠️': 'warning', '温和': '', '未知': 'info' }
  return map[type] || ''
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
.heat-rank {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.heat-scroll-area {
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

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin: 8px 0 6px;
  padding-left: 8px;
  border-left: 3px solid #e6a23c;
}

.concept-name {
  font-weight: 500;
  color: #e6a23c;
}

.stock-list {
  display: flex;
  flex-wrap: nowrap;
  gap: 4px;
}

.heat-stock-tag {
  padding: 2px 8px;
  background: #fdf6ec;
  border-radius: 4px;
  font-size: 12px;
  color: #e6a23c;
  white-space: nowrap;
  flex-shrink: 0;
}

.concept-tags {
  display: flex;
  flex-wrap: nowrap;
  gap: 4px;
}

.up { color: #f56c6c; font-weight: 600; }
.down { color: #67c23a; font-weight: 600; }
.no-data { color: #ccc; }
.ml-4 { margin-left: 4px; }

.table-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

/* 内容一行显示不换行 */
.table-wrapper :deep(.el-table .cell) {
  white-space: nowrap !important;
}

/* 覆盖全局 table-layout: fixed + width:100%，启用 auto 自适应列宽 */
.heat-scroll-area :deep(.el-table__header-wrapper > table),
.heat-scroll-area :deep(.el-table__body-wrapper > table) {
  table-layout: auto !important;
  width: auto !important;
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
  .heat-scroll-area {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  .section-title {
    font-size: 12px;
    margin: 6px 0 4px;
  }

  /* 表格横向滚动（内容自适应列宽，一行显示不换行） */
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

  /* 覆盖全局 table-layout: fixed，手机端同样自适应列宽 */
  :deep(.el-table__header-wrapper > table),
  :deep(.el-table__body-wrapper > table) {
    table-layout: auto !important;
    width: auto !important;
  }

  :deep(.el-table th),
  :deep(.el-table td) {
    padding: 6px 4px !important;
    white-space: nowrap !important;
  }

  :deep(.el-table .cell) {
    font-size: 11px !important;
    white-space: nowrap !important;
  }

  .heat-stock-tag {
    font-size: 10px;
    padding: 1px 5px;
  }

  .concept-tags {
    gap: 2px;
  }

  :deep(.el-tag) {
    transform: scale(0.8);
    display: inline-block;
  }
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

@media (max-width: 480px) {
  .section-title {
    font-size: 11px;
    margin: 4px 0 3px;
  }

  /* 移动端卡片列表 */
  .mobile-card-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }

  .m-sector-card, .m-stock-card {
    background: var(--m-surface, #fff);
    border-radius: 12px;
    padding: 10px 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }

  .m-card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 0; }
  .m-rank { width: 22px; height: 22px; border-radius: 6px; background: var(--m-surface2, #f0f2f5); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: var(--m-text3, #8e99ab); flex-shrink: 0; }
  .m-card-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .m-card-name { font-size: 14px; font-weight: 600; color: var(--m-text, #1a2332); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .m-card-code { font-size: 11px; color: var(--m-text3, #8e99ab); }

  .m-price-col { text-align: right; flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
  .m-price { font-size: 15px; font-weight: 700; color: var(--m-text, #1a2332); }
  .m-chg { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 4px; display: inline-block; }
  .m-chg.up { background: var(--m-up-bg, rgba(231,76,60,0.08)); color: var(--m-up, #e74c3c); }
  .m-chg.down { background: var(--m-down-bg, rgba(46,204,113,0.08)); color: var(--m-down, #2ecc71); }

  .m-card-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--m-border, #e0e4ea); }
  .m-stat { font-size: 11px; color: var(--m-text2, #5a6577); white-space: nowrap; }
  .m-stat b { font-weight: 600; color: var(--m-text, #1a2332); }
  .m-stat.up { color: var(--m-up, #e74c3c) !important; }
  .m-stat.down { color: var(--m-down, #2ecc71) !important; }

  .m-card-stocks { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .ml-2 { margin-left: 4px; }
}
</style>
