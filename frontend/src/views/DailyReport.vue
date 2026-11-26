<template>
  <div class="report-page">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title"><el-icon><Notebook /></el-icon> 每日复盘报告</h2>
        <span class="disclaimer-inline">本报告由AI智能生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。</span>
      </div>
      <div class="header-actions" :class="{ 'mobile-header': isMobile }">
        <RefreshingIndicator :show="reportListCache.refreshing.value || reportDetailCache.refreshing.value" text="数据更新中" />
        <el-date-picker
          v-model="selectedDate"
          type="date"
          placeholder="选择日期"
          value-format="YYYY-MM-DD"
          :disabled-date="disableMobileDate"
          :clearable="false"
          @change="loadReportByDate"
          :style="{ width: isMobile ? 'auto' : '160px', flex: isMobile ? '1' : 'none' }"
        />
        <el-button type="primary" :icon="Refresh" circle @click="refreshCurrent" :loading="loading" class="desktop-only" />
        <el-button v-if="isMobile" type="primary" text :icon="Refresh" @click="refreshCurrent" :loading="loading" class="mobile-refresh">刷新</el-button>
        <el-button v-if="authStore.isAdmin && !isMobile" type="warning" @click="handleGenerate" :loading="generating">
          生成当日报告
        </el-button>
        <el-button v-if="authStore.isAdmin && isMobile" type="warning" text size="small" @click="handleGenerate" :loading="generating" class="mobile-gen-btn">生成</el-button>
      </div>
    </div>

    <!-- 移动端：卡片式报告布局 -->
    <template v-if="isMobile">
      <div class="mob-report-container" v-loading="loadingReport">

        <!-- 日期快速选择器 -->
        <div v-if="reportList.length > 1" class="m-card mob-date-tabs">
          <div class="m-hscroll-tabs">
            <span
              v-for="item in reportList.slice(0, 14)"
              :key="'tab-' + item.report_date"
              class="tab"
              :class="{ active: currentReport?.report_date === item.report_date }"
              @click="selectReport(item.report_date)"
            >
              {{ formatDateTab(item.report_date) }}
            </span>
          </div>
        </div>

        <!-- 报告头部信息卡 -->
        <div v-if="currentReport" class="m-card mob-report-header">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <div style="font-size:16px;font-weight:700;color:var(--m-text);">{{ currentReport.report_date }}</div>
              <div style="font-size:12px;color:var(--m-text3);margin-top:2px;">每日复盘报告</div>
            </div>
            <el-tag :type="currentReport.status === 'completed' ? 'success' : currentReport.status === 'generating' ? 'warning' : 'danger'" size="small" style="min-height:24px;padding:0 10px;">{{ statusLabel(currentReport.status) }}</el-tag>
          </div>

          <!-- 已完成：统计卡片 -->
          <div v-if="currentReport.status === 'completed'" class="m-stats-row mob-stats">
            <div class="m-stat-card" style="cursor:default;">
              <div class="val accent">{{ extractWordCount(currentReport.ai_report) }}</div>
              <div class="lbl">字数</div>
            </div>
            <div class="m-stat-card" style="cursor:default;">
              <div class="val accent">{{ formatTime(currentReport.generated_at) }}</div>
              <div class="lbl">生成时间</div>
            </div>
            <div class="m-stat-card" style="cursor:default;">
              <div class="val accent">{{ extractSectionCount(currentReport.ai_report) }}</div>
              <div class="lbl">分析板块</div>
            </div>
            <div class="m-stat-card" style="cursor:default;">
              <div class="val up">AI</div>
              <div class="lbl">智能生成</div>
            </div>
          </div>

          <!-- 生成中：进度提示 -->
          <div v-if="currentReport.status === 'generating'" class="mob-generating">
            <div class="m-alert-item" style="border-bottom:none;padding:8px 0;">
              <span class="dot blue"></span>
              <div class="body">
                <div class="title" style="color:#409eff;">报告生成中，请稍候...</div>
                <div class="desc">AI推理通常需要1-3分钟</div>
              </div>
            </div>
            <el-button type="primary" size="small" style="margin-top:8px;width:100%;min-height:40px;" @click="refreshCurrent" :loading="loading">刷新查看进度</el-button>
          </div>

          <!-- 生成失败：错误提示 -->
          <div v-if="currentReport.status === 'failed'" class="mob-failed">
            <div class="m-alert-item" style="border-bottom:none;padding:8px 0;">
              <span class="dot red"></span>
              <div class="body">
                <div class="title" style="color:#f56c6c;">报告生成失败</div>
                <div class="desc">{{ currentReport.error_msg || '未知错误' }}</div>
              </div>
            </div>
            <el-button v-if="authStore.isAdmin" type="warning" size="small" style="margin-top:8px;width:100%;min-height:40px;" @click="handleGenerate">重新生成</el-button>
          </div>
        </div>

        <!-- 报告内容卡 -->
        <div v-if="currentReport?.ai_report && currentReport.status === 'completed'" class="m-card mob-report-body">
          <div class="mob-md-content" v-html="renderMarkdown(currentReport.ai_report)" />
        </div>

        <!-- 加载中提示 -->
        <div v-if="!currentReport && loadingReport" class="m-card mob-placeholder">
          <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          <p style="margin-top:12px;color:var(--m-text3);font-size:13px;">正在加载报告内容...</p>
        </div>

        <!-- 空状态 -->
        <div v-if="!currentReport && !loadingReport" class="m-card mob-placeholder">
          <el-empty description="暂无报告数据" :image-size="80">
            <template #description>
              <p style="color:var(--m-text3);font-size:12px;margin-top:8px;text-align:center;line-height:1.6;">系统定时生成复盘报告，当前暂无数据。<br /><span v-if="authStore.isAdmin">点击上方「生成当日报告」手动触发</span><span v-else>请联系管理员生成</span></p>
            </template>
          </el-empty>
        </div>

      </div>
    </template>

    <!-- 桌面端：双栏布局 -->
    <template v-else>
      <!-- 报告列表 -->
      <el-row :gutter="16">
        <!-- 左侧：历史报告列表 -->
        <el-col :xs="24" :sm="5">
          <el-card shadow="hover" class="list-card">
            <template #header>
              <div class="card-header">
                <span>历史报告</span>
                <el-tag size="small" type="info">最近30天</el-tag>
              </div>
            </template>
            <div class="report-list" v-loading="loadingList">
              <div
                v-for="item in reportList"
                :key="item.report_date"
                class="report-item"
                :class="{ active: currentReport?.report_date === item.report_date }"
                @click="selectReport(item.report_date)"
              >
                <div class="item-date">{{ item.report_date }}</div>
                <div class="item-meta">
                  <el-tag
                    :type="item.status === 'completed' ? 'success' : item.status === 'failed' ? 'danger' : 'warning'"
                    size="small"
                  >
                    {{ statusLabel(item.status) }}
                  </el-tag>
                  <span class="item-time">{{ formatTime(item.generated_at) }}</span>
                </div>
              </div>
              <el-empty
                v-if="!loadingList && reportList.length === 0"
                :description="reportListError ? reportListError : '暂无报告'"
              />
            </div>
          </el-card>
        </el-col>

        <!-- 右侧：报告详情 -->
        <el-col :xs="24" :sm="19">
          <el-card shadow="hover" class="report-card" v-loading="loadingReport">
            <template #header v-if="currentReport">
              <div class="card-header">
                <span>{{ currentReport.report_date }} 复盘报告</span>
                <el-tag :type="currentReport.status === 'completed' ? 'success' : currentReport.status === 'generating' ? 'warning' : 'danger'" size="small">
                  {{ statusLabel(currentReport.status) }}
                </el-tag>
              </div>
            </template>

            <!-- AI研报内容 -->
            <div v-if="currentReport?.ai_report && currentReport.status === 'completed'" class="report-content" v-html="renderMarkdown(currentReport.ai_report)" />

            <!-- 生成中提示 -->
            <div v-else-if="currentReport?.status === 'generating'" class="report-placeholder">
              <el-icon class="is-loading" :size="32"><Loading /></el-icon>
              <p style="margin-top:12px;color:#409eff;font-weight:500;">报告生成中，请稍候...</p>
              <p style="color:#909399;font-size:13px;margin-top:4px;">AI推理通常需要1-3分钟</p>
              <el-button type="primary" size="small" style="margin-top:12px;" @click="refreshCurrent" :loading="loading">刷新查看进度</el-button>
            </div>

            <!-- 生成失败提示 -->
            <div v-else-if="currentReport?.status === 'failed'" class="report-placeholder">
              <el-icon :size="32"><WarningFilled /></el-icon>
              <p style="color:#f56c6c;margin-top:12px;font-weight:500;">报告生成失败</p>
              <p style="color:#909399;font-size:13px;margin-top:8px;text-align:center;max-width:400px;">{{ currentReport.error_msg || '未知错误' }}</p>
              <el-button v-if="authStore.isAdmin" type="warning" size="small" style="margin-top:12px;" @click="handleGenerate">重新生成</el-button>
            </div>

            <!-- 加载中提示 -->
            <div v-else-if="loadingReport" class="report-placeholder">
              <el-icon class="is-loading" :size="32"><Loading /></el-icon>
              <p>正在加载报告内容...</p>
            </div>

            <!-- 空状态 -->
            <div v-else class="report-placeholder">
              <el-empty description="暂无报告数据">
                <template #description>
                  <p style="color:#909399;font-size:13px;margin-top:8px;text-align:center;line-height:1.6;">
                     系统定时生成复盘报告，当前暂无数据。<br />
                    <span v-if="authStore.isAdmin">点击上方「生成当日报告」手动触发</span>
                    <span v-else>请联系管理员生成</span>
                  </p>
                </template>
              </el-empty>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<script setup>
defineOptions({ name: 'DailyReport' })
import { ref, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'
import { Refresh, Notebook, Loading, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dailyReportApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'

const authStore = useAuthStore()

// 本地时间格式化为 YYYY-MM-DD（避免 toISOString 在 UTC+8 凌晨返回昨天）
function getTodayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 移动端检测
const isMobile = ref(false)
function _updateIsMobile() {
  isMobile.value = window.innerWidth <= 768
}

const loading = ref(false)
const generating = ref(false)
const selectedDate = ref('')

// 报告列表缓存：打开即看到最近30天列表 + 后台静默刷新
const reportListCache = useCachedFetch({
  key: () => 'report:list:30d',
  fetcher: () => dailyReportApi.list(30),
  tier: CACHE_TIERS.REPORT,
  onSuccess: (res) => Array.isArray(res) ? res : (res?.items || res?.reports || []),
  onError: (e) => {
    const status = e?.response?.status
    if (status === 401 || status === 403) {
      reportListError.value = '未登录或会话已过期'
    } else if (status >= 500) {
      reportListError.value = '后端服务异常'
    } else {
      reportListError.value = '加载失败，请稍后重试'
    }
  },
})

const reportListError = ref('')

// 按日期缓存报告详情 - dynamic key：切回已看过的日期立即显示
const reportDetailCache = useCachedFetch({
  key: () => `report:detail:${selectedDate.value || 'latest'}`,
  fetcher: () => {
    const d = selectedDate.value
    return d ? dailyReportApi.getByDate(d) : dailyReportApi.getLatest()
  },
  tier: CACHE_TIERS.REPORT,
  immediate: false,
})

const reportList = computed(() => Array.isArray(reportListCache.data.value) ? reportListCache.data.value : [])
const loadingList = computed(() => reportListCache.loading.value)

// 报告详情：由 reportDetailCache 直接提供，currentReport 同步其值
const currentReport = ref(null)
const loadingReport = ref(false)

// 工具函数
function statusLabel(status) {
  return { completed: '已完成', generating: '生成中', failed: '失败' }[status] || status
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

function formatDateTab(dateStr) {
  if (!dateStr) return ''
  const [y, m, d] = dateStr.split('-')
  const months = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
  return `${months[parseInt(m, 10) - 1] || m}${parseInt(d, 10)}日`
}

function extractWordCount(text) {
  if (!text) return 0
  const cleaned = text.replace(/[#*`>\-\[\]()]/g, '').replace(/\s+/g, '')
  return cleaned.length > 999 ? `${(cleaned.length / 1000).toFixed(1)}k` : cleaned.length
}

function extractSectionCount(text) {
  if (!text) return 0
  const matches = text.match(/^#{1,3}\s+/gm)
  return matches ? matches.length : 0
}

function disableFutureDate(date) {
  return date.getTime() > Date.now()
}

// 移动端日期选择器：只允许选择有报告的日期；列表为空时回退到只禁用未来日期
function disableMobileDate(d) {
  if (disableFutureDate(d)) return true
  if (!reportList.value || reportList.value.length === 0) return false
  const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return !reportList.value.some(item => item.report_date === dateStr)
}



function renderMarkdown(text) {
  if (!text) return ''
  marked.setOptions({
    breaks: true,
    gfm: true,
  })
  let rawHtml = marked.parse(text)
  // 表格包裹 div，方便手机端横向滚动
  rawHtml = rawHtml.replace(/<table([^>]*)>([\s\S]*?)<\/table>/g, '<div class="table-wrapper"><table$1>$2</table></div>')
  return `<div class="md-body">${sanitizeHtml(rawHtml)}</div>`
}

// 选中报告时触发缓存 fetch
async function loadReportByDate(date) {
  const d = date || selectedDate.value
  if (!d) {
    // 没选日期 → 加载最新
    selectedDate.value = ''
    await loadLatest()
    return
  }
  selectedDate.value = d
  loadingReport.value = true
  try {
    const r = await reportDetailCache.refresh()
    if (!r) {
      currentReport.value = null
      ElMessage.warning(`${d} 暂无报告`)
    } else {
      currentReport.value = r
    }
  } catch (e) {
    if (e.response?.status === 404) {
      currentReport.value = null
      ElMessage.warning(`${d} 暂无报告`)
    } else {
      ElMessage.error('加载报告失败')
    }
  } finally {
    loadingReport.value = false
  }
}

async function loadLatest() {
  loadingReport.value = true
  try {
    // 直接调用 getLatest 走缓存：key=report:detail:latest
    const r = await reportDetailCache.refresh()
    if (r && r.report_date) {
      currentReport.value = r
      selectedDate.value = r.report_date
    }
  } catch (e) {
    console.error('加载最新报告失败:', e)
  } finally {
    loadingReport.value = false
  }
}

function selectReport(date) {
  selectedDate.value = date
  loadReportByDate(date)
}

function refreshCurrent() {
  if (selectedDate.value) {
    // 强制刷新当前日期（清缓存再拉）
    reportDetailCache.clear()
    loadReportByDate(selectedDate.value)
  } else {
    reportDetailCache.clear()
    loadLatest()
  }
}

async function handleGenerate() {
  const today = getTodayStr()

  // 任何已存在的相同日期报告都提示覆盖（不仅限 completed）
  const exists = currentReport.value?.report_date === today
  try {
    await ElMessageBox.confirm(
      `${exists ? `${today} 的复盘报告已存在，确定要重新生成并覆盖吗？` : `确认生成 ${today} 的复盘报告？此过程可能需要1-3分钟。`}`,
      exists ? '确认覆盖' : '确认生成',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  generating.value = true
  const loadingMsg = ElMessage({ message: '正在生成复盘报告，请稍候...', duration: 0, type: 'info' })
  try {
    const result = await dailyReportApi.generate(today)
    loadingMsg.close()
    // 检查后端返回的报告状态
    if (result?.report?.status === 'failed') {
      const errMsg = result.report.error_msg || '报告生成失败'
      ElMessage.error(`报告生成失败: ${errMsg}`)
    } else {
      ElMessage.success(exists ? '报告已重新生成并覆盖' : '报告生成成功')
    }
    // 重新拉取列表与详情（覆盖缓存）
    await reportListCache.refresh()
    selectedDate.value = today
    reportDetailCache.clear()
    await loadReportByDate(today)
  } catch (e) {
    loadingMsg.close()
    const detail = e.response?.data?.detail || e.message || '报告生成失败'
    // 超时错误：后端可能仍在执行，30 秒后自动刷新一次（更接近实际生成时间）
    if (e.code === 'ECONNABORTED' || detail.includes('超时')) {
      ElMessage.warning('请求超时，但后端可能仍在生成中，请稍后刷新页面查看结果')
      setTimeout(async () => {
        await reportListCache.refresh()
        if (selectedDate.value === today) {
          await loadReportByDate(today)
        }
      }, 30000)
    } else {
      ElMessage.error(`报告生成失败: ${detail}`)
      console.error('报告生成错误:', e)
      // 刷新列表以显示失败状态
      try {
        await reportListCache.refresh()
      } catch {}
    }
  } finally {
    generating.value = false
  }
}

onMounted(() => {
  _updateIsMobile()
  window.addEventListener('resize', _updateIsMobile)
  // useCachedFetch 内部已自动读缓存+后台静默刷新
  // 仅需拉详情（最新报告）
  loadLatest()
})

// keep-alive 切回时同步 isMobile
onActivated(() => {
  _updateIsMobile()
})

onDeactivated(() => {
  // keep-alive 切走时不移除监听器
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', _updateIsMobile)
})
</script>

<style scoped>
.report-page { position: relative; height: 100%; overflow-y: auto; padding: 12px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.header-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.page-title { display: flex; align-items: center; gap: 8px; color: #303133; font-size: 20px; margin: 0; white-space: nowrap; }
.disclaimer-inline { font-size: 12px; color: #909399; line-height: 1.4; }
.header-actions { display: flex; align-items: center; gap: 8px; }

.list-card, .report-card { height: calc(100vh - 160px); display: flex; flex-direction: column; }
.list-card :deep(.el-card__body), .report-card :deep(.el-card__body) { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
.card-header { display: flex; align-items: center; justify-content: space-between; font-weight: 600; }

/* 报告列表 */
.report-list { overflow-y: auto; flex: 1; }
.report-item {
  padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px;
  transition: all 0.2s; border: 1px solid transparent;
}
.report-item:hover { background: #f5f7fa; }
.report-item.active { background: #ecf5ff; border-color: #409eff; }
.item-date { font-weight: 600; color: #303133; margin-bottom: 4px; }
.item-meta { display: flex; align-items: center; gap: 8px; }
.item-time { color: #909399; font-size: 12px; }

/* 报告内容 */
.report-content {
  overflow-y: auto; flex: 1; padding: 16px; line-height: 1.8; color: #303133; font-size: 14px;
}
.report-content :deep(.md-body h2) { font-size: 18px; margin: 16px 0 8px; color: #1a1a2e; border-bottom: 2px solid #409eff; padding-bottom: 6px; }
.report-content :deep(.md-body h3) { font-size: 16px; margin: 14px 0 6px; color: #303133; }
.report-content :deep(.md-body h4) { font-size: 15px; margin: 12px 0 4px; color: #606266; }
.report-content :deep(.md-body strong) { color: #409eff; }
.report-content :deep(.md-body li) { margin-left: 20px; margin-bottom: 4px; list-style: disc; }
.report-content :deep(.md-body p) { margin: 8px 0; }
.report-content :deep(.table-wrapper) {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 12px 0;

  &::-webkit-scrollbar { height: 4px; }
  &::-webkit-scrollbar-thumb { background: #dcdfe6; border-radius: 2px; }
}
.report-content :deep(table),
.report-content :deep(.md-table) {
  width: 100%; border-collapse: collapse; font-size: 13px; margin: 0;
}
.report-content :deep(th) {
  padding: 8px 12px; border: 1px solid #d0d7de; background: #f0f5ff; font-weight: 600; color: #303133; text-align: left;
}
.report-content :deep(td) {
  padding: 8px 12px; border: 1px solid #ebeef5; background: #fafafa;
}
.report-content :deep(tr:hover td) { background: #ecf5ff; }
.report-content :deep(blockquote) {
  margin: 12px 0; padding: 10px 16px; background: #fef9e7; border-left: 4px solid #e6a817; border-radius: 4px; color: #6b5900; font-size: 14px;
}
.report-content :deep(hr) {
  border: none; border-top: 1px solid #e4e7ed; margin: 16px 0;
}
.report-content :deep(code) {
  background: #f5f7fa; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #c41d7f;
}
.report-content :deep(pre) {
  background: #f5f7fa; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 12px 0; font-size: 13px;
}
.report-content :deep(pre code) {
  background: none; padding: 0; color: inherit;
}
.report-content :deep(ul), .report-content :deep(ol) {
  margin: 8px 0; padding-left: 24px;
}
.report-content :deep(li) {
  margin-bottom: 4px;
}

.report-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 300px; color: #909399; }
.report-placeholder p { margin-top: 12px; }

/* ═══════════════════════════════════════════
   移动端卡片式报告布局
   ═══════════════════════════════════════════ */

.mob-report-container {
  padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0));
}

/* 日期快速选择器卡 */
.mob-date-tabs {
  padding: 12px 0 8px !important;
  margin-bottom: 12px;
}

/* 报告头部信息卡 */
.mob-report-header {
  margin-bottom: 12px;
}

/* 统计卡片行 - 移动端紧凑间距 */
.mob-stats {
  gap: 6px;
  margin-top: 12px;
  margin-bottom: 0;
}

.mob-stats .m-stat-card {
  padding: 10px 4px;
}

/* 生成中/失败状态区域 */
.mob-generating,
.mob-failed {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--m-border);
}

/* 报告内容卡 - Markdown渲染 */
.mob-report-body {
  padding: 12px !important;
  overflow-x: visible !important;
}

.mob-md-content {
  font-size: 13px;
  line-height: 1.7;
  color: var(--m-text);
}

.mob-md-content :deep(h2) {
  font-size: 15px;
  margin: 16px 0 8px;
  padding-bottom: 6px;
  border-bottom: 2px solid var(--m-accent);
  color: var(--m-text);
  font-weight: 700;
}

.mob-md-content :deep(h3) {
  font-size: 14px;
  margin: 14px 0 6px;
  color: var(--m-text);
  font-weight: 600;
}

.mob-md-content :deep(h4) {
  font-size: 13px;
  margin: 12px 0 4px;
  color: var(--m-text2);
}

.mob-md-content :deep(p) {
  margin: 8px 0;
  line-height: 1.7;
}

.mob-md-content :deep(strong) {
  color: var(--m-accent);
  font-weight: 600;
}

.mob-md-content :deep(ul), .mob-md-content :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.mob-md-content :deep(li) {
  font-size: 13px;
  margin-bottom: 4px;
  line-height: 1.6;
}

/* Markdown表格横向滚动容器 - 不超出父元素，内部滚动 */
.mob-md-content :deep(.table-wrapper) {
  overflow-x: auto !important;
  overflow-y: hidden !important;
  -webkit-overflow-scrolling: touch;
  width: 100% !important;
  margin: 8px 0 !important;
  padding: 0 !important;
  box-sizing: border-box !important;

  &::-webkit-scrollbar { height: 3px; }
  &::-webkit-scrollbar-thumb { background: var(--m-border); border-radius: 2px; }
}

.mob-md-content :deep(.table-wrapper table),
.mob-md-content :deep(.table-wrapper .md-table) {
  width: 100% !important;
  min-width: max-content !important;
  font-size: 11px !important;
  border-collapse: collapse !important;
  margin: 0 auto !important;
  table-layout: auto !important;

  th, td {
    padding: 6px 8px !important;
    font-size: 11px !important;
    box-sizing: border-box !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
  }

  th {
    background: var(--m-surface2) !important;
    font-weight: 600 !important;
    color: var(--m-text) !important;
    border: 1px solid var(--m-border) !important;
  }

  td {
    border: 1px solid var(--m-border) !important;
  }

  th:last-child, td:last-child {
    white-space: normal !important;
    word-break: break-word !important;
  }
}

/* 直接渲染的table（无wrapper包裹时）- 同样方案 */
.mob-md-content :deep(table) {
  display: block !important;
  overflow-x: auto !important;
  -webkit-overflow-scrolling: touch;
  min-width: max-content !important;
  font-size: 11px !important;
  border-collapse: collapse !important;
  width: 100% !important;
  margin: 8px 0 !important;
  padding: 0 !important;
  box-sizing: border-box !important;
  table-layout: auto !important;

  &::-webkit-scrollbar { height: 3px; }
  &::-webkit-scrollbar-thumb { background: var(--m-border); border-radius: 2px; }

  th, td {
    padding: 6px 8px !important;
    font-size: 11px !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
  }

  th:last-child, td:last-child {
    white-space: normal !important;
    word-break: break-word !important;
  }

  th {
    background: var(--m-surface2) !important;
    font-weight: 600 !important;
    color: var(--m-text) !important;
    border: 1px solid var(--m-border) !important;
  }

  td {
    border: 1px solid var(--m-border) !important;
  }
}

.mob-md-content :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 12px;
  background: rgba(240, 180, 41, 0.08);
  border-left: 3px solid var(--m-gold);
  border-radius: 4px;
  color: var(--m-text2);
  font-size: 12px;
}

.mob-md-content :deep(code) {
  background: var(--m-surface2);
  padding: 2px 5px;
  border-radius: 3px;
  font-size: 12px;
  color: #c41d7f;
}

.mob-md-content :deep(pre) {
  background: var(--m-surface2);
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 10px 0;
  font-size: 12px;

  code {
    background: none;
    padding: 0;
    color: inherit;
  }
}

.mob-md-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--m-border);
  margin: 14px 0;
}

/* 空状态/加载中占位 */
.mob-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

/* ═══════════════════════════════════════════
   响应式：移动端页面专属覆盖
   ═══════════════════════════════════════════ */
@media (max-width: 768px) {
  .report-page { padding: 4px 8px; position: absolute !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; overflow-y: auto !important; overflow-x: visible !important; }

  /* 移动端 header 已有标题，隐藏页面内部重复标题 */
  .page-title { display: none !important; }
  .disclaimer-inline { display: none !important; }

  .page-header { flex-direction: row; align-items: center; justify-content: flex-end; gap: 4px; margin-bottom: 4px; width: 100%; }
  .header-left { display: none !important; }

  /* 桌面端按钮在移动端隐藏 */
  .desktop-only { display: none !important; }

  .header-actions.mobile-header {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: nowrap;
    gap: 2px;
    align-items: center;

    :deep(.el-date-picker) { flex: 1; min-width: 80px; max-width: 140px; }
    :deep(.el-date-editor) { border-radius: 6px !important; }
    :deep(.el-input__wrapper) { box-shadow: none !important; border: 1px solid #e0e4ea !important; padding: 0 8px !important; }
    :deep(.el-input__inner) { font-size: 12px !important; height: 30px; line-height: 30px; }

    .mobile-refresh,
    .mobile-gen-btn {
      flex-shrink: 0;
      font-size: 12px !important;
      padding: 4px 8px !important;
      min-height: 30px !important;
      line-height: 30px !important;
      height: 30px !important;
      border-radius: 6px !important;
    }

    .mobile-refresh { color: #409eff; background: rgba(64,158,255,0.06); }
    .mobile-gen-btn { color: #e6a23c; background: rgba(230,162,60,0.06); }
  }

  .list-card, .report-card { height: auto; min-height: 0; }

  /* 移动端容器背景 */
  .mob-report-container {
    background: transparent;
  }

  /* 触摸目标优化：确保所有可点击元素 ≥ 44px */
  .mob-date-tabs :deep(.m-hscroll-tabs .tab) {
    min-height: 36px;
    display: inline-flex;
    align-items: center;
    padding: 8px 16px;
    font-size: 13px;
  }

  /* el-tag 触摸优化 */
  :deep(.el-tag) {
    min-height: 24px;
    line-height: 22px;
  }

  /* m-card 间距微调 */
  .mob-report-header,
  .mob-report-body,
  .mob-placeholder {
    --m-card-radius: 12px;
  }

  /* 统计卡片触摸反馈 */
  .mob-stats .m-stat-card {
    --m-card-radius: 10px;
  }
}

@media (max-width: 480px) {
  .page-title { font-size: 15px !important; }

  .header-actions.mobile-header :deep(.el-date-picker) { min-width: 70px; max-width: 120px; }
  .header-actions.mobile-header :deep(.el-input__inner) { font-size: 11px !important; height: 28px; line-height: 28px; }
  .header-actions.mobile-header .mobile-refresh,
  .header-actions.mobile-header .mobile-gen-btn {
    font-size: 11px !important;
    padding: 3px 6px !important;
    min-height: 28px !important;
    line-height: 28px !important;
    height: 28px !important;
  }

  /* 超小屏幕：统计卡片缩小 */
  .mob-stats { gap: 4px; }
  .mob-stats .m-stat-card { padding: 8px 2px; }
  .mob-stats .m-stat-card .val { font-size: 14px; }
  .mob-stats .m-stat-card .lbl { font-size: 9px; }

  /* Markdown内容进一步缩小 */
  .mob-md-content { font-size: 12px; }
  .mob-md-content :deep(h2) { font-size: 14px; }
  .mob-md-content :deep(h3) { font-size: 13px; }
  .mob-md-content :deep(li) { font-size: 12px; }

  /* 日期标签缩小 */
  .mob-date-tabs :deep(.m-hscroll-tabs .tab) {
    padding: 6px 12px;
    font-size: 12px;
  }
}
</style>
