<template>
  <div class="chat-history-container">
    <el-row :gutter="16">
      <!-- 左侧会话列表 -->
      <el-col :span="7" :xs="24">
        <el-card class="session-list-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span><el-icon><ChatLineRound /></el-icon> 对话历史</span>
              <el-input
                v-model="searchQuery"
                placeholder="搜索..."
                clearable
                size="small"
                @input="debounceSearch"
              />
            </div>
          </template>

          <div class="session-list" :class="{ 'is-searching': searchQuery }">
            <!-- 搜索结果 -->
            <template v-if="searchQuery && searchResults.length > 0">
              <div
                v-for="item in searchResults"
                :key="'s-' + item.message_id"
                class="session-item search-result"
                @click="loadSession(item.session_id)"
              >
                <div class="session-title">{{ item.content_preview }}</div>
                <div class="session-meta">
                  {{ formatDate(item.created_at) }} · 会话 #{{ item.session_id }}
                </div>
              </div>
            </template>

            <!-- 正常列表 -->
            <template v-else>
              <div
                v-for="s in sessions"
                :key="s.id"
                class="session-item"
                :class="{ active: currentSessionId === s.id }"
                @click="loadSession(s.id)"
              >
                <div class="session-title">{{ s.title }}</div>
                <div class="session-meta">
                  {{ formatDate(s.updated_at) }} · {{ s.message_count }}条消息
                </div>
              </div>

              <el-empty v-if="sessions.length === 0" description="暂无对话记录" :image-size="60" />
            </template>
          </div>

          <div class="pagination-wrap" v-if="!searchQuery && total > 20">
            <el-pagination
              v-model:current-page="page"
              :page-size="20"
              :total="total"
              layout="prev, pager, next"
              small
              @change="fetchSessions"
            />
          </div>
        </el-card>
      </el-col>

      <!-- 右侧消息详情 -->
      <el-col :span="17" :xs="24">
        <el-card class="message-detail-card" shadow="never" v-if="currentSessionId">
          <template #header>
            <div class="card-header">
              <span>{{ currentTitle }}</span>
              <el-popconfirm title="确定删除此对话？" @confirm="deleteSession(currentSessionId)">
                <template #reference>
                  <el-button type="danger" size="small" plain>
                    <el-icon><Delete /></el-icon> 删除
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>

          <div class="messages-container" ref="messagesContainer">
            <div
              v-for="msg in messages"
              :key="msg.id"
              class="message-item"
              :class="msg.role"
            >
              <div class="message-avatar">
                <el-icon v-if="msg.role === 'user'"><User /></el-icon>
                <el-icon v-else><ChatDotRound /></el-icon>
              </div>
              <div class="message-content">
                <div class="message-text" v-html="formatMessage(msg.content)"></div>
                <div class="message-time">{{ formatTime(msg.created_at) }}</div>
                <div v-if="msg.tools_used" class="tools-used">
                  使用工具: {{ msg.tools_used }}
                </div>
              </div>
            </div>

            <el-empty v-if="messages.length === 0" description="加载中..." :image-size="60" />
          </div>
        </el-card>

        <el-card class="message-detail-card" shadow="never" v-else>
          <el-empty description="选择一条对话查看详情" :image-size="100" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const sessions = ref([])
const messages = ref([])
const searchResults = ref([])
const currentSessionId = ref(null)
const currentTitle = ref('')
const searchQuery = ref('')
const page = ref(1)
const total = ref(0)
const messagesContainer = ref(null)

let searchTimer = null

async function api(url, method = 'GET', body = null) {
  const token = localStorage.getItem('gp_access_token')
  return axios({
    url: `/api/v1${url}`,
    method,
    data: body,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  }).then((r) => r.data)
}

async function fetchSessions() {
  try {
    const data = await api(`/chat/sessions?skip=${(page.value - 1) * 20}&limit=20`)
    sessions.value = data.sessions
    total.value = data.total
  } catch (e) {
    console.error('获取会话列表失败:', e)
  }
}

async function loadSession(sessionId) {
  currentSessionId.value = sessionId
  searchQuery.value = ''
  searchResults.value = []

  try {
    const data = await api(`/chat/sessions/${sessionId}`)
    messages.value = data.messages
    currentTitle.value = data.session.title

    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    })
  } catch (e) {
    ElMessage.error('加载对话失败')
  }
}

async function deleteSession(sessionId) {
  try {
    await api(`/chat/sessions/${sessionId}`, 'DELETE')
    ElMessage.success('对话已删除')
    currentSessionId.value = null
    messages.value = []
    fetchSessions()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function debounceSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    if (searchQuery.value.trim()) {
      performSearch()
    } else {
      searchResults.value = []
    }
  }, 300)
}

async function performSearch() {
  try {
    const data = await api(`/chat/search?q=${encodeURIComponent(searchQuery.value)}&limit=50`)
    searchResults.value = data.results
  } catch (e) {
    console.error('搜索失败:', e)
  }
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return d.toLocaleDateString('zh-CN')
}

function formatTime(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatMessage(content) {
  if (!content) return ''
  // 简单的Markdown格式化：换行和代码块
  let html = content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')

  // 代码块
  html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
  // 行内代码
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  // 粗体
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

  return html
}

onMounted(() => {
  fetchSessions()
})

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
})
</script>

<style scoped>
.chat-history-container {{ height: 100%; overflow-y: auto;
  max-width: 1400px;
  margin: 0 auto;
}

.session-list-card, .message-detail-card {
  height: calc(100vh - 160px);
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-header span {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
}

.session-item {
  padding: 12px;
  margin-bottom: 4px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.session-item:hover {
  background: #f0f2f5;
}

.session-item.active {
  background: #ecf5ff;
  color: #409EFF;
}

.search-result {
  border-left: 3px solid #409EFF;
}

.session-title {
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.pagination-wrap {
  padding-top: 12px;
  display: flex;
  justify-content: center;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
  flex-shrink: 0;
}

.message-item.user .message-avatar {
  background: #ecf5ff;
  color: #409EFF;
}

.message-content {
  max-width: 70%;
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  background: #f0f2f5;
  line-height: 1.6;
  font-size: 14px;
  word-break: break-word;
}

.message-item.user .message-text {
  background: #ecf5ff;
  color: #333;
}

.message-text pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 8px 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 4px 0;
}

.message-text code {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 4px;
  border-radius: 3px;
  font-size: 13px;
}

.message-item.user .message-text code {
  background: rgba(255, 255, 255, 0.4);
}

.message-time {
  font-size: 11px;
  color: #999;
  margin-top: 4px;
}

.tools-used {
  font-size: 11px;
  color: #67c23a;
  margin-top: 2px;
}

@media (max-width: 768px) {
  .session-list-card, .message-detail-card {
    height: auto;
    min-height: 400px;
  }

  .message-content {
    max-width: 85%;
  }
}
</style>
