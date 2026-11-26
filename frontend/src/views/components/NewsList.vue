<template>
  <div class="news-list-container" :class="{ 'mobile-mode': mobile }">
    <div v-if="loading" class="list-loading">
      <el-skeleton :rows="5" animated />
    </div>

    <div v-else-if="pagedItems.length === 0" class="empty-state">
      <div class="empty-icon">
        <el-icon :size="64" color="#c0c4cc"><DocumentCopy /></el-icon>
      </div>
      <p class="empty-text">{{ emptyText }}</p>
    </div>

    <!-- 移动端：m-alert-item 风格卡片列表 -->
    <template v-else-if="mobile">
      <template v-for="(group, dateKey) in groupedItems" :key="dateKey">
        <div class="m-section-header mobile-date-group">
          {{ formatDateLabel(dateKey) }}
          <span class="meta">{{ group.length }}条</span>
        </div>

        <div class="m-card mobile-news-list" style="padding: 0; overflow: hidden;">
          <div
            v-for="(item, index) in group"
            :key="index"
            class="mobile-news-item"
            @click="$emit('news-click', item)"
          >
            <!-- 彩色圆点标识来源类型 -->
            <span class="dot" :class="getDotColor(item.source)"></span>

            <div class="body">
              <div class="title">{{ cleanTitle(item.title) }}</div>
              <div class="desc">
                <template v-if="item.org">{{ item.org }}</template>
                <template v-if="item.org && item.date"> · </template>
                <template v-if="!item.org && item.date">{{ item.date }}</template>
              </div>
            </div>

            <span class="time mobile-source-badge" :class="'badge-' + getSourceColor(item.source)">
              {{ item.source || '资讯' }}
            </span>
          </div>
        </div>
      </template>

      <!-- 移动端分页 -->
      <div class="pagination-wrapper mob-pagination" v-if="items.length > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="items.length"
          layout="prev, pager, next"
          small
          background
        />
      </div>
    </template>

    <!-- 桌面端：原有卡片布局 -->
    <template v-else>
      <!-- 日期分组标题 -->
      <template v-for="(group, dateKey) in groupedItems" :key="dateKey">
        <div class="date-group-header">
          <el-icon><Calendar /></el-icon>
          <span>{{ formatDateLabel(dateKey) }}</span>
          <span class="group-count">{{ group.length }}条</span>
        </div>
        <div class="date-group-cards">
          <div
            v-for="(item, index) in group"
            :key="index"
            class="news-card"
            @click="$emit('news-click', item)"
          >
            <!-- 来源标签 -->
            <span class="card-source" :class="'badge-' + getSourceColor(item.source)">
              {{ item.source || '资讯' }}
            </span>

            <h3 class="card-title">{{ cleanTitle(item.title) }}</h3>

            <div class="card-body">
              <p class="card-summary">{{ getSummary(item.content) }}</p>
            </div>

            <div class="card-footer">
              <span class="footer-item" v-if="item.org">
                <el-icon><OfficeBuilding /></el-icon>
                {{ item.org }}
              </span>
              <span class="footer-item" v-if="item.time && item.time !== item.date">
                <el-icon><Clock /></el-icon>
                {{ item.time.substring(10) }}
              </span>
            </div>
          </div>
        </div>
      </template>

      <!-- 分页 -->
      <div class="pagination-wrapper" v-if="items.length > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="items.length"
          layout="prev, pager, next"
          small
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  pageSize: { type: Number, default: 20 },
  mobile: { type: Boolean, default: false }
})

defineEmits(['news-click'])

const currentPage = ref(1)

watch(() => props.items, () => {
  currentPage.value = 1
})

// 分页后的条目
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * props.pageSize
  return props.items.slice(start, start + props.pageSize)
})

// 按日期分组
const groupedItems = computed(() => {
  const groups = {}
  for (const item of pagedItems.value) {
    const dateKey = item.date || '未知'
    if (!groups[dateKey]) groups[dateKey] = []
    groups[dateKey].push(item)
  }
  return groups
})

function formatDateLabel(dateStr) {
  if (!dateStr || dateStr === '未知') return dateStr
  const today = new Date()
  const todayStr = today.toISOString().split('T')[0]
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const yesterdayStr = yesterday.toISOString().split('T')[0]

  if (dateStr === todayStr) return '今天'
  if (dateStr === yesterdayStr) return '昨天'
  const month = parseInt(dateStr.split('-')[1])
  const day = parseInt(dateStr.split('-')[2])
  return `${month}月${day}日`
}

function getSourceColor(source) {
  const map = { '公告': 'warning', '研报': 'success', '政策': 'danger', '新闻': 'primary', '快讯': 'info' }
  return map[source] || 'info'
}

function getDotColor(source) {
  const map = { '公告': 'gold', '研报': 'green', '政策': 'red', '新闻': 'blue', '快讯': 'red' }
  return map[source] || 'blue'
}

function cleanTitle(title) {
  if (!title) return ''
  return title.replace(/\s*---\s*$/, '').replace(/\s*\|.*$/, '').trim()
}

function getSummary(content) {
  if (!content) return ''
  const text = content.replace(/\n/g, ' ').trim()
  return text.length > 100 ? text.substring(0, 100) + '...' : text
}
</script>

<style scoped>
.news-list-container {
  min-height: 100px;
}

.list-loading {
  padding: 20px 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
}

.empty-icon {
  opacity: 0.6;
  margin-bottom: 8px;
}

.empty-text {
  color: #909399;
  font-size: 14px;
  margin: 0;
}

/* 日期分组 */
.date-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #409eff;
  border-bottom: 1px solid #f0f7ff;
  margin-bottom: 4px;
}

.date-group-header .el-icon {
  font-size: 15px;
}

.group-count {
  margin-left: auto;
  font-weight: 400;
  color: #909399;
  font-size: 12px;
}

.date-group-cards {
  margin-bottom: 8px;
}

/* 卡片 */
.news-card {
  position: relative;
  background: #fafbfc;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.news-card:hover {
  background: #fff;
  border-color: #409eff;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.1);
}

.card-source {
  position: absolute;
  top: 8px;
  right: 12px;
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 3px;
}

.card-source.badge-primary { background: #ecf5ff; color: #409eff; }
.card-source.badge-success { background: #f0f9eb; color: #67c23a; }
.card-source.badge-warning { background: #fdf6ec; color: #e6a23c; }
.card-source.badge-danger  { background: #fef0f0; color: #f56c6c; }
.card-source.badge-info    { background: #f4f4f5; color: #909399; }

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px 0;
  line-height: 1.6;
}

.card-body {
  margin-bottom: 8px;
}

.card-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12px;
  color: #909399;
}

.footer-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #f5f5f5;
}

/* ================================================================
   移动端新闻列表样式（m-alert-item 风格）
   ================================================================ */
.mobile-mode .mobile-date-group {
  padding: 10px 0 6px;
  font-size: 14px;
}

.mobile-news-list {
  margin-bottom: 12px;
}

.mobile-news-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 14px;
  border-bottom: 1px solid #f0f2f5;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background 0.15s;
  min-height: 48px;
}

.mobile-news-item:last-child {
  border-bottom: none;
}

.mobile-news-item:active {
  background: var(--m-surface2, #f0f2f5);
}

.mobile-news-item .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}

.mobile-news-item .dot.red { background: var(--m-up, #e74c3c); }
.mobile-news-item .dot.green { background: var(--m-down, #2ecc71); }
.mobile-news-item .dot.gold { background: var(--m-gold, #f0b429); }
.mobile-news-item .dot.blue { background: var(--m-accent, #5b7cfa); }

.mobile-news-item .body {
  flex: 1;
  min-width: 0;
}

.mobile-news-item .body .title {
  font-size: 13px;
  font-weight: 500;
  color: var(--m-text, #1a2332);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mobile-news-item .body .desc {
  font-size: 11px;
  color: var(--m-text3, #8e99ab);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mobile-news-item .mobile-source-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  white-space: nowrap;
  line-height: 1.6;
  min-width: 28px;
  text-align: center;
}

.mobile-news-item .mobile-source-badge.badge-primary { background: #ecf5ff; color: #409eff; }
.mobile-news-item .mobile-source-badge.badge-success { background: #f0f9eb; color: #67c23a; }
.mobile-news-item .mobile-source-badge.badge-warning { background: #fdf6ec; color: #e6a23c; }
.mobile-news-item .mobile-source-badge.badge-danger  { background: #fef0f0; color: #f56c6c; }
.mobile-news-item .mobile-source-badge.badge-info    { background: #f4f4f5; color: #909399; }

/* 桌面端媒体查询兜底 */
@media (max-width: 768px) {
  .news-card { padding: 12px; }
  /* 分页紧靠底部导航栏 */
  .pagination-wrapper {
    padding: 1px 0 calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0));
    margin-top: 1px;
  }
  /* 移动端分页固定底部 */
  .mob-pagination {
    background: #fff !important;
    box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
    padding: 1px 1px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)) !important;
    min-height: 24px !important;
  }
  .mob-pagination :deep(.el-pagination) { font-size: 11px !important; justify-content: center; }
  .mob-pagination :deep(.el-pager li) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; font-size: 11px !important; }
  .mob-pagination :deep(.el-pagination button) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; }
}
</style>
