<template>
  <div class="chat-page">
    <!-- 移动端：会话列表遮罩层 -->
    <div v-if="isMobile && showMobileSidebar" class="mobile-overlay" @click="showMobileSidebar = false"></div>

    <!-- 左侧会话列表（桌面端）/ 弹出面板（移动端） -->
    <div class="sidebar" :class="{ collapsed: sidebarCollapsed, 'mobile-visible': isMobile && showMobileSidebar }">
      <div class="sidebar-header">
        <button class="new-chat-btn" @click="createNewSession" title="新对话">＋ 新对话</button>
        <template v-if="isMobile">
          <button class="collapse-btn" @click="showMobileSidebar = false" title="关闭">✕</button>
        </template>
        <template v-else>
          <button v-if="!sidebarCollapsed" class="collapse-btn" @click="sidebarCollapsed = true" title="收起">◂</button>
        </template>
      </div>

      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: currentSessionId === s.id }"
          @click="loadSession(s.id); if (isMobile) showMobileSidebar = false"
        >
          <div class="session-title">{{ s.title }}</div>
          <div class="session-meta">
            {{ formatDateShort(s.updated_at) }} · {{ s.message_count }}条
          </div>
          <button class="delete-session-btn" @click.stop="showMobileSidebar = false; confirmDeleteSession(s.id)" title="删除对话">
            ✕
          </button>
        </div>

        <el-empty v-if="sessions.length === 0" description="暂无对话" :image-size="40" />
      </div>
    </div>

    <!-- 展开按钮（桌面端侧边栏收起时显示） -->
    <button v-if="!isMobile && sidebarCollapsed" class="expand-btn" @click="sidebarCollapsed = false" title="展开">▸</button>

    <!-- 主聊天区域 -->
    <div class="chat-main-area m-chat-container">
    <!-- 桌面端顶部工具栏 -->
    <div class="chat-header">
      <div class="header-left">
        <h2 class="page-title">
          <span class="title-icon">🤖</span>
          AI助手
        </h2>
        <el-tag
          :type="llmEnabled ? 'success' : 'info'"
          effect="plain"
          size="small"
          round
          class="status-tag"
        >
          {{ llmEnabled ? 'Agent模式' : '规则模式' }}
        </el-tag>
        <el-tag
          v-if="quotaInfo && !quotaInfo.unlimited"
          :type="quotaInfo.remaining <= 5 ? 'danger' : 'warning'"
          effect="plain"
          size="small"
          round
          class="quota-tag"
        >
          今日剩余 {{ quotaInfo.remaining }}/{{ quotaInfo.limit }}
        </el-tag>
      </div>
      <div class="header-actions">
        <button v-if="!isMobile" class="action-btn" @click="showStats = !showStats" title="对话统计">
          📊
        </button>
        <button v-if="!isMobile" class="action-btn" @click="exportChat" :disabled="messages.length === 0" title="导出记录">
          💾
        </button>
        <button v-if="!isMobile" class="action-btn" @click="clearChat" :disabled="messages.length === 0" title="清空对话">
          🗑️
        </button>
      </div>
    </div>

    <!-- 对话统计面板 -->
    <transition name="slide-down">
      <div v-if="showStats" class="stats-panel">
        <div class="stat-item">
          <span class="stat-label">消息数</span>
          <span class="stat-value">{{ messages.length }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">提问数</span>
          <span class="stat-value">{{ userCount }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">字符数</span>
          <span class="stat-value">{{ charCount.toLocaleString() }}</span>
        </div>
      </div>
    </transition>

    <!-- 快捷分类标签 -->
    <div class="category-tabs">
      <button
        v-for="cat in categories"
        :key="cat.key"
        class="cat-tab"
        :class="{ active: activeCategory === cat.key }"
        @click="activeCategory = cat.key"
      >
        {{ cat.icon }} {{ cat.label }}
      </button>
    </div>

    <!-- 快捷问题 -->
    <transition name="slide-down">
      <div v-if="activeCategory" class="quick-questions">
        <button
          v-for="q in currentQuestions"
          :key="q"
          class="quick-q-btn"
          @click="quickAsk(q)"
        >
          {{ q }}
        </button>
      </div>
    </transition>

    <!-- 聊天消息区域 -->
    <div ref="chatContainer" class="chat-messages m-chat-msgs">
      <!-- 欢迎界面 -->
      <div v-if="messages.length === 0" class="welcome-screen">
        <div class="welcome-avatar">📊</div>
        <h3 class="welcome-title">A股智能分析助手</h3>
        <p class="welcome-desc">支持实时行情、个股诊断、板块分析、资金流向、龙虎榜、智能选股、盘中异动等 17 种分析能力</p>
        <div class="capability-grid">
          <div class="capability-item" v-for="cap in capabilities" :key="cap.label">
            <span class="cap-icon">{{ cap.icon }}</span>
            <span class="cap-label">{{ cap.label }}</span>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <template v-for="(msg, idx) in messages" :key="idx">
        <div class="message-row" :class="[msg.role, msg.role === 'user' ? 'm-chat-bubble-user' : 'm-chat-bubble-ai']">
          <div class="msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="msg-body">
            <div class="msg-info">
              <span class="msg-role">{{ msg.role === 'user' ? '你' : 'AI助手' }}</span>
              <span class="msg-time">{{ formatTime(msg.timestamp) }}</span>
            </div>
            <div class="msg-bubble" :class="msg.role">
              <!-- 用户消息 -->
              <template v-if="msg.role === 'user'">
                {{ msg.content }}
              </template>

              <!-- Agent流式消息 -->
              <template v-else-if="msg.reasoning_steps || msg.streaming_content !== undefined">
                <!-- 推理步骤（可折叠） -->
                <div v-if="msg.reasoning_steps && msg.reasoning_steps.length" class="reasoning-section">
                  <button
                    class="toggle-reasoning"
                    @click="msg.showReasoning = !msg.showReasoning"
                  >
                    {{ msg.showReasoning !== false ? '隐藏' : '显示' }}分析过程 ({{ msg.reasoning_steps.length }}步)
                    <span class="arrow" :class="{ up: msg.showReasoning !== false }">▼</span>
                  </button>
                  <transition name="expand">
                    <div v-if="msg.showReasoning !== false" class="reasoning-chain">
                      <div
                        v-for="(step, si) in msg.reasoning_steps"
                        :key="si"
                        class="reasoning-step"
                        :class="'status-' + (step.status || 'thinking')"
                      >
                        <div class="step-header">
                          <span class="step-badge">{{ step.round }}</span>
                          <span class="step-icon">
                            <template v-if="step.status === 'thinking'">🔍</template>
                            <template v-else-if="step.status === 'running' && step.running_tool">⏳ {{ step.running_tool }}</template>
                            <template v-else-if="step.status === 'done'">✅</template>
                            <template v-else>🔍</template>
                          </span>
                          <span class="step-tools">{{ (step.tools_called || []).join(', ') }}</span>
                        </div>
                      </div>
                    </div>
                  </transition>
                </div>

                <!-- 流式回答（v-for 内使用 idx，msgIdx 在 sendWithAgent 内闭包捕获） -->
                <div v-if="msg.streaming_content" class="answer" v-html="renderedHtml[idx] || msg.streaming_content"></div>

                <!-- 错误信息（报告生成失败时显示） -->
                <div v-if="msg.content && msg.finished" class="answer error-content">{{ msg.content }}</div>

                <!-- 分析中指示器（工具调用期间显示） -->
                <div v-if="!msg.streaming_content && !msg.finished" class="thinking-indicator">
                  <span class="thinking-dots">
                    <span>.</span><span>.</span><span>.</span>
                  </span>
                  Agent正在分析
                </div>
              </template>

              <!-- 工具结果（旧版） -->
              <template v-else-if="msg.tool_results && msg.tool_results.length">
                <details class="tool-details" v-for="(tr, ti) in msg.tool_results" :key="ti">
                  <summary>📊 {{ tr.name }} 数据</summary>
                  <pre>{{ tr.content }}</pre>
                </details>
              </template>

              <!-- 普通回答 -->
              <div v-else class="answer" v-html="formatMarkdown(msg.content)"></div>
            </div>

            <!-- 消息操作栏 -->
            <div class="msg-actions">
              <button
                class="copy-btn"
                @click="copyMessage(msg)"
                :title="'复制' + (msg.role === 'user' ? '' : '回答')"
              >
                📋 {{ copiedMsgIdx === idx ? '已复制' : '复制' }}
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- 加载指示器（仅规则模式） -->
      <div v-if="chatLoading" class="message-row assistant">
        <div class="msg-avatar">🤖</div>
        <div class="msg-body">
          <div class="msg-bubble assistant loading-bubble">
            <span class="loading-text">{{ loadingText }}</span>
            <span class="loading-dots"><span>.</span><span>.</span><span>.</span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <div class="input-wrapper m-chat-input">
        <button v-if="isMobile" class="sidebar-toggle-btn" @click="showMobileSidebar = !showMobileSidebar" :title="showMobileSidebar ? '关闭会话列表' : '查看聊天记录'">
          📋
        </button>
        <textarea
          ref="inputRef"
          v-model="inputText"
          placeholder="输入你的问题... (Shift+Enter换行)"
          rows="1"
          @keydown.enter.exact.prevent="sendMessage"
          :disabled="chatLoading || isStreaming"
          @input="autoResize"
          @focus="handleInputFocus"
          @blur="handleInputBlur"
        ></textarea>
        <button
          v-if="isStreaming"
          class="send-btn stop-btn"
          @click="abortRequest"
        >
          ⏹ 停止
        </button>
        <button
          v-else
          class="send-btn"
          @click="sendMessage"
          :disabled="!inputText.trim() || chatLoading"
        >
          发送
        </button>
      </div>
    </div>
    </div>  <!-- chat-main-area -->
  </div>
</template>

<script setup>
defineOptions({ name: 'ChatAssistant' })
import { ref, nextTick, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import { useAuthStore } from '../stores/auth'
import { chatApi } from '@/api'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

const authStore = useAuthStore()

// 移动端键盘处理：CSS 已通过 --vh 变量自动适配，JS 只需处理滚动
function handleInputFocus() {
  if (!isMobile.value) return
  
  // 延迟滚动到底部，让输入框可见
  setTimeout(() => {
    scrollToBottom()
    
    // 确保输入框在可视区域内
    if (inputRef.value) {
      inputRef.value.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, 300)
}

function handleInputBlur() {
  // 键盘收起时，CSS 会自动恢复高度
}

const messages = ref([])
const inputText = ref('')
const chatLoading = ref(false)  // 规则模式加载状态
const isStreaming = ref(false)   // Agent流式响应状态
const loadingText = ref('正在分析...')
const showStats = ref(false)
const llmEnabled = ref(false)
const llmConnected = ref(false)
const chatContainer = ref(null)
const inputRef = ref(null)
const copiedMsgIdx = ref(-1)
const activeCategory = ref('market')
let abortController = null

// ===== 会话管理 =====
const sidebarCollapsed = ref(false)
const currentSessionId = ref(null)

// 移动端检测 + 侧边栏切换
const isMobile = ref(false)
const showMobileSidebar = ref(false)
function _updateIsMobile() {
  const wasMobile = isMobile.value
  isMobile.value = window.innerWidth <= 768
  if (!wasMobile && isMobile.value) {
    showMobileSidebar.value = false
  }
}
window.addEventListener('resize', _updateIsMobile)
window.addEventListener('toggle-chat-sidebar', () => {
  showMobileSidebar.value = !showMobileSidebar.value
})
onMounted(async () => {
  _updateIsMobile()
  await refreshSessions()
})

async function api(url, method = 'GET', body = null) {
  const token = localStorage.getItem('gp_access_token')
  return axios({
    url: `/api/v1${url}`,
    method,
    data: body,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    signal: abortController?.signal,
  }).then((r) => r.data)
}

// 会话列表 - 1分钟缓存（用户期望发完消息立即看到新会话）
const sessionsCache = useCachedFetch({
  key: () => `chat:sessions:user${authStore.user?.id || 0}`,
  fetcher: () => api('/chat/sessions?limit=50'),
  tier: { storageTTL: 60 * 1000, refreshInterval: 60 * 1000 },
  onSuccess: (data) => data?.sessions || [],
})

const sessions = computed(() => sessionsCache.data.value || [])

// 刷新会话列表（发送消息/创建/删除后用）
async function refreshSessions() {
  sessionsCache.clear()
  await sessionsCache.refresh()
}

function createNewSession() {
  currentSessionId.value = null
  messages.value = []
  showMobileSidebar.value = false
  ElMessage.success('已创建新对话')
  refreshSessions()
}

async function loadSession(sessionId) {
  if (currentSessionId.value === sessionId) return
  currentSessionId.value = sessionId
  try {
    const data = await api(`/chat/sessions/${sessionId}`)
    messages.value = (data.messages || []).map(m => ({
      role: m.role,
      content: m.content,
      timestamp: new Date(m.created_at).getTime(),
    }))
    scrollToBottom()
  } catch (e) {
    console.error('加载会话失败:', e)
  }
}

async function confirmDeleteSession(sessionId) {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  try {
    await api(`/chat/sessions/${sessionId}`, 'DELETE')
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
    }
    ElMessage.success('对话已删除')
    refreshSessions()
  } catch (e) {
    console.error('删除对话失败:', e)
    ElMessage.error('删除失败')
  }
}

function formatDateShort(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

// ===== 快捷分类 =====
const categories = [
  { key: 'market', icon: '📈', label: '大盘' },
  { key: 'stock', icon: '🔍', label: '个股' },
  { key: 'strategy', icon: '🤖', label: '选股' },
  { key: 'news', icon: '💡', label: '资讯' },
  { key: 'dragon', icon: '🐉', label: '龙虎榜' },
]

const categoryQuestions = {
  market: ['今天大盘走势如何？', '上证指数技术分析', '市场情绪怎么样？'],
  stock: ['贵州茅台怎么样？', '宁德时代估值分析', '比亚迪技术面如何？'],
  strategy: ['帮我选低估值的股票', '近期有哪些强势股？', '推荐成长型板块'],
  news: ['人工智能板块最新消息', '今天有什么重要财经新闻？', '政策利好哪些行业？'],
  dragon: ['今天龙虎榜有谁？', '最近游资在买什么？', '机构买入最多的股票'],
}

const capabilities = [
  { icon: '📊', label: '实时行情' },
  { icon: '📈', label: '技术分析' },
  { icon: '🎯', label: '智能选股' },
  { icon: '🐉', label: '龙虎榜' },
  { icon: '💰', label: '资金流向' },
  { icon: '📰', label: '资讯分析' },
]

const currentQuestions = computed(() => categoryQuestions[activeCategory.value] || [])
const userCount = computed(() => messages.value.filter(m => m.role === 'user').length)
const charCount = computed(() => messages.value.reduce((sum, m) => sum + (m.content?.length || 0) + (m.streaming_content?.length || 0), 0))


// 前端最后一道防线：过滤思维链泄露（保守策略，避免误删正常内容）
function stripThinking(text) {
  if (!text || typeof text !== 'string') return ''
  
  let processed = text
  
  // 移除 XML 思维标签
  for (const tag of ['thinking', 'thought', 'reasoning', 'analysis']) {
    const re = new RegExp(`\\s*<${tag}>.*?</${tag}>\\s*`, 'gis')
    processed = processed.replace(re, '')
  }
  
  // 移除英文思维链块（Here's a thinking process: ... / Thinking Process: ...）
  processed = processed.replace(
    /(?:^|\n)\s*(?:Here'?s?\s+(?:a|the)\s+thinking\s+process|Thinking\s*Process|Thought\s*Process)[:\s]*\r?\n[\s\S]*?(?=\n(?:##|# |\*\*|📊|🔥|📈|📋|⚠️|---|\d+\.\s)|$)/i,
    '\n'
  )
  
  // 找到最后一个思维链标记行，只保留其后的内容（大小写不敏感）
  const keywords = [
    '识别意图', '设定角色', '确定回复', '遵守约束', '草拟',
    '最终输出', '思考过程', '分析步骤', '不需要调用', '直接生成',
    '检查约束', '输出构建', '草拟回复', '回复结构',
    '决定行动', '选择工具', '构建回复', '修正',
    '数据分析：', '回答结构规划', '约束检查', '草稿内容构建',
    '开始生成回复', '现在需要根据返回的数据进行分析',
    "here's a thinking process", 'understand user role', 'analyze constraints',
    'process candidate data', 'calculate strategy parameters', 'draft content',
    'output generation', 'self-correction', 'call to action',
  ]
  
  const lines = processed.split('\n')
  let lastThoughtIdx = -1
  for (let i = 0; i < lines.length; i++) {
    const lowerLine = lines[i].toLowerCase()
    if (keywords.some(kw => lowerLine.includes(kw))) {
      lastThoughtIdx = i
    }
  }
  if (lastThoughtIdx >= 0) {
    processed = lines.slice(lastThoughtIdx + 1).join('\n').trim()
  }
  
  return processed
}

function formatMarkdown(text) {
  // 先过滤思维链
  text = stripThinking(text)
  
  if (!text || typeof text !== 'string') return ''
  
  let processed = text
  
  // 修复 LLM 输出的不规范 Markdown：###标题 -> ### 标题（补空格）
  processed = processed.replace(/(^|\n)(#{1,6})(\S)/g, '$1$2 $3')
  
  // 移除标题内容中的前导 # 符号（LLM 可能输出 ## # 标题）
  processed = processed.replace(/^## # /gm, '## ')
  processed = processed.replace(/^### # /gm, '### ')
  
  // 流式输出时处理不完整的 markdown：
  const openCodeBlocks = (processed.match(/```/g) || []).length
  if (openCodeBlocks % 2 === 1) {
    processed += '\n```\n'
  }
  
  const inlineCodes = (processed.match(/`/g) || []).length
  if (inlineCodes % 2 === 1) {
    processed += '`'
  }
  
  try {
    // marked v18+ 可能返回 Promise，需要处理两种情况
    const result = marked.parse(processed, { async: false })
    // 如果是 Promise（v18+），等待解析完成
    if (result && typeof result.then === 'function') {
      return '<p>加载中...</p>' // 流式输出时先显示占位
    }
    let html = result || ''
    // 移除标题内容中前导的 # 符号（LLM 输出 ## # 标题时 marked 会渲染为 <h2># 标题</h2>）
    html = html.replace(/(<h[1-6]>)(#+)\s*/g, '$1')
    return sanitizeHtml(html)
  } catch (e) {
    console.warn('Markdown parse error:', e)
    return `<pre style="white-space:pre-wrap;">${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`
  }
}

// 异步版本，用于最终渲染
async function formatMarkdownAsync(text) {
  // 先过滤思维链
  text = stripThinking(text)
  
  if (!text || typeof text !== 'string') return ''
  
  let processed = text
  
  // 修复 LLM 输出的不规范 Markdown：###标题 -> ### 标题（补空格）
  processed = processed.replace(/(^|\n)(#{1,6})(\S)/g, '$1$2 $3')
  
  try {
    const result = await marked.parse(processed)
    let html = result || ''
    // 移除标题前显示的 # 符号（清理 LLM 可能在标题内容中重复输出的 #）
    html = html.replace(/<h([1-6])>(?:&num;?#?\s*)*(.*?)<\/h\1>/g, (match, level, title) => {
      return `<h${level}>${title}</h${level}>`
    })
    return sanitizeHtml(html)
  } catch (e) {
    console.warn('Markdown parse error:', e)
    return `<pre style="white-space:pre-wrap;">${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`
  }
}

// 为每个消息维护渲染后的 HTML（解决 v-html + async marked 的问题）
const renderedHtml = ref({})

async function updateRenderedHtml(msgIdx, text) {
  if (!text || typeof text !== 'string') return
  const html = await formatMarkdownAsync(text)
  renderedHtml.value = { ...renderedHtml.value, [msgIdx]: html }
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

// LLM 配置缓存（1分钟）
const llmConfigCache = useCachedFetch({
  key: () => 'chat:llm-config',
  fetcher: () => chatApi.getConfig(),
  tier: CACHE_TIERS.USER,
})

// 配额信息缓存（1分钟）
const quotaCache = useCachedFetch({
  key: () => `chat:quota:user${authStore.user?.id || 0}`,
  fetcher: async ({ signal } = {}) => {
    const token = localStorage.getItem('gp_access_token')
    const resp = await fetch('/api/v1/chat/quota', {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    })
    if (!resp.ok) return null
    return resp.json()
  },
  tier: CACHE_TIERS.USER,
})

const quotaInfo = computed(() => quotaCache.data.value || null)

async function checkLlmStatus() {
  // 强制刷新配置（设置保存后立即生效）
  llmConfigCache.clear()
  const data = await llmConfigCache.refresh()
  if (data) {
    llmEnabled.value = !!data.enabled
    llmConnected.value = llmEnabled.value
  }
}

async function fetchQuota() {
  await quotaCache.refresh()
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

// 自动调整textarea高度
function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

// 复制消息
function copyMessage(msg) {
  const idx = messages.value.indexOf(msg)
  const text = msg.role === 'user' ? msg.content : (msg.streaming_content || msg.content || '')
  navigator.clipboard.writeText(text).then(() => {
    copiedMsgIdx.value = idx
    setTimeout(() => { copiedMsgIdx.value = -1 }, 2000)
  })
}

// 清空对话
function clearChat() {
  messages.value = []
  showStats.value = false
}

// 导出聊天记录
function exportChat() {
  const lines = messages.value.map(m => {
    const role = m.role === 'user' ? '[你]' : '[AI]'
    const time = m.timestamp ? new Date(m.timestamp).toLocaleString('zh-CN') : ''
    const content = m.role === 'user' ? m.content : (m.streaming_content || m.content || '')
    return `${role} ${time}\n${content}\n`
  })
  const blob = new Blob([lines.join('\n---\n\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `AI助手对话_${new Date().toLocaleDateString('zh-CN').replace(/\//g, '-')}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

function quickAsk(text) {
  inputText.value = text
  sendMessage()
}

async function sendMessage() {
  if (!inputText.value.trim() || chatLoading.value || isStreaming.value) return

  // 检查AI对话配额（LLM启用时）
  if (llmEnabled.value) {
    await fetchQuota()
    if (quotaInfo.value && !quotaInfo.value.unlimited && quotaInfo.value.remaining <= 0) {
      ElMessage.warning('今日AI对话次数已用完，请明日再试或联系管理员提升额度')
      return
    }
  }

  const question = inputText.value.trim()

  await checkLlmStatus()

  messages.value.push({ role: 'user', content: question, timestamp: Date.now() })
  inputText.value = ''
  nextTick(() => {
    if (inputRef.value) inputRef.value.style.height = 'auto'
  })

  const history = messages.value
    .filter(m => {
      if (m.role === 'user') return true
      // AI消息：保留有实际回答内容的（排除纯推理步骤占位符）
      if (m.role === 'assistant') {
        return !!(m.content || m.streaming_content)
      }
      return false
    })
    .map(m => ({ role: m.role, content: m.content || m.streaming_content }))

  // 保留最近10轮对话（20条消息）
  const recentHistory = history.slice(-20)

  if (llmEnabled.value) {
    isStreaming.value = true
    scrollToBottom()
    try {
      await sendWithAgent(question, history)
    } finally {
      isStreaming.value = false
    }
  } else {
    chatLoading.value = true
    loadingText.value = '正在分析...'
    scrollToBottom()
    try {
      // 先调用 /chat/completions 保存会话（即使LLM未启用也会保存）
      const token = localStorage.getItem('gp_access_token')
      await fetch('/api/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ messages: recentHistory, stream: false, session_id: currentSessionId.value }),
      }).catch(() => {}) // 忽略错误，继续规则模式

      await sendWithRules(question)
    } finally {
      chatLoading.value = false
    }
  }

  refreshSessions()
  fetchQuota()

  scrollToBottom()
}

async function sendWithAgent(question, history) {
  const thinkingMsg = {
    role: 'assistant',
    content: '',
    reasoning_steps: [],
    streaming_content: '',
    showReasoning: false,
    timestamp: Date.now(),
    finished: false,
  }
  messages.value.push(thinkingMsg)

  const msgIdx = messages.value.length - 1

  let lastUpdate = 0
  function updateMsg(force = false) {
    const now = Date.now()
    if (!force && now - lastUpdate < 20) return
    lastUpdate = now
    // 只保留工具运行状态的步骤，隐藏纯思考内容
    const toolSteps = (thinkingMsg.reasoning_steps || []).filter(s =>
      s.status === 'running' || s.status === 'done'
    )
    const msgCopy = {
      ...thinkingMsg,
      reasoning_steps: toolSteps,
    }
    messages.value.splice(msgIdx, 1, msgCopy)
  }

  abortController = new AbortController()

  try {
    const token = localStorage.getItem('gp_access_token')
    const resp = await fetch('/api/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ messages: history.slice(-20), stream: true, session_id: currentSessionId.value }),
      signal: abortController.signal,
    })

    if (!resp.ok) {
      let errorMsg = `HTTP ${resp.status}`
      try {
        const errData = await resp.json()
        errorMsg = errData.error || errData.detail || errorMsg
        if (errData.config) {
          errorMsg += `\n\n当前配置: enabled=${errData.config.enabled}, model='${errData.config.model}', url=${errData.config.base_url}`
        }
      } catch {}
      throw new Error(errorMsg)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let lastActivity = Date.now()
    const TIMEOUT_MS = 300000 // 5分钟超时（LLM生成报告可能很慢）

    while (true) {
      // 检查是否长时间没有数据
      if (Date.now() - lastActivity > TIMEOUT_MS) {
        throw new Error('响应超时，LM Studio 可能处理时间过长')
      }

      const { done, value } = await reader.read()
      if (done) break

      lastActivity = Date.now()
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const dataStr = line.slice(6).trim()
        if (!dataStr || dataStr === '[DONE]') continue

        try {
          const event = JSON.parse(dataStr)
          if (event.type === 'final_chunk' && event.content) {
            // 流式内容逐字显示：先追加内容，更新DOM，然后短暂延迟
            thinkingMsg.streaming_content += event.content
            updateMsg(true)
            scrollToBottom()
            // 异步渲染 Markdown（后台执行，不阻塞流式输出）
            updateRenderedHtml(msgIdx, thinkingMsg.streaming_content)
            // 确保DOM有时间渲染，模拟打字效果
            await new Promise(r => setTimeout(r, 16))
          } else if (event.type === 'session_info') {
            // 更新当前会话ID（新对话时）
            if (event.session_id && !currentSessionId.value) {
              currentSessionId.value = event.session_id
            }
          } else {
            handleSSEEvent(event, thinkingMsg)
            updateMsg(true)
          }
        } catch (e) {}
      }
    }

    // 处理剩余缓冲区
    if (buffer.startsWith('data: ')) {
      try {
        const event = JSON.parse(buffer.slice(6).trim())
        handleSSEEvent(event, thinkingMsg)
        updateMsg(true)
      } catch (e) {}
    }

    // 正常结束，强制同步最终状态到 Vue（final_end 可能被节流跳过）
    if (!thinkingMsg.finished) {
      thinkingMsg.finished = true
    }
    // 确保最终的 Markdown 被正确渲染
    if (thinkingMsg.streaming_content) {
      await updateRenderedHtml(msgIdx, thinkingMsg.streaming_content)
    }
    updateMsg(true)

  } catch (err) {
    if (err.name === 'AbortError') {
      messages.value[msgIdx].content = '⚠️ 请求已取消'
      updateMsg(true)
      return
    }
    console.error('[Chat] Agent error:', err.message)
    
    // 如果已经有部分内容，保留它并标记完成
    if (thinkingMsg.streaming_content || thinkingMsg.reasoning_steps?.length) {
      thinkingMsg.finished = true
      if (!thinkingMsg.content && !thinkingMsg.streaming_content) {
        thinkingMsg.content = `⚠️ ${err.message}\n\n分析可能不完整，请重试。`
      } else {
        // 在已有内容后追加错误提示
        const existingContent = thinkingMsg.streaming_content || ''
        if (existingContent && !thinkingMsg.finished) {
          thinkingMsg.content = existingContent + `\n\n⚠️ ${err.message}`
          thinkingMsg.streaming_content = undefined
        }
      }
      updateMsg(true)
    } else if (messages.value[msgIdx] === thinkingMsg) {
      // 完全没有内容，替换为错误消息
      messages.value.splice(msgIdx, 1)
      
      let detailMsg = `⚠️ ${err.message}`
      if (err.message.includes('未启用')) {
        detailMsg += '\n\n请在上方设置面板中启用 AI 助手'
      } else if (err.message.includes('连接') || err.message.includes('localhost')) {
        detailMsg += '\n\n请确认 LM Studio 已启动并正在监听端口 1234'
      } else if (err.message.includes('超时')) {
        detailMsg += '\n\n模型可能过大或服务器负载过高，尝试使用更小的模型'
      } else if (err.message.includes('已用完') || err.message.includes('QUOTA')) {
        detailMsg = `⚠️ 今日AI对话次数已用完\n\n请明日再试，或联系管理员提升额度`
      }
      
      messages.value.push({
        role: 'assistant',
        content: detailMsg,
        timestamp: Date.now(),
      })
    }
  } finally {
    abortController = null
  }

  scrollToBottom()
}

function abortRequest() {
  if (abortController) {
    abortController.abort()
    isStreaming.value = false
    // 立即更新当前消息状态，停止"Agent正在分析..."的显示
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg && lastMsg.role === 'assistant') {
      lastMsg.finished = true
      if (!lastMsg.streaming_content && !lastMsg.content) {
        lastMsg.content = '⚠️ 已停止分析'
      } else if (lastMsg.streaming_content) {
        lastMsg.content = lastMsg.streaming_content + '\n\n⚠️ 已停止，内容可能不完整'
        lastMsg.streaming_content = undefined
      }
      // 触发响应式更新
      messages.value.splice(messages.value.length - 1, 1, { ...lastMsg })
    }
  }
}

// 组件卸载时中止进行中的 SSE 流
onBeforeUnmount(() => {
  if (abortController) {
    abortController.abort()
  }
  window.removeEventListener('resize', _updateIsMobile)
})

function handleSSEEvent(event, thinkingMsg) {
  switch (event.type) {
    case 'thinking':
      thinkingMsg.reasoning_steps.push({
        round: event.round || thinkingMsg.reasoning_steps.length + 1,
        tools_called: event.tools || [],
        model_thought: event.thought || '',
        status: 'thinking',
      })
      break
    case 'tool_running':
      if (thinkingMsg.reasoning_steps.length) {
        const lastStep = thinkingMsg.reasoning_steps[thinkingMsg.reasoning_steps.length - 1]
        lastStep.status = 'running'
        lastStep.running_tool = event.tool
      }
      break
    case 'tool_result':
      if (thinkingMsg.reasoning_steps.length) {
        const lastStep = thinkingMsg.reasoning_steps[thinkingMsg.reasoning_steps.length - 1]
        lastStep.status = 'done'
        lastStep.running_tool = null
      }
      break
    case 'final_start':
      thinkingMsg.streaming_content = ''
      break
    case 'final_chunk':
      // final_chunk已在主循环中直接处理（带延迟），此处保留兼容
      if (event.content && !thinkingMsg.streaming_content?.includes(event.content)) {
        thinkingMsg.streaming_content = (thinkingMsg.streaming_content || '') + event.content
        updateMsg(true)
        scrollToBottom()
      }
      break
    case 'final_end':
      thinkingMsg.finished = true
      break
    case 'error':
      thinkingMsg.content = `⚠️ ${event.content || '分析出错'}`
      thinkingMsg.finished = true
      thinkingMsg.streaming_content = undefined
      break
  }
}

async function sendWithAgentNonStream(question, history) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 180000)

  try {
    const token = localStorage.getItem('gp_access_token')
    const resp = await fetch('/api/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ messages: history, stream: false }),
      signal: controller.signal,
    })

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

    const data = await resp.json()

    if (data.reasoning_steps && data.reasoning_steps.length) {
      messages.value.push({
        role: 'assistant',
        content: '',
        reasoning_steps: data.reasoning_steps,
        tools_used: data.tools_used || [],
        showReasoning: true,
        timestamp: Date.now(),
      })
    }

    messages.value.push({
      role: 'assistant',
      content: data.content || '分析完成。',
      timestamp: Date.now(),
    })
  } finally {
    clearTimeout(timeoutId)
  }
}

async function sendWithRules(question) {
  try {
    const controller = new AbortController()
    const token = localStorage.getItem('gp_access_token')
    const resp = await fetch('/api/v1/nlp/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ message: question }),
      signal: controller.signal,
    })

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

    const data = await resp.json()
    let answer = ''

    if (data.data && typeof data.data === 'object') {
      const stockData = data.data.stock_data || {}
      const diagnosis = data.data.diagnosis || {}

      if (Object.keys(stockData).length) {
        answer += `📊 ${stockData.name}(${stockData.code})\n`
        answer += `现价: ${stockData.price} | 涨跌: ${stockData.change_pct}\n\n`
      }

      if (diagnosis.summary) {
        answer += diagnosis.summary
      } else if (Object.keys(diagnosis).length) {
        for (const [k, v] of Object.entries(diagnosis)) {
          if (typeof v === 'object') {
            answer += `**${k}:**\n`
            for (const [sk, sv] of Object.entries(v)) {
              answer += `- ${sk}: ${sv}\n`
            }
          } else {
            answer += `**${k}:** ${v}\n`
          }
        }
      }
    } else if (data.raw_output) {
      answer = data.raw_output
    }

    messages.value.push({ role: 'assistant', content: answer || '暂无分析结果', timestamp: Date.now() })
  } catch (err) {
    console.error('[Chat] Rules fallback failed:', err)
    messages.value.push({ role: 'assistant', content: '⚠️ 请求处理失败，请稍后重试。', timestamp: Date.now() })
  }
}

// 监听配置变化，异步加载完成后自动更新模式状态
watch(() => llmConfigCache.data.value, (config) => {
  if (config) {
    const wasEnabled = llmEnabled.value
    llmEnabled.value = !!config.enabled
    llmConnected.value = llmEnabled.value
    // 模式切换时提示用户
    if (wasEnabled !== llmEnabled.value) {
      console.log('[Chat] LLM mode:', llmEnabled.value ? 'Agent' : 'Rules')
    }
  }
}, { immediate: true })
</script>

<style scoped>
/* ========== 页面容器 ========== */
/* 参考 SmartStockPick：absolute 定位填满 .app-main（父级 position:relative + overflow:hidden），
   避免 height:100%/min-height 在小分辨率下溢出导致整页滚动 */
.chat-page {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  display: flex;
  flex-direction: row;
  background: #fff;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  border: 1px solid #ebeef5;
}

/* ========== 侧边栏 ========== */
.sidebar {
  width: 260px;
  min-width: 260px;
  background: linear-gradient(180deg, #f7f9fc 0%, #fafbfc 100%);
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
}

.sidebar.collapsed {
  width: 0 !important;
  min-width: 0 !important;
  overflow: hidden;
  border-right: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid #ebeef5;
}

.new-chat-btn {
  flex: 1;
  padding: 8px 12px;
  border: 1px dashed #dcdfe6;
  background: #fff;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: #409eff;
}

.new-chat-btn:hover { background: #ecf5ff; border-color: #409eff; }

.collapse-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  color: #909399;
  border-radius: 6px;
}

.collapse-btn:hover { background: rgba(64, 158, 255, 0.1); color: #409eff; }

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  min-height: 0; /* 让会话列表在 sidebar 内独立滚动 */
}

.session-item {
  padding: 10px 12px;
  margin-bottom: 4px;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
}

.session-item:hover { background: #ecf5ff; }
.session-item.active { background: #d9ecff; color: #409eff; }

.session-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 20px;
}

.session-meta {
  font-size: 11px;
  color: #909399;
  margin-top: 4px;
}

.delete-session-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: #c0c4cc;
  opacity: 0;
}

.session-item:hover .delete-session-btn { opacity: 1; }
.delete-session-btn:hover { background: #fef0f0; color: #f56c6c; }

/* 展开按钮（侧边栏收起时显示） */
.expand-btn {
  position: absolute;
  left: 0;
  top: 12px;
  width: 24px;
  height: 24px;
  border: none;
  background: #fff;
  cursor: pointer;
  font-size: 16px;
  color: #909399;
  border-radius: 0 6px 6px 0;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.1);
  z-index: 10;
}

.expand-btn:hover { background: #ecf5ff; color: #409eff; }

/* ========== 主聊天区域 ========== */
.chat-main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  min-height: 0; /* 关键：允许 flex 子元素收缩，让 .chat-messages 内部滚动而非整页滚动 */
}

/* ========== 顶部工具栏 ========== */
.chat-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-bottom: 1px solid #ebeef5;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1a1a2e;
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  font-size: 22px;
}

.status-tag {
  font-weight: 500;
}

.quota-tag {
  font-weight: 500;
  margin-left: 4px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.action-btn:hover:not(:disabled) {
  background: rgba(64, 158, 255, 0.1);
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.settings-toggle {
  width: 36px;
  height: 36px;
  border: 1px solid #dcdfe6;
  background: #fff;
  border-radius: 8px;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  margin-left: 4px;
}

.settings-toggle:hover {
  border-color: #409eff;
  color: #409eff;
}

.settings-toggle.active {
  background: #409eff;
  border-color: #409eff;
  color: #fff;
}

/* ========== 统计面板 ========== */
.stats-panel {
  display: flex;
  gap: 24px;
  padding: 12px 20px;
  background: linear-gradient(90deg, #ecf5ff, #f0f9ff);
  border-bottom: 1px solid #d9ecff;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 15px;
  font-weight: 600;
  color: #409eff;
}

/* ========== 设置面板 ========== */
.settings-panel {
  padding: 0;
  border-bottom: 1px solid #ebeef5;
}

/* ========== 分类标签 ========== */
.category-tabs {
  flex-shrink: 0;
  display: flex;
  gap: 6px;
  padding: 12px 20px 0;
  overflow-x: auto;
}

.cat-tab {
  padding: 6px 14px;
  border: 1px solid #e4e7ed;
  background: #fff;
  border-radius: 20px;
  cursor: pointer;
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
  transition: all 0.2s;
}

.cat-tab:hover {
  border-color: #409eff;
  color: #409eff;
}

.cat-tab.active {
  background: linear-gradient(135deg, #409eff, #66b1ff);
  border-color: #409eff;
  color: #fff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
}

/* ========== 快捷问题 ========== */
.quick-questions {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 20px;
}

.quick-q-btn {
  padding: 6px 14px;
  border: 1px solid #e4e7ed;
  background: #fafbfc;
  border-radius: 16px;
  cursor: pointer;
  font-size: 12px;
  color: #606266;
  transition: all 0.2s;
}

.quick-q-btn:hover {
  background: #ecf5ff;
  border-color: #409eff;
  color: #409eff;
  transform: translateY(-1px);
}

/* ========== 消息区域 ========== */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  min-height: 0; /* 配合父级 min-height:0，确保仅消息区域内部滚动 */
  background: linear-gradient(180deg, #f7f9fc 0%, #fafbfc 100%);
}

/* 欢迎界面 */
.welcome-screen {
  text-align: center;
  padding: 40px 20px;
}

.welcome-avatar {
  font-size: 56px;
  margin-bottom: 16px;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.welcome-title {
  font-size: 22px;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 8px;
}

.welcome-desc {
  color: #909399;
  font-size: 14px;
  margin-bottom: 28px;
}

.capability-grid {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  max-width: 500px;
  margin: 0 auto;
}

.capability-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 20px;
  font-size: 13px;
  color: #606266;
  transition: all 0.2s;
}

.capability-item:hover {
  border-color: #409eff;
  color: #409eff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.15);
}

.cap-icon {
  font-size: 16px;
}

/* ========== 消息行 ========== */
.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: msgIn 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes msgIn {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.message-row.user .msg-avatar {
  background: linear-gradient(135deg, #ecf5ff, #d9ecff);
}

.msg-body {
  max-width: 75%;
  min-width: 0;
}

.message-row.user .msg-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

/* 消息信息 */
.msg-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  padding: 0 4px;
}

.message-row.user .msg-info {
  flex-direction: row-reverse;
}

.msg-role {
  font-size: 12px;
  font-weight: 600;
  color: #909399;
}

.msg-time {
  font-size: 11px;
  color: #c0c4cc;
}

/* 消息气泡 */
.msg-bubble {
  padding: 14px 18px;
  border-radius: 16px;
  line-height: 1.7;
  word-break: break-word;
  font-size: 13px;
}

.msg-bubble.user {
  background: linear-gradient(135deg, #409eff 0%, #3a8ee6 100%);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.25);
}

.msg-bubble.assistant {
  background: #fff;
  color: #303133;
  border-bottom-left-radius: 4px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

/* 消息操作 */
.msg-actions {
  margin-top: 6px;
}

.message-row.user .msg-actions {
  display: flex;
  justify-content: flex-end;
}

.copy-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: #c0c4cc;
  padding: 2px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.copy-btn:hover {
  color: #409eff;
  background: rgba(64, 158, 255, 0.08);
}

/* ========== 推理过程 ========== */
.reasoning-section {
  margin-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
  padding-bottom: 8px;
}

.toggle-reasoning {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 0;
  transition: color 0.2s;
}

.toggle-reasoning:hover {
  color: #409eff;
}

.arrow {
  display: inline-block;
  transition: transform 0.3s;
  font-size: 10px;
}

.arrow.up {
  transform: rotate(180deg);
}

.reasoning-chain {
  margin-top: 8px;
}

.reasoning-step {
  padding: 10px 14px;
  margin-bottom: 6px;
  border-radius: 8px;
  font-size: 13px;
  border-left: 3px solid transparent;
  transition: all 0.3s;
}

.reasoning-step.status-thinking {
  background: #fdf6ec;
  border-left-color: #e6a23c;
}

.reasoning-step.status-running {
  background: linear-gradient(90deg, #ecf5ff, #f0f9ff);
  border-left-color: #409eff;
  animation: pulse 1.5s infinite;
}

.reasoning-step.status-done {
  background: linear-gradient(90deg, #f0f9eb, #f6ffed);
  border-left-color: #67c23a;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.step-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}

.reasoning-step.status-thinking .step-header { color: #e6a23c; }
.reasoning-step.status-running .step-header { color: #409eff; }
.reasoning-step.status-done .step-header { color: #67c23a; }

.step-badge {
  background: currentColor;
  color: #fff;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
}

.step-icon, .step-tools {
  font-size: 12px;
}

.thought {
  margin-top: 6px;
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}

/* ========== 思考指示器 ========== */
.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #909399;
  font-style: italic;
  font-size: 12px;
  animation: fadePulse 2s infinite;
}

@keyframes fadePulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.thinking-dots span {
  animation: dotBlink 1.4s infinite both;
  color: #409eff;
  font-weight: bold;
}

.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotBlink {
  0%, 80%, 100% { opacity: 0; }
  40% { opacity: 1; }
}
/* ========== Markdown回答样式（使用 :deep() 穿透 scoped） ========== */
:deep(.answer) {
  line-height: 1.7;
  font-size: 13px;
  word-wrap: break-word;
}

:deep(.answer h1),
:deep(.answer h2),
:deep(.answer h3),
:deep(.answer h4) {
  margin: 10px 0 6px;
  font-weight: 700;
  color: #1a1a2e;
  line-height: 1.4;
}

/* 隐藏标题中可能出现的 # 符号 */
:deep(.answer h1::before),
:deep(.answer h2::before),
:deep(.answer h3::before),
:deep(.answer h4::before) {
  content: '';
}

:deep(.answer h1) {
  font-size: 16px;
  border-bottom: 2px solid #409eff;
  padding-bottom: 4px;
  margin-top: 12px;
}

:deep(.answer h2) {
  font-size: 15px;
  border-bottom: 1px solid #e4e7ed;
  padding-bottom: 3px;
  margin-top: 10px;
}

:deep(.answer h3) {
  font-size: 14px;
  color: #303133;
  margin-top: 8px;
}

:deep(.answer p) {
  margin: 6px 0;
  font-size: 13px;
  line-height: 1.7;
}

:deep(.answer strong) {
  color: #303133;
  font-weight: 700;
}

:deep(.answer em) {
  font-style: italic;
  color: #606266;
}

:deep(.answer ul),
:deep(.answer ol) {
  margin: 6px 0;
  padding-left: 24px;
  font-size: 13px;
}

:deep(.answer ul li) {
  list-style-type: disc;
  margin: 4px 0;
  line-height: 1.6;
}

:deep(.answer ol li) {
  list-style-type: decimal;
  margin: 4px 0;
  line-height: 1.6;
}

:deep(.answer ul ul),
:deep(.answer ol ol) {
  padding-left: 20px;
  margin-top: 4px;
}

:deep(.answer ul ul li) {
  list-style-type: circle;
}

:deep(.answer code) {
  background: linear-gradient(135deg, #f5f7fa, #ebeef5);
  color: #e6a23c;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  border: 1px solid #e4e7ed;
}

:deep(.answer pre) {
  background: linear-gradient(135deg, #1e1e1e, #2d2d2d);
  color: #d4d4d4;
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
  font-size: 12px;
  line-height: 1.5;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.3);
}

:deep(.answer pre code) {
  background: none;
  color: inherit;
  padding: 0;
  border: none;
  font-size: 12px;
}

:deep(.answer table) {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  margin: 10px 0;
  font-size: 12px;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  border: 1px solid #e4e7ed;
}

:deep(.answer thead) {
  background: linear-gradient(135deg, #f5f7fa, #ebeef5);
}

:deep(.answer th) {
  padding: 10px 12px;
  text-align: left;
  font-weight: 600;
  border-bottom: 2px solid #dcdfe6;
  font-size: 12px;
  color: #303133;
}

:deep(.answer td) {
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  color: #606266;
  font-size: 12px;
}

:deep(.answer tbody tr:hover) {
  background: #f5f7fa;
}

:deep(.answer blockquote) {
  margin: 8px 0;
  padding: 10px 14px;
  border-left: 4px solid #409eff;
  background: linear-gradient(90deg, #ecf5ff, #f0f9ff);
  color: #606266;
  border-radius: 0 8px 8px 0;
  font-size: 12px;
}

:deep(.answer hr) {
  border: none;
  border-top: 1px solid #e4e7ed;
  margin: 12px 0;
}

:deep(.answer a) {
  color: #409eff;
  text-decoration: none;
  font-weight: 500;
}

:deep(.answer a:hover) {
  text-decoration: underline;
  color: #3a8ee6;
}

:deep(.answer img) {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  margin: 8px 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.error-content {
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 8px;
  padding: 12px 16px;
  color: #f56c6c;
  margin-top: 8px;
}

.error-content {
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 8px;
  padding: 12px 16px;
  color: #f56c6c;
  margin-top: 8px;
}

/* ========== 加载状态 ========== */
.loading-bubble {
  background: #f5f7fa !important;
  border: 1px dashed #dcdfe6;
}

.loading-text { color: #909399; }

.loading-dots span {
  animation: dotBlink 1.4s infinite both;
  color: #409eff;
  font-weight: bold;
}

.loading-dots span:nth-child(2) { animation-delay: 0.2s; }
.loading-dots span:nth-child(3) { animation-delay: 0.4s; }

/* ========== 输入区域 ========== */
.input-area {
  flex-shrink: 0;
  padding: 16px 20px;
  border-top: 1px solid #ebeef5;
  background: #fff;
}

.input-wrapper {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

textarea {
  flex: 1;
  padding: 12px 16px;
  border: 1.5px solid #e4e7ed;
  border-radius: 12px;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  outline: none;
  transition: all 0.25s;
  background: #fafbfc;
  max-height: 120px;
  font-family: inherit;
}

textarea:focus {
  border-color: #409eff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1);
  background: #fff;
}

textarea:disabled {
  background: #f5f7fa;
  cursor: not-allowed;
}

.send-btn {
  width: 80px;
  height: 46px;
  border: none;
  background: linear-gradient(135deg, #409eff 0%, #3a8ee6 100%);
  color: #fff;
  border-radius: 12px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.25s;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.4);
}

.send-btn:active:not(:disabled) {
  transform: translateY(0);
}

.send-btn:disabled {
  background: linear-gradient(135deg, #a0cfff, #b3d4ff);
  cursor: not-allowed;
  box-shadow: none;
}

.stop-btn {
  background: linear-gradient(135deg, #f56c6c 0%, #e6a23c 100%) !important;
  box-shadow: 0 2px 8px rgba(245, 108, 108, 0.3) !important;
}

.stop-btn:hover {
  background: linear-gradient(135deg, #e6a23c 0%, #f56c6c 100%) !important;
  box-shadow: 0 4px 12px rgba(245, 108, 108, 0.4) !important;
}

.stop-icon {
  font-size: 18px;
}

/* ========== 过渡动画 ========== */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  max-height: 300px;
  overflow: hidden;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ================================================================
   移动端响应式 — 卡片式设计（基于 mobile.css design tokens）
   桌面端代码完全不受影响，所有样式仅在 ≤768px 时生效
   ================================================================ */
@media (max-width: 768px) {

  /* ── 页面容器：全屏卡片布局 ── */
  .chat-page {
    position: absolute !important;
    top: calc(var(--m-header-h, 48px) + var(--m-safe-top, 0)) !important;
    left: 0 !important;
    right: 0 !important;
    bottom: calc(var(--m-tab-h, 52px) + var(--m-safe-bottom, 0)) !important;
    flex-direction: column !important;
    background: var(--m-bg, #f5f7fa);
    border-radius: 0 !important;
    box-shadow: none !important;
    border: none !important;
    overflow: hidden;
  }

  /* ── 侧边栏：抽屉式弹出面板 ── */
  .sidebar {
    position: fixed !important;
    top: calc(var(--m-header-h, 48px) + var(--m-safe-top, 0)) !important;
    bottom: calc(var(--m-tab-h, 52px) + var(--m-safe-bottom, 0)) !important;
    left: -280px !important;
    width: 280px !important;
    height: auto !important;
    z-index: 999 !important;
    transition: left 0.3s ease !important;
    box-shadow: none !important;
    border-radius: 0 !important;

    &.mobile-visible {
      left: 0 !important;
      box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15) !important;
      z-index: 9999 !important;
    }
  }

  .session-list {
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
  }

  .sidebar-header {
    padding: 12px 10px;
  }
  .sidebar-header .new-chat-btn { font-size: 13px; padding: 6px 12px; }
  .sidebar-header .collapse-btn { font-size: 18px; width: 28px; height: 28px; }

  .expand-btn { display: none !important; }

  .mobile-overlay {
    position: fixed;
    top: calc(var(--m-header-h, 48px) + var(--m-safe-top, 0)) !important;
    left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.4);
    z-index: 9998;
    animation: m-fadeIn 0.2s ease;
  }

  @keyframes m-fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  /* ── 移动端工具栏已移到全局header，这里保留按钮样式供侧边栏使用 ── */
  .m-mobile-toolbar-fixed .toolbar-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: none;
    background: var(--m-surface2, #f0f2f5);
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: none !important;
    animation: none !important;
    flex-shrink: 0;
  }

  .m-mobile-toolbar-fixed .toolbar-btn:active {
    transform: scale(0.9);
    background: var(--m-border, #e0e4ea);
  }

  .m-mobile-toolbar-fixed .toolbar-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* ── 隐藏桌面端专属元素 ── */
  .chat-header { display: none !important; }
  .category-tabs { display: none !important; }
  .quick-questions { display: none !important; }
  .stats-panel { display: none !important; }

  /* ── 主聊天区域：m-chat-container 卡片布局 ── */
  .chat-main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
    min-height: 0;
    background: var(--m-bg, #f5f7fa);
    padding-top: 0 !important;
    margin-top: 0 !important;
  }

  /* ── 消息区域：m-chat-msgs 滚动容器 ── */
  .chat-messages {
    flex: 1 !important;
    overflow-y: auto !important;
    padding: 6px 10px 8px !important;
    min-height: 0 !important;
    background: var(--m-bg, #f5f7fa) !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
    -webkit-overflow-scrolling: touch;
  }
  .chat-messages::-webkit-scrollbar { display: none; }

  /* ── 消息行：移动端紧凑布局，隐藏头像和信息 ── */
  .message-row {
    margin-bottom: 0 !important;
    gap: 0 !important;
    padding: 0 !important;
  }

  .msg-avatar { display: none !important; }
  .msg-info { display: none !important; }
  .msg-actions { display: none !important; }

  .msg-body {
    max-width: 85% !important;
    padding: 0 !important;
  }

  /* 用户消息靠右 */
  .message-row.user {
    flex-direction: row-reverse !important;
  }
  .message-row.user .msg-body {
    align-items: flex-end !important;
  }

  /* ── 消息气泡：m-chat-bubble 卡片样式 ── */
  .msg-bubble {
    max-width: 100% !important;
    padding: 12px 14px !important;
    border-radius: 16px !important;
    font-size: 14px !important;
    line-height: 1.6 !important;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)) !important;
  }

  /* AI 气泡：白色卡片 + 左边圆角 */
  .msg-bubble.assistant {
    background: var(--m-surface, #fff) !important;
    color: var(--m-text, #1a2332) !important;
    border: 1px solid var(--m-border, #e0e4ea) !important;
    border-bottom-left-radius: 4px !important;
    align-self: flex-start !important;
  }

  /* 用户气泡：主题色 + 右边圆角 */
  .msg-bubble.user {
    background: var(--m-accent, #5b7cfa) !important;
    color: #fff !important;
    border: none !important;
    border-bottom-right-radius: 4px !important;
    align-self: flex-end !important;
  }

  /* ── 欢迎界面：m-card 卡片样式 ── */
  .welcome-screen {
    padding: 20px 16px !important;
    text-align: center;
  }

  .welcome-avatar {
    font-size: 48px !important;
    margin-bottom: 12px !important;
  }

  .welcome-title {
    font-size: 17px !important;
    color: var(--m-text, #1a2332) !important;
    margin-bottom: 6px !important;
  }

  .welcome-desc {
    font-size: 13px !important;
    color: var(--m-text2, #5a6577) !important;
    margin-bottom: 20px !important;
  }

  .capability-grid {
    gap: 8px !important;
    justify-content: center;
  }

  .capability-item {
    padding: 8px 14px !important;
    background: var(--m-surface, #fff) !important;
    border: 1px solid var(--m-border, #e0e4ea) !important;
    border-radius: var(--m-card-radius, 16px) !important;
    font-size: 12px !important;
    color: var(--m-text2, #5a6577) !important;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)) !important;
  }

  /* ── 输入区域：m-chat-input 底部栏 ── */
  .input-area {
    flex-shrink: 0 !important;
    padding: 8px 12px !important;
    padding-bottom: calc(8px + var(--m-safe-bottom, 0)) !important;
    border-top: 1px solid var(--m-border, #e0e4ea) !important;
    background: var(--m-surface, #fff) !important;
  }

  .input-wrapper {
    display: flex !important;
    gap: 8px !important;
    align-items: center !important;
  }

  .sidebar-toggle-btn {
    width: 36px !important;
    height: 36px !important;
    border-radius: 50% !important;
    border: none !important;
    background: var(--m-surface2, #f0f2f5) !important;
    font-size: 16px !important;
    cursor: pointer !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-shrink: 0 !important;
  }

  textarea {
    flex: 1 !important;
    min-height: 40px !important;
    max-height: 100px !important;
    height: 40px !important;
    padding: 0 16px !important;
    border: 1px solid var(--m-border, #e0e4ea) !important;
    border-radius: 20px !important;
    background: var(--m-surface, #fff) !important;
    color: var(--m-text, #1a2332) !important;
    font-size: 14px !important;
    line-height: 40px !important;
    box-shadow: none !important;
  }

  textarea:focus {
    border-color: var(--m-accent, #5b7cfa) !important;
    box-shadow: 0 0 0 2px rgba(91, 124, 250, 0.15) !important;
  }

  .send-btn {
    width: 40px !important;
    height: 40px !important;
    border-radius: 50% !important;
    font-size: 16px !important;
    flex-shrink: 0 !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: var(--m-accent, #5b7cfa) !important;
    box-shadow: 0 2px 8px rgba(91, 124, 250, 0.3) !important;
  }

  .send-btn:active:not(:disabled) {
    transform: scale(0.92) !important;
  }

  .stop-btn {
    background: var(--m-up, #e74c3c) !important;
    box-shadow: 0 2px 8px rgba(231, 76, 60, 0.3) !important;
  }

  /* ── 推理步骤：紧凑卡片 ── */
  .reasoning-section {
    margin-bottom: 8px !important;
    padding-bottom: 6px !important;
  }

  .toggle-reasoning {
    font-size: 12px !important;
    color: var(--m-text3, #8e99ab) !important;
  }

  .reasoning-step {
    padding: 8px 10px !important;
    font-size: 12px !important;
    margin-bottom: 4px !important;
  }

  .step-badge {
    width: 16px !important;
    height: 16px !important;
    font-size: 10px !important;
  }

  /* ── Markdown 内容适配 ── */
  :deep(.answer) {
    font-size: 14px !important;
    line-height: 1.6 !important;
  }

  :deep(.answer h1),
  :deep(.answer h2),
  :deep(.answer h3) {
    font-size: 15px !important;
    margin: 8px 0 4px !important;
  }

  :deep(.answer p) {
    font-size: 14px !important;
    line-height: 1.6 !important;
    margin: 4px 0 !important;
  }

  :deep(.answer pre) {
    padding: 8px 12px !important;
    font-size: 11px !important;
    border-radius: 8px !important;
    overflow-x: auto !important;
  }

  :deep(.answer table) {
    font-size: 11px !important;
    display: block !important;
    overflow-x: auto !important;
    white-space: nowrap !important;
  }

  :deep(.answer th),
  :deep(.answer td) {
    padding: 6px 8px !important;
    font-size: 11px !important;
  }

  :deep(.answer code) {
    font-size: 11px !important;
    padding: 2px 4px !important;
  }

  :deep(.answer blockquote) {
    padding: 8px 10px !important;
    font-size: 12px !important;
  }

  /* ── 加载状态 ── */
  .loading-bubble {
    background: var(--m-surface2, #f0f2f5) !important;
    border: 1px dashed var(--m-border, #e0e4ea) !important;
  }

  .thinking-indicator {
    font-size: 12px !important;
    color: var(--m-text3, #8e99ab) !important;
  }

  /* ── 错误内容 ── */
  .error-content {
    background: rgba(231, 76, 60, 0.08) !important;
    border: 1px solid rgba(231, 76, 60, 0.2) !important;
    color: var(--m-up, #e74c3c) !important;
    padding: 10px 12px !important;
    border-radius: 8px !important;
    font-size: 12px !important;
  }

  /* ── 工具详情折叠面板 ── */
  .tool-details {
    margin: 6px 0 !important;
    font-size: 12px !important;
  }

  .tool-details summary {
    padding: 8px 0 !important;
    cursor: pointer !important;
  }

  .tool-details pre {
    padding: 8px !important;
    font-size: 11px !important;
    overflow-x: auto !important;
  }

  /* ── 会话列表项紧凑化 ── */
  .session-item {
    padding: 8px 10px !important;
    margin-bottom: 2px !important;
  }

  .session-title { font-size: 12px !important; }
  .session-meta { font-size: 10px !important; color: var(--m-text3, #8e99ab) !important; }

  .delete-session-btn { opacity: 1 !important; }
}

/* ── 小屏手机额外优化（≤480px） ── */
@media (max-width: 480px) {
  .msg-bubble {
    padding: 10px 12px !important;
    font-size: 13px !important;
  }

  .welcome-avatar { font-size: 40px !important; }
  .welcome-title { font-size: 16px !important; }
  .capability-item { padding: 6px 10px !important; font-size: 11px !important; }

  textarea {
    min-height: 36px !important;
    height: 36px !important;
    font-size: 13px !important;
    line-height: 36px !important;
  }

  .send-btn {
    width: 36px !important;
    height: 36px !important;
    font-size: 14px !important;
  }

  .chat-messages { padding: 6px 8px 10px !important; gap: 8px !important; }
  .input-area { padding: 6px 8px !important; }
}
</style>
