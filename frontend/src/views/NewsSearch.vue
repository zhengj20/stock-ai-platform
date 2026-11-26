<template>
  <div class="news-page" :class="{ 'mobile-view': isMobile }">
    <!-- 后台刷新指示器 -->
    <RefreshingIndicator :show="hotNewsCache.refreshing.value || researchCache.refreshing.value" text="数据更新中" />

    <!-- 搜索区域：桌面端 el-card / 移动端 m-card -->
    <template v-if="isMobile">
      <div class="m-search-header">
        <h2 class="page-title m-page-title">
          <el-icon><Notebook /></el-icon>
          资讯研报
        </h2>
        <span class="last-update" v-if="hotNewsCache.lastUpdate.value">
          更新于 {{ formatTime(hotNewsCache.lastUpdate.value) }}
        </span>
      </div>

      <div class="m-card m-search-card">
        <el-input
          v-model="searchQuery"
          placeholder="搜索个股公告、研报、新闻..."
          clearable
          @keyup.enter="doSearch"
          class="search-input"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
          <template #append>
            <el-button @click="doSearch" :loading="loading" class="search-btn">搜索</el-button>
          </template>
        </el-input>

        <!-- 热点标签：移动端 m-filter-bar -->
        <div class="m-filter-bar hot-tags-row">
          <span
            v-for="(tag, index) in hotTags"
            :key="tag"
            class="fil hot-tag"
            @click="hotSearch(tag)"
            :class="'badge-' + hotTagTypes[index % hotTagTypes.length]"
          >{{ tag }}</span>
        </div>
      </div>
    </template>

    <el-card v-else shadow="hover" class="search-card">
      <div class="search-top">
        <h2 class="page-title">
          <el-icon><Notebook /></el-icon>
          资讯研报
        </h2>
        <span class="last-update" v-if="hotNewsCache.lastUpdate.value">
          更新于 {{ formatTime(hotNewsCache.lastUpdate.value) }}
        </span>
      </div>

      <div class="search-row">
        <el-input
          v-model="searchQuery"
          placeholder="搜索个股公告、研报、新闻..."
          size="large"
          clearable
          @keyup.enter="doSearch"
          class="search-input"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
          <template #append>
            <el-button @click="doSearch" :loading="loading" class="search-btn">搜索</el-button>
          </template>
        </el-input>

      </div>

      <!-- 热点标签 -->
      <div class="hot-tags-row">
        <span class="filter-label"><el-icon><Fire /></el-icon></span>
        <el-tag
          v-for="(tag, index) in hotTags"
          :key="tag"
          class="hot-tag"
          @click="hotSearch(tag)"
          :type="hotTagTypes[index % hotTagTypes.length]"
          size="small"
          effect="light"
        >{{ tag }}</el-tag>
      </div>
    </el-card>

    <!-- 主标签页：桌面端 el-tabs / 移动端 m-hscroll-tabs + m-filter-bar -->
    <template v-if="isMobile">
      <!-- 移动端 Tab 切换 -->
      <div class="m-hscroll-tabs news-mobile-tabs">
        <span class="tab" :class="{ active: activeTab === 'hot' }" @click="activeTab = 'hot'">
          <el-icon><TrendCharts /></el-icon> 热点资讯
        </span>
        <span class="tab" :class="{ active: activeTab === 'research' }" @click="activeTab = 'research'">
          <el-icon><Document /></el-icon> 研报精选
        </span>
        <span v-if="hasSearched" class="tab" :class="{ active: activeTab === 'search' }" @click="activeTab = 'search'">
          <el-icon><Search /></el-icon> "{{ searchQuery }}"
        </span>
      </div>

      <!-- 热点资讯面板 -->
      <template v-if="activeTab === 'hot'">
        <div class="m-section-header">
          <span><el-icon><TrendCharts /></el-icon></span> 热点资讯
          <span class="meta">{{ filteredHotItems.length }}条</span>
        </div>

        <!-- 来源筛选：移动端 m-filter-bar -->
        <div class="m-filter-bar sub-filter-bar">
          <span class="fil" :class="{ active: hotFilter === 'all' }" @click="hotFilter = 'all'">
            全部 ({{ hotNewsItems.length }})
          </span>
          <span v-for="src in hotSources" :key="src" class="fil" :class="{ active: hotFilter === src }" @click="hotFilter = src">
            {{ src }} ({{ countBySource(hotNewsItems, src) }})
          </span>
        </div>

        <div class="section-actions mobile-action">
          <el-button text type="primary" size="small" @click="loadHotNews(true)">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>

        <NewsList
          :items="filteredHotItems"
          :loading="hotLoading"
          :page-size="20"
          @news-click="showDetail"
          empty-text="暂无热点资讯，请输入关键词搜索"
          mobile
        />
      </template>

      <!-- 研报精选面板 -->
      <template v-if="activeTab === 'research'">
        <div class="m-section-header">
          <span><el-icon><Document /></el-icon></span> 研报精选
          <span class="meta">{{ researchItems.length }}条</span>
        </div>

        <div class="section-actions mobile-action">
          <el-button text type="primary" size="small" @click="loadResearchNews(true)">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>

        <NewsList
          :items="researchItems"
          :loading="researchLoading"
          :page-size="20"
          @news-click="showDetail"
          empty-text="暂无研报信息，请尝试搜索关键词"
          mobile
        />
      </template>

      <!-- 搜索结果面板 -->
      <template v-if="activeTab === 'search' && hasSearched">
        <div class="m-section-header">
          <span><el-icon><Search /></el-icon></span> "{{ searchQuery }}"
          <span class="meta">{{ filteredSearchItems.length }}条</span>
        </div>

        <!-- 来源筛选：移动端 m-filter-bar -->
        <div class="m-filter-bar sub-filter-bar">
          <span class="fil" :class="{ active: searchFilter === 'all' }" @click="searchFilter = 'all'">
            全部 ({{ searchResults.length }})
          </span>
          <span v-for="src in searchSources" :key="src" class="fil" :class="{ active: searchFilter === src }" @click="searchFilter = src">
            {{ src }} ({{ countBySource(searchResults, src) }})
          </span>
        </div>

        <NewsList
          :items="filteredSearchItems"
          :loading="loading"
          :page-size="20"
          @news-click="showDetail"
          empty-text="未找到相关资讯，请尝试其他关键词"
          mobile
        />
      </template>
    </template>

    <!-- 桌面端标签页 -->
    <el-card v-else shadow="hover" class="news-tabs-card">
      <el-tabs v-model="activeTab" class="news-tabs">
        <!-- 热点资讯 Tab -->
        <el-tab-pane name="hot">
          <template #label>
            <span class="tab-label"><el-icon><TrendCharts /></el-icon> 热点资讯</span>
          </template>
          <div class="sub-tabs-wrapper">
            <el-radio-group v-model="hotFilter" size="small" class="sub-tabs">
              <el-radio-button value="all">全部 ({{ hotNewsItems.length }})</el-radio-button>
              <el-radio-button v-for="src in hotSources" :key="src" :value="src">
                {{ src }} ({{ countBySource(hotNewsItems, src) }})
              </el-radio-button>
            </el-radio-group>
          </div>
          <div class="section-actions">
            <el-button text type="primary" size="small" @click="loadHotNews(true)">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
          <NewsList
            :items="filteredHotItems"
            :loading="hotLoading"
            :page-size="20"
            @news-click="showDetail"
            empty-text="暂无热点资讯，请输入关键词搜索"
          />
        </el-tab-pane>

        <!-- 研报精选 Tab -->
        <el-tab-pane name="research">
          <template #label>
            <span class="tab-label"><el-icon><Document /></el-icon> 研报精选</span>
          </template>
          <div class="section-actions">
            <el-button text type="primary" size="small" @click="loadResearchNews(true)">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
          <NewsList
            :items="researchItems"
            :loading="researchLoading"
            :page-size="20"
            @news-click="showDetail"
            empty-text="暂无研报信息，请尝试搜索关键词"
          />
        </el-tab-pane>

        <!-- 搜索结果 Tab -->
        <el-tab-pane v-if="hasSearched" name="search">
          <template #label>
            <span class="tab-label"><el-icon><Search /></el-icon> "{{ searchQuery }}"</span>
          </template>
          <div class="sub-tabs-wrapper">
            <el-radio-group v-model="searchFilter" size="small" class="sub-tabs">
              <el-radio-button value="all">全部 ({{ searchResults.length }})</el-radio-button>
              <el-radio-button v-for="src in searchSources" :key="src" :value="src">
                {{ src }} ({{ countBySource(searchResults, src) }})
              </el-radio-button>
            </el-radio-group>
          </div>
          <NewsList
            :items="filteredSearchItems"
            :loading="loading"
            :page-size="20"
            @news-click="showDetail"
            empty-text="未找到相关资讯，请尝试其他关键词"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 新闻详情弹窗 -->
    <el-dialog v-model="detailVisible" :width="isMobile ? '95%' : '680px'" top="5vh" :show-close="false" class="news-detail-dialog">
      <template #header="{ close }">
        <span></span>
      </template>
      <div class="article-container">
        <!-- 吸顶工具栏 -->
        <div class="sticky-bar">
          <span class="sticky-title">{{ cleanTitle(detailItem.title) }}</span>
          <button class="close-btn" @click="detailVisible = false">✕</button>
        </div>

        <div class="article-header">
          <div class="source-badge" :class="'badge-' + getSourceColor(detailItem.source)">
            {{ detailItem.source || '资讯' }}
          </div>
          <h2 class="article-title">{{ cleanTitle(detailItem.title) }}</h2>
          <div class="meta-row">
            <span class="meta-tag" v-if="detailItem.org">{{ detailItem.org }}</span>
            <span class="meta-divider" v-if="detailItem.org && detailItem.date">·</span>
            <span class="meta-tag" v-if="detailItem.date">{{ detailItem.date }}</span>
          </div>

        <div class="article-body" v-html="renderedContent"></div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'NewsSearch' })
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { nlpApi } from '@/api'
import { ElMessage } from 'element-plus'
import NewsList from './components/NewsList.vue'
import { useCachedFetch } from '@/composables/useCachedFetch'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'

const isMobile = ref(false)
function checkMobile() {
  isMobile.value = window.innerWidth <= 768
}
onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', checkMobile)
  if (searchAbortController) searchAbortController.abort()
})

const searchQuery = ref('')
const loading = ref(false)
const activeTab = ref('hot')
const hasSearched = ref(false)
let searchAbortController = null

// 子 tab 筛选
const hotFilter = ref('all')
const searchFilter = ref('all')

const detailVisible = ref(false)
const detailItem = ref({})

const hotTags = ['贵州茅台', '宁德时代', '人工智能', '新能源']
const hotTagTypes = ['', 'success', 'danger', 'primary']

// 热点资讯 - akshare 实时接口，5分钟刷新，拉近7天数据（增加到300条）
const hotNewsCache = useCachedFetch({
  key: () => `news:live:hot:${new Date().toISOString().slice(0, 10)}`,
  fetcher: () => nlpApi.getNewsLive(300),
  tier: { storageTTL: 5 * 60 * 1000, refreshInterval: 5 * 60 * 1000 },
  onSuccess: (res) => sortByDate(res?.news || []),
})

// 研报 - 东方财富实时接口，10分钟刷新，拉近7天数据（增加到200条）
const researchCache = useCachedFetch({
  key: () => `news:live:research:${new Date().toISOString().slice(0, 10)}`,
  fetcher: () => nlpApi.getResearchLive(200),
  tier: { storageTTL: 10 * 60 * 1000, refreshInterval: 10 * 60 * 1000 },
  onSuccess: (res) => sortByDate(res?.research || []),
})

const hotNewsItems = computed(() => hotNewsCache.data.value || [])
const researchItems = computed(() => researchCache.data.value || [])
const hotLoading = computed(() => hotNewsCache.loading.value)
const researchLoading = computed(() => researchCache.loading.value)

// 搜索结果
const searchResults = ref([])

// 动态来源列表
const hotSources = computed(() => [...new Set(hotNewsItems.value.map(i => i.source).filter(Boolean))])
const searchSources = computed(() => [...new Set(searchResults.value.map(i => i.source).filter(Boolean))])

// 按来源过滤
function countBySource(items, source) {
  return items.filter(i => i.source === source).length
}

const filteredHotItems = computed(() => {
  if (hotFilter.value === 'all') return hotNewsItems.value
  return hotNewsItems.value.filter(i => i.source === hotFilter.value)
})

const filteredSearchItems = computed(() => {
  if (searchFilter.value === 'all') return searchResults.value
  return searchResults.value.filter(i => i.source === searchFilter.value)
})

function cleanTitle(title) {
  if (!title) return ''
  return title.replace(/\s*---\s*$/, '').replace(/\s*\|.*$/, '').trim()
}

const renderedContent = computed(() => {
  let content = detailItem.value.content || ''
  if (!content) return '<p class="no-content">暂无详细内容</p>'

  const noisePatterns = [
    /^日期[:\s|]/, /类型[:\s|]/, /机构[:\s|]/,
    /^✅/, /^📄/, /纯文本结果已保存到/, /原始结果已保存到/,
    /声明[：:]/, /特别声明/, /Notice:/, /免责声明/,
    /^作者为/, /^本栏逢/,
  ]

  const rawLines = content.split('\n').map(l => l.trim()).filter(Boolean)
  const cleanLines = rawLines.filter(l => !noisePatterns.some(pat => pat.test(l)))

  if (cleanLines.length === 0) return '<p class="no-content">暂无详细内容</p>'

  const merged = [cleanLines[0]]
  for (let i = 1; i < cleanLines.length; i++) {
    const line = cleanLines[i]
    const prev = merged[merged.length - 1]
    if (line.length < 15 && !/[。！？；\n]$/.test(prev)) {
      merged[merged.length - 1] = prev + line
    } else {
      merged.push(line)
    }
  }

  return merged.map(p => `<p>${escapeHtml(p)}</p>`).join('')
})

function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

function getSourceColor(source) {
  const map = { '公告': 'warning', '研报': 'success', '政策': 'danger', '新闻': 'primary' }
  return map[source] || 'info'
}

function sortByDate(items) {
  if (!Array.isArray(items)) return []
  return [...items].sort((a, b) => {
    if (a.savedAt && b.savedAt) return b.savedAt.localeCompare(a.savedAt)
    if (a.savedAt) return -1
    if (b.savedAt) return 1
    if (a.date && b.date) return b.date.localeCompare(a.date)
    if (a.date) return -1
    if (b.date) return 1
    return 0
  })
}

function formatTime(timestamp) {
  const d = new Date(timestamp)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

async function doSearch() {
  if (!searchQuery.value.trim()) { ElMessage.warning('请输入搜索关键词'); return }
  if (loading.value) return

  // 取消上一次未完成的搜索
  if (searchAbortController) searchAbortController.abort()
  searchAbortController = new AbortController()

  loading.value = true
  hasSearched.value = true
  searchFilter.value = 'all'
  activeTab.value = 'search'

  try {
    const res = await nlpApi.searchNewsLive(searchQuery.value, 20, searchAbortController.signal)
    let items = sortByDate(res?.news || [])

    searchResults.value = items

    if (items.length === 0) {
      ElMessage.warning('未找到相关资讯，请尝试其他关键词')
    } else {
      ElMessage.success(`找到 ${items.length} 条结果`)
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      ElMessage.error('搜索失败: ' + e.message)
    }
  } finally {
    loading.value = false
  }
}

function hotSearch(tag) {
  searchQuery.value = tag
  doSearch()
}

async function loadHotNews(forceRefresh = false) {
  if (forceRefresh) hotNewsCache.clear()
  await hotNewsCache.refresh()
}

async function loadResearchNews(forceRefresh = false) {
  if (forceRefresh) researchCache.clear()
  await researchCache.refresh()
}

function showDetail(item) {
  detailItem.value = item
  detailVisible.value = true
}

</script>

<style scoped>
/* ================================================================
   桌面端样式（保持不变）
   ================================================================ */
.news-page {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 0;
}

.search-card {
  margin-bottom: 16px;
}

.search-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #303133;
  font-size: 20px;
  margin: 0;
}

.last-update {
  font-size: 12px;
  color: #909399;
}

.search-row {
  margin-bottom: 12px;
}

.search-input {
  width: 100%;
}

.search-input :deep(.search-btn) {
  background: #409eff !important;
  border-color: transparent !important;
  color: #fff !important;
  font-weight: 500;
  padding: 0 24px;
}

.search-input :deep(.search-btn:hover) {
  background: #66b1ff !important;
  border-color: transparent !important;
  color: #fff !important;
}

.search-input :deep(.search-btn:active) {
  background: #3a8ee6 !important;
  border-color: transparent !important;
}

.hot-tags-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-label {
  color: #909399;
  font-size: 13px;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 4px;
}

.hot-tag {
  cursor: pointer;
  transition: all 0.2s;
  margin-right: 4px;
  margin-bottom: 4px;
}

.hot-tag:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

/* 主标签页 */
.news-tabs-card {
  padding: 4px;
}

.news-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.news-tabs :deep(.el-tabs__nav-wrap)::after {
  background-color: #f0f0f0;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 子 tab */
.sub-tabs-wrapper {
  margin-bottom: 12px;
  padding-left: 4px;
}

.sub-tabs :deep(.el-radio-button__inner) {
  border-radius: 6px;
  padding: 4px 14px;
  font-size: 13px;
  color: #606266;
}

.sub-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background-color: #409eff;
  color: #fff;
  border-color: #409eff;
  box-shadow: -1px 0 0 0 #409eff;
}

.section-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

/* ================================================================
   移动端专用样式（v-if="isMobile" 渲染的模板）
   ================================================================ */
.mobile-view {
  padding: 4px 8px 70px !important;
  background: var(--m-bg, #f5f7fa);
}

/* 移动端搜索头部 - 紧凑布局 */
.m-search-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 4px 8px;
}

.m-page-title {
  font-size: 17px !important;
  color: var(--m-text, #1a2332);
  gap: 6px !important;
}

.m-search-header .last-update {
  font-size: 11px;
  color: var(--m-text3, #8e99ab);
}

/* 移动端搜索卡片 */
.m-search-card {
  padding: 10px 12px !important;
}

.m-search-card .search-input :deep(.el-input__wrapper) {
  border-radius: 10px;
  box-shadow: none;
  border: 1px solid var(--m-border, #e0e4ea);
  padding: 2px 4px 2px 12px;
}

.m-search-card .search-input :deep(.el-input__inner) {
  font-size: 13px !important;
  height: 34px;
  line-height: 34px;
}

.m-search-card .search-input :deep(.el-input__prefix) {
  margin-right: 4px;
}

.m-search-card .search-input :deep(.search-btn) {
  border-radius: 0 9px 9px 0 !important;
  padding: 0 14px !important;
  font-size: 13px !important;
  height: 34px !important;
  min-height: 34px !important;
  line-height: 34px !important;
}

/* 移动端热点标签 - m-filter-bar 样式覆盖 */
.mobile-view .hot-tags-row {
  margin-top: 6px;
  flex-wrap: nowrap !important;
}

.mobile-view .hot-tags-row .filter-label {
  flex-shrink: 0;
  color: var(--m-text3, #8e99ab);
  font-size: 12px;
}

.mobile-view .hot-tags-row .hot-tag {
  margin: 0 !important;
  border-radius: 16px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  min-height: 28px;
  display: inline-flex;
  align-items: center;
}

.mobile-view .hot-tags-row .hot-tag.badge-primary { background: #ecf5ff; color: #409eff; border: 1px solid #d9ecff; }
.mobile-view .hot-tags-row .hot-tag.badge-success { background: #f0f9eb; color: #67c23a; border: 1px solid #e1f3d8; }
.mobile-view .hot-tags-row .hot-tag.badge-danger { background: #fef0f0; color: #f56c6c; border: 1px solid #fde2e2; }
.mobile-view .hot-tags-row .hot-tag.badge-warning { background: #fdf6ec; color: #e6a23c; border: 1px solid #faecd8; }

/* m-section-header 内的图标样式 - 替代 ::before 竖条 */
.mobile-view .m-section-header::before {
  display: none;
}

.mobile-view .m-section-header > span:first-child {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--m-accent, #5b7cfa);
  border-radius: 4px;
  background: rgba(91, 124, 250, 0.08);
}

.mobile-view .m-section-header > span:first-child .el-icon {
  font-size: 14px;
}

/* 移动端 Tab 横滑 */
.news-mobile-tabs {
  margin-bottom: 8px;
}

.news-mobile-tabs .tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  min-height: 36px;
}

/* 子筛选条 */
.sub-filter-bar {
  margin-bottom: 4px;
  padding: 2px 0;
}

.mobile-action {
  padding: 0 0 6px !important;
}

/* ================================================================
   新闻详情弹窗（桌面 + 移动端共用）
   ================================================================ */
.news-detail-dialog :deep(.el-dialog) {
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.news-detail-dialog :deep(.el-dialog__header) {
  display: none;
}

.news-detail-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.article-container {
  background: #fff;
  max-height: 72vh;
  overflow-y: auto;
}

.sticky-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 48px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid #f0f0f0;
}

.sticky-title {
  font-size: 14px;
  font-weight: 500;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 16px;
}

.close-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: #f5f5f5;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #909399;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}

.close-btn:hover {
  background: #e8e8e8;
  color: #303133;
}

.article-header {
  padding: 24px 48px 20px;
}

.source-badge {
  display: inline-block;
  font-size: 12px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 4px;
  margin-bottom: 16px;
}

.source-badge.badge-primary { background: #ecf5ff; color: #409eff; }
.source-badge.badge-success { background: #f0f9eb; color: #67c23a; }
.source-badge.badge-warning { background: #fdf6ec; color: #e6a23c; }
.source-badge.badge-danger  { background: #fef0f0; color: #f56c6c; }
.source-badge.badge-info    { background: #f4f4f5; color: #909399; }

.article-title {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.5;
  color: #1a1a1a;
  margin: 0 0 14px 0;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #909399;
}

.meta-divider {
  color: #dcdfe6;
}

.article-body {
  padding: 24px 48px 40px;
}

.article-body :deep(p) {
  margin: 0 0 16px 0;
  font-size: 15px;
  line-height: 1.9;
  color: #333;
  text-indent: 2em;
  letter-spacing: 0.02em;
}

.no-content {
  color: #c0c4cc;
  padding: 48px 0;
  text-align: center;
  font-size: 14px;
}

.article-container::-webkit-scrollbar { width: 5px; }
.article-container::-webkit-scrollbar-track { background: transparent; }
.article-container::-webkit-scrollbar-thumb { background: #e8e8e8; border-radius: 3px; }
.article-container::-webkit-scrollbar-thumb:hover { background: #d0d0d0; }

/* ================================================================
   @media (max-width: 768px) — 页面级覆盖（兜底 + 弹窗适配）
   ================================================================ */
@media (max-width: 768px) {
  /* 弹窗移动端适配 - 底部弹出面板风格 */
  .news-detail-dialog :deep(.el-dialog) {
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    top: auto !important;
    border-radius: 16px 16px 0 0 !important;
    max-height: 92vh !important;
    overflow: hidden !important;
    box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.12) !important;
    animation: news-slide-up 0.3s ease !important;
  }

  @keyframes news-slide-up {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }

  .news-detail-dialog :deep(.el-dialog__body) {
    height: 92vh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .sticky-bar { padding: 10px 14px; }
  .article-header { padding: 14px; }
  .article-title { font-size: 17px; line-height: 1.5; }
  .article-body { padding: 12px 14px calc(30px + var(--m-safe-bottom, 0px)); }
  .article-body :deep(p) { font-size: 15px; line-height: 1.9; text-indent: 1.5em; }

  /* 桌面端模板兜底（如果 isMobile 检测失效） */
  .search-card,
  .news-tabs-card { border-radius: 14px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important; margin-bottom: 8px; }
  .search-card :deep(.el-card__body) { padding: 12px 14px !important; }
  .news-tabs-card :deep(.el-card__body) { padding: 8px 12px !important; }

  .page-title { font-size: 16px; }
  .search-top { flex-direction: column; align-items: flex-start; gap: 4px; }
  .last-update { font-size: 11px; }

  .hot-tags-row { overflow-x: auto; padding: 2px 0 4px; scrollbar-width: none; }
  .hot-tags-row::-webkit-scrollbar { display: none; }
  .hot-tags-row .hot-tag { flex-shrink: 0; margin: 0 !important; min-height: 28px; }

  .news-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
  .news-tabs :deep(.el-tabs__nav-wrap) { overflow-x: auto; white-space: nowrap; scrollbar-width: none; }
  .news-tabs :deep(.el-tabs__nav-wrap::-webkit-scrollbar) { display: none; }
  .news-tabs :deep(.el-tabs__item) { font-size: 12px; padding: 0 10px; height: 36px; line-height: 36px; }
  .news-tabs :deep(.el-tabs__nav) { display: flex; }

  .sub-tabs-wrapper { overflow-x: auto; scrollbar-width: none; padding: 2px 0 6px; }
  .sub-tabs-wrapper::-webkit-scrollbar { display: none; }
  .sub-tabs-wrapper .sub-tabs { display: flex; flex-wrap: nowrap; }
}

@media (max-width: 480px) {
  .mobile-view { padding: 2px 6px 70px !important; }
  .m-page-title { font-size: 15px !important; gap: 4px !important; }
  .news-mobile-tabs .tab :deep(.el-icon) { font-size: 13px; }
  .news-mobile-tabs .tab { padding: 6px 10px; font-size: 12px; }
  .m-search-card { padding: 8px 10px !important; }
  .sub-filter-bar { margin-bottom: 2px; }
  .mobile-action { padding: 0 0 4px !important; }
}
</style>
