<template>
  <div class="sector-analysis-page">
    <!-- 桌面端 Header -->
    <div class="page-header" v-if="!isMobile">
      <h2 class="page-title">板块深度分析</h2>
      <div class="header-meta">
        <span class="update-time" v-if="metaText">{{ metaText }}</span>
        <span class="update-time loading-hint" v-else-if="anyLoading">加载中...</span>
        <el-button :icon="Refresh" @click="refreshAll" :loading="globalLoading" plain size="default" class="refresh-btn">
          <span class="refresh-text">刷新全部</span>
        </el-button>
      </div>
    </div>

    <!-- 移动端 Header：方案A渐变卡片风格 -->
    <div class="m-page-header" v-else>
      <div class="m-header-card">
        <div class="m-header-left">
          <div class="m-header-icon">📈</div>
          <div class="m-header-info">
            <div class="m-header-title">板块深度分析</div>
            <div class="m-header-time">{{ metaText || (anyLoading ? '加载中...' : '数据已加载') }}</div>
          </div>
        </div>
        <div class="m-header-right">
          <div class="m-refresh-btn" @click="refreshAll" :class="{ 'm-refresh-loading': globalLoading }">
            <el-icon :class="{ 'm-refresh-spin': globalLoading }"><Refresh /></el-icon>
          </div>
        </div>
      </div>
    </div>

    <!-- 移动端胶囊导航（仅手机端显示） -->
    <div class="mobile-tab-nav">
      <div class="m-pill-scroll">
        <span v-for="tab in sectorTabList" :key="tab.name" class="m-pill" :class="{ 'm-pill--active': activeTab === tab.name, 'm-pill--loading': !tabLoadedSet[tab.name] }" @click="activeTab = tab.name">
          {{ tab.icon }} {{ tab.label }}
          <span v-if="!tabLoadedSet[tab.name]" class="m-pill-dot"></span>
        </span>
      </div>
    </div>

    <!-- Tab Navigation -->
    <el-tabs v-model="activeTab" type="border-card" class="analysis-tabs dragon-tabs">
      <!-- P0: 涨停梯队分析 -->
      <el-tab-pane label="涨停梯队" name="ladder">
        <div class="tab-content-wrap">
          <div v-if="!tabLoadedSet.ladder" class="tab-loading-skeleton">
            <el-skeleton :rows="8" animated />
          </div>
          <LimitUpLadder ref="ladderRef" @loading="(v) => loadingStates.ladder = v" @meta-update="(m) => onMetaUpdate(m, 'ladder')" @loaded="() => tabLoadedSet.ladder = true" />
        </div>
      </el-tab-pane>

      <!-- P0: 板块轮动量化模型 -->
      <el-tab-pane label="轮动量化" name="rotation">
        <div class="tab-content-wrap">
          <div v-if="!tabLoadedSet.rotation" class="tab-loading-skeleton">
            <el-skeleton :rows="8" animated />
          </div>
          <RotationModel ref="rotationRef" @loading="(v) => loadingStates.rotation = v" @meta-update="(m) => onMetaUpdate(m, 'rotation')" @loaded="() => tabLoadedSet.rotation = true" />
        </div>
      </el-tab-pane>

      <!-- P1: 行业研报聚合 -->
      <el-tab-pane label="行业研报" name="reports">
        <div class="tab-content-wrap">
          <div v-if="!tabLoadedSet.reports" class="tab-loading-skeleton">
            <el-skeleton :rows="8" animated />
          </div>
          <IndustryReports ref="reportsRef" @loading="(v) => loadingStates.reports = v" @meta-update="(m) => onMetaUpdate(m, 'reports')" @loaded="() => tabLoadedSet.reports = true" />
        </div>
      </el-tab-pane>

      <!-- P1: 板块热度排行 -->
      <el-tab-pane label="热度排行" name="heat">
        <div class="tab-content-wrap">
          <div v-if="!tabLoadedSet.heat" class="tab-loading-skeleton">
            <el-skeleton :rows="8" animated />
          </div>
          <HeatRank ref="heatRef" @loading="(v) => loadingStates.heat = v" @meta-update="(m) => onMetaUpdate(m, 'heat')" @loaded="() => tabLoadedSet.heat = true" />
        </div>
      </el-tab-pane>

      <!-- P2: 产业链深度分析 -->
      <el-tab-pane label="产业链" name="chain">
        <div class="tab-content-wrap">
          <div v-if="!tabLoadedSet.chain" class="tab-loading-skeleton">
            <el-skeleton :rows="8" animated />
          </div>
          <IndustryChain ref="chainRef" @loading="(v) => loadingStates.chain = v" @meta-update="(m) => onMetaUpdate(m, 'chain')" @loaded="() => tabLoadedSet.chain = true" />
        </div>
      </el-tab-pane>

      <!-- P2: 板块对比工具 -->
      <el-tab-pane label="板块对比" name="comparison">
        <div class="tab-content-wrap">
          <div v-if="!tabLoadedSet.comparison" class="tab-loading-skeleton">
            <el-skeleton :rows="8" animated />
          </div>
          <SectorComparison ref="comparisonRef" @loading="(v) => loadingStates.comparison = v" @meta-update="(m) => onMetaUpdate(m, 'comparison')" @loaded="() => tabLoadedSet.comparison = true" />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import LimitUpLadder from './components/LimitUpLadder.vue'
import RotationModel from './components/RotationModel.vue'
import IndustryReports from './components/IndustryReports.vue'
import HeatRank from './components/HeatRank.vue'
import IndustryChain from './components/IndustryChain.vue'
import SectorComparison from './components/SectorComparison.vue'

import { onMounted, onBeforeUnmount } from 'vue'

const isMobile = ref(window.innerWidth <= 768)
const onResize = () => { isMobile.value = window.innerWidth <= 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const activeTab = ref('ladder')

// 移动端胶囊导航列表
const sectorTabList = computed(() => [
  { name: 'ladder', label: '涨停梯队', icon: '📊' },
  { name: 'rotation', label: '轮动量化', icon: '🔄' },
  { name: 'reports', label: '行业研报', icon: '📄' },
  { name: 'heat', label: '热度排行', icon: '🔥' },
  { name: 'chain', label: '产业链', icon: '⛓️' },
  { name: 'comparison', label: '板块对比', icon: '📈' },
])
const globalLoading = ref(false)
const loadingStates = ref({})
const tabLoadedSet = ref({})
const metaText = ref('')

// 是否有任意tab尚未完成首次加载 - 用于显示统一加载动画
const anyLoading = computed(() => {
  for (const tab of sectorTabList.value) {
    if (!tabLoadedSet.value[tab.name]) {
      return true
    }
  }
  return false
})

// 超时兜底：30秒后强制标记所有tab为已加载，防止骨架屏永久显示
setTimeout(() => {
  for (const tab of sectorTabList.value) {
    if (!tabLoadedSet.value[tab.name]) {
      tabLoadedSet.value[tab.name] = true
    }
  }
}, 30000)
const ladderRef = ref(null)
const rotationRef = ref(null)
const reportsRef = ref(null)
const heatRef = ref(null)
const chainRef = ref(null)
const comparisonRef = ref(null)

function onMetaUpdate(meta, tabName) {
  if (meta && meta.data_date) {
    metaText.value = `数据日期: ${meta.data_date} | 更新: ${meta.update_time || '-'}`
  }
  if (tabName) {
    tabLoadedSet.value[tabName] = true
  }
}

async function refreshAll() {
  globalLoading.value = true
  try {
    // 按优先级串行刷新，配合后端 em_get 限流器
    const refs = [ladderRef, rotationRef, reportsRef, heatRef, chainRef, comparisonRef]
    for (const ref of refs) {
      await ref.value?.fetchData?.()
      // 等待限流间隔，避免并发请求堆积
      await new Promise(r => setTimeout(r, 800))
    }
  } finally {
    globalLoading.value = false
  }
}
</script>

<style scoped>
.sector-analysis-page {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px;
  background: #f5f7fa;
}

/* 移动端胶囊导航：桌面端隐藏 */
.mobile-tab-nav { display: none !important; }

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-shrink: 0;
  padding: 0 4px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #1a1a1a;
  margin: 0;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.update-time {
  font-size: 13px;
  color: #909399;
}

.loading-hint {
  color: #5b7cfa !important;
  animation: loading-pulse 1.5s ease-in-out infinite;
}

@keyframes loading-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Tab content wrapper with skeleton overlay */
.tab-content-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.tab-loading-skeleton {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.95);
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  backdrop-filter: blur(2px);
}

/* Mobile pill loading dot */
.m-pill--loading {
  color: var(--m-text3, #8e99ab) !important;
}

.m-pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #5b7cfa;
  display: inline-block;
  animation: pill-dot-pulse 1s ease-in-out infinite;
  margin-left: 2px;
}

@keyframes pill-dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.3; transform: scale(0.6); }
}

/* ========== 移动端 Header：方案A渐变卡片风格 ========== */
.m-page-header {
  display: none;
}
.m-header-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  background: linear-gradient(135deg, rgba(91,124,250,0.08), rgba(91,124,250,0.02));
  border-radius: 10px;
}
.m-header-left {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  min-width: 0;
}
.m-header-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(91,124,250,0.15);
  border-radius: 50%;
  font-size: 11px;
  flex-shrink: 0;
}
.m-header-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.m-header-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a2332;
  line-height: 1.2;
}
.m-header-time {
  font-size: 9px;
  color: #5b7cfa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.1;
}
.m-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.m-refresh-btn {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}
.m-refresh-btn:active {
  transform: scale(0.9);
  background: rgba(91,124,250,0.1);
  border-color: #5b7cfa;
}
.m-refresh-btn .el-icon {
  font-size: 12px;
  color: #606266;
}
.m-refresh-spin {
  animation: m-spin 1s linear infinite;
  color: #5b7cfa !important;
}
@keyframes m-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.analysis-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: transparent;
}

.analysis-tabs :deep(.el-tabs__header) {
  flex-shrink: 0;
  margin-bottom: 0;
}

.analysis-tabs :deep(.el-tabs__content) {
  flex: 1;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
  min-height: 0;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}

/* 激活 pane 占满，非激活隐藏（Element Plus 用 inline style display:none 隐藏） */
.analysis-tabs :deep(.el-tabs__content > .el-tab-pane) {
  display: none !important;
}
.analysis-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
  display: flex !important;
  flex-direction: column !important;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

/* ========== H5 移动端适配（卡片化设计） ========== */
@media (max-width: 768px) {
  /* ── 页面容器：紧凑间距 + safe-area ── */
  .sector-analysis-page {
    padding: 6px 4px;
    top: 0 !important;
    bottom: 0 !important;
    background: var(--m-bg, #f5f7fa);
  }

  /* ── Header：移动端显示新样式，隐藏桌面端 ── */
  .page-header { display: none !important; }
  .m-page-header { display: block !important; margin-bottom: 6px; }

  /* ── Tabs：移动端横向滚动标签栏（m-hscroll-tabs 风格） ── */
  /* Tabs 外层 overflow:hidden 会裁剪分页，移动端改为 visible */
  .analysis-tabs {
    overflow: visible !important;
  }
  .analysis-tabs :deep(.el-tabs__content) {
    overflow: visible !important;
  }

  /* 隐藏原生 el-tabs 头部，用自定义胶囊导航替代 */
  .dragon-tabs :deep(.el-tabs__header) { display: none !important; }

  /* 移动端 el-tabs 容器去掉边框（与胶囊导航融合） */
  .dragon-tabs.el-tabs--border-card {
    border: none !important;
    border-radius: var(--m-card-radius, 16px) !important;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)) !important;
  }

  .dragon-tabs :deep(.el-tabs__content) { padding: 0 !important; }
  .dragon-tabs :deep(.el-tabs__content > .el-tab-pane) { padding: 12px !important; }

  /* ========== 移动端胶囊导航 ========== */
  .mobile-tab-nav {
    display: block !important;
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    margin-bottom: 8px;
    overflow: hidden;
  }

  .m-pill-scroll {
    display: flex;
    gap: 8px;
    padding: 10px 14px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    background: var(--m-surface, #fff);
  }

  .m-pill-scroll::-webkit-scrollbar { display: none; }

  .m-pill {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 7px 14px;
    border-radius: 16px;
    font-size: 12px;
    color: var(--m-text3, #8e99ab);
    background: var(--m-surface2, #f0f2f5);
    white-space: nowrap;
    cursor: pointer;
    transition: all 0.2s ease;
    -webkit-tap-highlight-color: transparent;
  }

  .m-pill--active {
    color: #fff !important;
    background: var(--m-accent, #5b7cfa) !important;
    font-weight: 600;
    box-shadow: 0 2px 6px rgba(91, 124, 250, 0.3);
  }

  .m-pill:active { transform: scale(0.96); }

  .analysis-tabs :deep(.el-tabs__header) {
    margin-bottom: 0;
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    padding: 4px 0 2px;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
  }

  .analysis-tabs :deep(.el-tabs__nav-wrap) {
    overflow-x: auto !important;
    white-space: nowrap;
    -webkit-overflow-scrolling: touch;
  }

  .analysis-tabs :deep(.el-tabs__nav-scroll) {
    overflow-x: auto !important;
    overflow-y: hidden !important;
    -webkit-overflow-scrolling: touch;
  }

  .analysis-tabs :deep(.el-tabs__nav) {
    display: flex !important;
    float: none !important;
  }

  .analysis-tabs :deep(.el-tabs__item) {
    font-size: 12px;
    padding: 0 10px;
    height: 34px;
    line-height: 34px;
    min-width: fit-content;
    border-bottom: 2px solid transparent !important;
    border-radius: 0;
    color: var(--m-text3, #8e99ab);
    transition: all 0.2s;
  }

  .analysis-tabs :deep(.el-tabs__item.is-active) {
    color: var(--m-accent, #5b7cfa);
    border-bottom-color: var(--m-accent, #5b7cfa) !important;
    font-weight: 600;
  }

  .analysis-tabs :deep(.el-tabs__nav-scroll::-webkit-scrollbar) {
    display: none;
  }

  /* ── Tab Content：卡片容器（m-card 风格） ── */
  .analysis-tabs :deep(.el-tabs__content) {
    padding: 6px 2px;
    border-radius: 0;
    box-shadow: none;
    background: var(--m-bg, #f5f7fa);
    margin-top: 4px;
  }

  /* ── 子组件 el-card：统一卡片样式（m-card） ── */
  .analysis-tabs :deep(.el-card) {
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px) !important;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)) !important;
    margin-bottom: 10px;
    border: none;
  }

  .analysis-tabs :deep(.el-card__body) {
    padding: 12px 14px !important;
  }

  /* ── el-table：移动端表格卡片化包装（m-rank-list 风格） ── */
  .analysis-tabs :deep(.el-table) {
    font-size: 12px !important;
    border-radius: var(--m-card-radius, 16px);
    overflow: hidden;
    border: 1px solid var(--m-border, #e0e4ea);
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    background: var(--m-surface, #fff);
  }

  .analysis-tabs :deep(.el-table__header-wrapper) {
    background: var(--m-surface2, #f0f2f5);
  }

  .analysis-tabs :deep(.el-table th.el-table__cell) {
    background: var(--m-surface2, #f0f2f5) !important;
    color: var(--m-text2, #5a6577);
    font-size: 11px !important;
    font-weight: 600;
    padding: 8px 4px !important;
    border-bottom: 1px solid var(--m-border, #e0e4ea) !important;
  }

  .analysis-tabs :deep(.el-table td.el-table__cell) {
    padding: 8px 4px !important;
    font-size: 12px !important;
    border-bottom-color: var(--m-border, #e0e4ea);
  }

  .analysis-tabs :deep(.el-table tr:hover > td) {
    background: var(--m-surface2, #f0f2f5) !important;
  }

  /* ── el-statistic：统计卡片（m-stat-card 风格） ── */
  .analysis-tabs :deep(.el-statistic) {
    text-align: center;
    padding: 8px 4px;
  }

  .analysis-tabs :deep(.el-statistic__head) {
    font-size: 10px !important;
    color: var(--m-text3, #8e99ab);
    margin-bottom: 2px;
  }

  .analysis-tabs :deep(.el-statistic__content) {
    font-size: 16px !important;
    font-weight: 700;
    color: var(--m-text, #1a2332);
  }

  .analysis-tabs :deep(.el-statistic__suffix) {
    font-size: 10px !important;
    color: var(--m-text3, #8e99ab);
  }

  /* ── el-tag：紧凑标签 ── */
  .analysis-tabs :deep(.el-tag) {
    transform: scale(0.85);
    display: inline-block;
    margin: 1px 2px;
  }

  /* ── el-progress：进度条紧凑化 ── */
  .analysis-tabs :deep(.el-progress__text) {
    font-size: 10px !important;
  }

  /* ── el-timeline：时间线移动端适配 ── */
  .analysis-tabs :deep(.el-timeline-item__timestamp) {
    font-size: 10px !important;
    color: var(--m-text3, #8e99ab);
  }

  /* ── el-alert：紧凑警告框 ── */
  .analysis-tabs :deep(.el-alert) {
    padding: 8px 10px !important;
    border-radius: 10px;
    margin-bottom: 8px;
  }

  .analysis-tabs :deep(.el-alert__content) {
    font-size: 11px !important;
  }

  /* ── Tab pane 内容底部避开导航栏 ── */
  .analysis-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  /* ── el-pagination：紧凑分页，紧靠底部导航栏 ── */
  .analysis-tabs :deep(.el-pagination) {
    flex-wrap: wrap;
    justify-content: center;
    gap: 2px;
    padding: 2px 0 calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0));
    margin-top: 2px;
  }

  .analysis-tabs :deep(.el-pagination button),
  .analysis-tabs :deep(.el-pagination span) {
    min-width: 26px !important;
    height: 26px !important;
    font-size: 11px !important;
    border-radius: 6px;
  }

  /* ── el-input / el-radio-group：表单紧凑化 ── */
  .analysis-tabs :deep(.el-input__inner) {
    font-size: 12px !important;
    border-radius: 8px;
  }

  .analysis-tabs :deep(.el-radio-button__inner) {
    padding: 5px 10px !important;
    font-size: 11px !important;
    border-radius: 8px !important;
  }

  /* ── el-skeleton：骨架屏紧凑化 ── */
  .analysis-tabs :deep(.el-skeleton__item) {
    height: 12px !important;
    margin-bottom: 6px !important;
    border-radius: 4px;
  }

  /* ── el-empty：空状态紧凑化 ── */
  .analysis-tabs :deep(.el-empty__description) {
    font-size: 12px !important;
    color: var(--m-text3, #8e99ab);
  }
}

@media (max-width: 480px) {
  /* ── 超小屏：极致紧凑布局 ── */
  .sector-analysis-page {
    padding: 4px 3px;
    top: 0 !important;
    bottom: 0 !important;
  }

  .page-header {
    margin-bottom: 4px;
    gap: 3px;
  }

  .page-title {
    font-size: 16px;
  }

  .update-time {
    font-size: 9px;
  }

  .header-meta :deep(.el-button) {
    padding: 4px 6px;
    font-size: 10px;
    min-height: 28px;
  }

  /* ── Tabs：超小屏更紧凑 ── */
  /* Tabs 外层 overflow:hidden 会裁剪分页，移动端改为 visible */
  .analysis-tabs {
    overflow: visible !important;
  }
  .analysis-tabs :deep(.el-tabs__content) {
    overflow: visible !important;
  }

  .analysis-tabs :deep(.el-tabs__header) {
    padding: 3px 0 1px;
    border-radius: 12px;
  }

  .analysis-tabs :deep(.el-tabs__item) {
    font-size: 11px;
    padding: 0 8px;
    height: 30px;
    line-height: 30px;
  }

  .analysis-tabs :deep(.el-tabs__content) {
    padding: 4px 2px;
    margin-top: 3px;
  }

  /* ── el-table：超小屏进一步紧凑 ── */
  .analysis-tabs :deep(.el-table) {
    font-size: 11px !important;
    border-radius: 12px;
  }

  .analysis-tabs :deep(.el-table th.el-table__cell),
  .analysis-tabs :deep(.el-table td.el-table__cell) {
    padding: 6px 3px !important;
    font-size: 10px !important;
  }

  /* ── el-card：超小屏紧凑卡片 ── */
  .analysis-tabs :deep(.el-card) {
    border-radius: 12px !important;
    margin-bottom: 8px;
  }

  .analysis-tabs :deep(.el-card__body) {
    padding: 10px 12px !important;
  }

  /* ── el-statistic：超小屏统计卡片 ── */
  .analysis-tabs :deep(.el-statistic__content) {
    font-size: 14px !important;
  }

  .analysis-tabs :deep(.el-statistic__head) {
    font-size: 9px !important;
  }

  /* ── el-pagination：超小屏分页 ── */
  .analysis-tabs :deep(.el-pagination button),
  .analysis-tabs :deep(.el-pagination span) {
    min-width: 24px !important;
    height: 24px !important;
    font-size: 10px !important;
  }

  /* ── el-tag：超小屏标签 ── */
  .analysis-tabs :deep(.el-tag) {
    transform: scale(0.78);
  }

  /* ── el-input / radio：超小屏表单 ── */
  .analysis-tabs :deep(.el-radio-button__inner) {
    padding: 4px 8px !important;
    font-size: 10px !important;
  }
}
</style>
