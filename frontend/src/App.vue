<template>
  <el-config-provider :locale="zhCn">
    <!-- 登录/注册页：全屏无布局 -->
    <router-view v-if="isAuthPage" />

    <!-- 主应用布局 -->
    <div v-else class="app-container">
      <!-- 桌面端侧边栏 -->
      <el-aside v-if="!isMobile" :width="isCollapse ? '64px' : '200px'" class="app-aside">
        <div class="logo" @click="isCollapse = !isCollapse">
          <el-icon :size="24" color="#409EFF"><TrendCharts /></el-icon>
          <span v-if="!isCollapse" class="logo-text">A股分析平台</span>
        </div>
        <el-menu
          :default-active="currentRoute"
          :collapse="isCollapse"
          router
          class="side-menu"
          background-color="#1a1a2e"
          text-color="#b8c5d6"
          active-text-color="#409EFF"
        >
          <el-menu-item index="/market">
            <el-icon><DataBoard /></el-icon>
            <template #title>市场看板</template>
          </el-menu-item>
          <el-menu-item index="/stock">
            <el-icon><DataLine /></el-icon>
            <template #title>个股诊断</template>
          </el-menu-item>
          <el-menu-item index="/strategy">
            <el-icon><Aim /></el-icon>
            <template #title>智能选股</template>
          </el-menu-item>
          <el-menu-item index="/scanner">
            <el-icon><Aim /></el-icon>
            <template #title>算法选股</template>
          </el-menu-item>
          <el-menu-item index="/dragon">
            <el-icon><Star /></el-icon>
            <template #title>龙虎榜</template>
          </el-menu-item>
          <el-menu-item index="/sector-analysis">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>板块分析</template>
          </el-menu-item>
          <el-menu-item index="/news">
            <el-icon><Notebook /></el-icon>
            <template #title>资讯研报</template>
          </el-menu-item>
          <el-menu-item index="/backtest">
            <el-icon><TrendCharts /></el-icon>
            <template #title>策略回测</template>
          </el-menu-item>
          <el-menu-item index="/decision">
            <el-icon><Compass /></el-icon>
            <template #title>决策中心</template>
          </el-menu-item>
          <el-menu-item index="/watchlist">
            <el-icon><StarFilled /></el-icon>
            <template #title>自选股</template>
          </el-menu-item>
          <el-menu-item index="/sim-trading">
            <el-icon><Money /></el-icon>
            <template #title>AI模拟交易</template>
          </el-menu-item>
          <el-menu-item index="/ai-stock-pick">
            <el-icon><MagicStick /></el-icon>
            <template #title>AI股票推荐</template>
          </el-menu-item>
          <el-menu-item index="/daily-report">
            <el-icon><Calendar /></el-icon>
            <template #title>AI每日复盘</template>
          </el-menu-item>
          <el-menu-item index="/chat">
            <el-icon><ChatDotRound /></el-icon>
            <template #title>AI助手</template>
          </el-menu-item>
          <el-menu-item index="/alerts">
            <el-icon><Warning /></el-icon>
            <template #title>智能预警</template>
          </el-menu-item>
          <el-divider v-if="authStore.isAdmin" style="margin: 4px 16px; border-color: rgba(255,255,255,0.1);" />
          <el-menu-item v-if="authStore.isAdmin" index="/admin">
            <el-icon><Setting /></el-icon>
            <template #title>系统管理</template>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <!-- 手机端 Tab Bar（仅在移动端显示） -->
      <div v-if="isMobile" class="m-tab-bar">
        <button v-for="(tab, index) in tabsWithMore" :key="tab.key"
          class="m-tab-item"
          :class="{ active: activeTab === tab.key }"
          @click="onTabClick(tab)"
        >
          <span class="tab-icon" :class="{ 'more-icon': tab.key === 'more', bounce: moreBounce }">{{ tab.icon }}</span>
          <span>{{ tab.label }}</span>
        </button>
      </div>

      <!-- 网格功能面板遮罩 -->
      <Transition name="grid-fade">
        <div v-if="gridMenuVisible" class="m-grid-overlay" @click.self="closeGridMenu">
          <div class="m-grid-panel">
            <div class="m-grid-header">
              <span class="m-grid-title">全部功能</span>
              <button class="m-grid-close" @click="closeGridMenu">✕</button>
            </div>
            <div class="m-grid-body">
              <!-- 行情 -->
              <div class="m-grid-category">
                <div class="m-grid-cat-title">📊 行情</div>
                <div class="m-grid-items">
                  <div class="m-grid-item" @click="navigate('/market'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-blue">📊</div>
                    <span>市场看板</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/dragon'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-orange">🐉</div>
                    <span>龙虎榜</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/sector-analysis'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-green">📈</div>
                    <span>板块分析</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/news'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-sky">📰</div>
                    <span>资讯研报</span>
                  </div>
                </div>
              </div>

              <!-- 选股 -->
              <div class="m-grid-category">
                <div class="m-grid-cat-title">🎯 选股</div>
                <div class="m-grid-items">
                  <div class="m-grid-item" @click="navigate('/strategy'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-purple">🎯</div>
                    <span>智能选股</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/scanner'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-cyan">📡</div>
                    <span>算法选股</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/watchlist'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-yellow">⭐</div>
                    <span>自选股</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/alerts'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-red">🔔</div>
                    <span>智能预警</span>
                  </div>
                </div>
              </div>

              <!-- 分析 -->
              <div class="m-grid-category">
                <div class="m-grid-cat-title">📈 分析</div>
                <div class="m-grid-items">
                  <div class="m-grid-item" @click="navigate('/stock'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-indigo">🔍</div>
                    <span>个股诊断</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/backtest'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-cyan">📉</div>
                    <span>策略回测</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/decision'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-indigo">🧭</div>
                    <span>决策中心</span>
                  </div>
                </div>
              </div>

              <!-- AI -->
              <div class="m-grid-category">
                <div class="m-grid-cat-title">🤖 AI</div>
                <div class="m-grid-items">
                  <div class="m-grid-item" @click="navigate('/sim-trading'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-amber">💰</div>
                    <span>模拟交易</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/ai-stock-pick'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-pink">🤖</div>
                    <span>股票推荐</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/daily-report'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-teal">📋</div>
                    <span>每日复盘</span>
                  </div>
                  <div class="m-grid-item" @click="navigate('/chat'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-lime">💬</div>
                    <span>AI助手</span>
                  </div>
                </div>
              </div>

              <!-- 账户 -->
              <div class="m-grid-category" style="border:none;">
                <div class="m-grid-cat-title">👤 账户</div>
                <div class="m-grid-items">
                  <div v-if="authStore.isAdmin" class="m-grid-item" @click="navigate('/admin'); closeGridMenu()">
                    <div class="m-grid-icon m-gi-gray">⚙️</div>
                    <span>系统管理</span>
                  </div>
                  <div class="m-grid-item" @click="closeGridMenu(); handleUserCommand('changepwd')">
                    <div class="m-grid-icon m-gi-sky">🔑</div>
                    <span>修改密码</span>
                  </div>
                  <div class="m-grid-item m-grid-logout" @click="handleUserCommand('logout')">
                    <div class="m-grid-icon m-gi-danger">🚪</div>
                    <span>退出登录</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>

      <!-- 主区域 -->
      <div class="main-area" :style="{ marginLeft: isMobile ? '0' : (isCollapse ? '64px' : '200px') }">
        <!-- 移动端 Header（仅移动端显示） -->
        <div v-if="isMobile" class="mobile-header">
          <span class="m-header-placeholder"></span>
          <span class="m-header-title">{{ currentTitle }}</span>
          <button class="m-header-btn" @click="openUserMenu">👤</button>
        </div>

        <!-- 桌面端 Header -->
        <el-header v-else class="app-header">
          <div class="header-left">
            <el-breadcrumb separator="/">
              <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
              <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
            </el-breadcrumb>
          </div>
          <div class="header-right">
            <template v-if="authStore.isLoggedIn">
              <el-tooltip
                v-if="authStore.remainingDays() !== null && !authStore.isAdmin"
                :content="authStore.isExpired() ? '账号已到期，请联系管理员' : `有效期: ${formatExpiryDate(authStore.expiryStartDate)} ~ ${formatExpiryDate(authStore.expiryDate)}，剩余 ${authStore.remainingDays()} 天`"
                placement="bottom"
              >
                <el-tag
                  :type="authStore.isExpired() ? 'danger' : authStore.remainingDays() <= 7 ? 'warning' : 'success'"
                  effect="plain" size="small" class="expiry-tag"
                >
                  {{ authStore.isExpired() ? '已到期' : `剩余${authStore.remainingDays()}天` }}
                </el-tag>
              </el-tooltip>

              <el-dropdown @command="handleUserCommand">
                <span class="user-info">
                  <el-icon><UserFilled /></el-icon>
                  {{ authStore.user?.username }}
                  <el-tag v-if="authStore.isAdmin" type="danger" effect="dark" size="small">管理员</el-tag>
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="changepwd">修改密码</el-dropdown-item>
                    <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </div>
        </el-header>

        <!-- 主体内容 -->
        <el-main class="app-main" :class="{ 'app-main-mobile': isMobile }">
          <router-view v-slot="{ Component }">
            <keep-alive :include="cachedViews" :max="10">
              <transition
                :name="isMobile ? 'm-page' : 'fade'"
                mode="out-in"
              >
                <component :is="Component" :key="route.path" />
              </transition>
            </keep-alive>
          </router-view>
        </el-main>

        <div class="keepalive-debug">v2.0</div>

        <!-- 桌面端 Footer -->
        <el-footer v-if="!isMobile" class="app-footer">
          <span>A股智能分析平台 | 基于20个分析模块 | 仅供参考，不构成投资建议</span>
        </el-footer>
      </div>

      <!-- 修改密码对话框 -->
      <el-dialog v-model="changePwdVisible" title="修改密码" width="400px">
        <el-form :model="pwdForm" label-width="100px">
          <el-form-item label="原密码">
            <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="输入原密码" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少6个字符" />
          </el-form-item>
          <el-form-item label="确认密码">
            <el-input v-model="pwdForm.confirm_password" type="password" show-password placeholder="再次输入新密码" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="changePwdVisible = false">取消</el-button>
          <el-button type="primary" :loading="changingPwd" @click="handleChangePassword">确认修改</el-button>
        </template>
      </el-dialog>
    </div>
  </el-config-provider>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UserFilled, TrendCharts, DataBoard, DataLine, Aim, Star, StarFilled, Notebook, ChatDotRound, Setting, Calendar, MagicStick, DataAnalysis, Money, Compass, Warning } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { useTableFit } from '@/composables/useTableFit'
import { preloadDashboardData } from '@/composables/usePreload'
import '@/styles/mobile.css'

let heartbeatTimer = null
useTableFit('.el-table')

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isCollapse = ref(false)
const gridMenuVisible = ref(false)
const moreBounce = ref(false)
const isMobile = ref(false)

function toggleChatSidebar() {
  window.dispatchEvent(new CustomEvent('toggle-chat-sidebar'))
}

const changePwdVisible = ref(false)
const changingPwd = ref(false)
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })

const currentRoute = computed(() => route.path)
const currentTitle = computed(() => route.meta?.title || '市场看板')

const cachedViews = computed(() => [
  'MarketDashboard', 'StockDiagnosis', 'SmartStockPick', 'AIStockPick', 'DragonList',
  'WatchList', 'NewsSearch', 'DailyReport', 'ChatAssistant', 'AdminDashboard', 'SectorAnalysis', 'SimTrading',
  'DecisionCenter', 'StockScanner'
])

// ── Mobile Tab Bar ─────────────────────────────────────────────
const TAB_BAR_HEIGHT = 64 // including safe area
const tabBarHeight = computed(() => isMobile.value ? TAB_BAR_HEIGHT + 'px' : '0px')

const tabs = [
  { key: 'market',    label: '行情', icon: '📊', routes: ['/market', '/dragon', '/sector-analysis', '/news'] },
  { key: 'pick',      label: '选股', icon: '🎯', routes: ['/strategy', '/watchlist', '/alerts', '/scanner'] },
  { key: 'analysis',  label: '分析', icon: '📈', routes: ['/stock', '/backtest', '/decision'] },
  { key: 'ai',        label: 'AI',   icon: '🤖', routes: ['/sim-trading', '/ai-stock-pick', '/daily-report', '/chat', '/admin'] },
]

// Tab Bar 顺序：行情 → 选股 → 全部 → 分析 → AI
const tabsWithMore = computed(() => {
  return [
    tabs[0], // 行情
    tabs[1], // 选股
    { key: 'more', label: '全部', icon: '' },
    tabs[2], // 分析
    tabs[3], // AI
  ]
})

// 计算当前 tab
const activeTab = computed(() => {
  const path = route.path
  for (const tab of tabs) {
    if (tab.routes.some(r => path.startsWith(r))) return tab.key
  }
  return 'market'
})

function switchTab(tab) {
  if (activeTab.value === tab.key) return // already on this tab
  navigate(tab.routes[0])
}

function navigate(path) {
  if (route.path !== path) router.push(path)
}

function openGridMenu() {
  moreBounce.value = true
  requestAnimationFrame(() => {
    setTimeout(() => { moreBounce.value = false }, 420)
  })
  gridMenuVisible.value = true
}

function closeGridMenu() {
  gridMenuVisible.value = false
}

function onTabClick(tab) {
  if (gridMenuVisible.value) {
    closeGridMenu()
    if (tab.key !== 'more') switchTab(tab)
    return
  }
  if (tab.key === 'more') openGridMenu()
  else switchTab(tab)
}

// 用户菜单（移动端简化版）
async function openUserMenu() {
  const action = await ElMessageBox.alert(
    `${authStore.user?.username || '用户'}`,
    '账户操作',
    {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      showCancelButton: true,
      type: 'info',
    }
  ).catch(() => null)
  if (action === 'confirm') handleUserCommand('logout')
}

// ── Heartbeat ──────────────────────────────────────────────────
async function sendHeartbeat() {
  try { await api.post('/auth/heartbeat') } catch {}
}
function startHeartbeat() {
  stopHeartbeat(); sendHeartbeat()
  heartbeatTimer = setInterval(sendHeartbeat, 15000)
}
function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
}

const isAuthPage = computed(() => ['/login', '/register'].includes(route.path))

function handleUserCommand(command) {
  if (command === 'logout') {
    stopHeartbeat(); authStore.logout(); router.push('/login')
  } else if (command === 'changepwd') {
    pwdForm.value = { old_password: '', new_password: '', confirm_password: '' }
    changePwdVisible.value = true
  }
}

async function handleChangePassword() {
  if (pwdForm.value.new_password.length < 6) { ElMessage.error('新密码至少6个字符'); return }
  if (pwdForm.value.new_password !== pwdForm.value.confirm_password) { ElMessage.error('两次输入的密码不一致'); return }
  changingPwd.value = true
  try {
    await api.post('/auth/change-password', {
      old_password: pwdForm.value.old_password,
      new_password: pwdForm.value.new_password,
    })
    ElMessage.success('密码已修改，请重新登录')
    changePwdVisible.value = false
    setTimeout(() => { authStore.logout(); router.push('/login') }, 1000)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '修改失败')
  } finally { changingPwd.value = false }
}

function formatExpiryDate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function checkMobile() { isMobile.value = window.innerWidth < 768 }

onMounted(async () => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  if (localStorage.getItem('gp_access_token')) {
    preloadDashboardData().catch(() => {})
    startHeartbeat()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', checkMobile)
  stopHeartbeat()
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: var(--m-bg, #f0f2f5); }

.app-container { display: flex; min-height: 100vh; overflow-x: clip; }

/* ── Sidebar (desktop) ───────────────────────────────────────── */
.app-aside {
  background: #1a1a2e;
  transition: width 0.3s;
  position: fixed;
  left: 0; top: 0; bottom: 0;
  z-index: 100;
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.logo {
  height: 48px; display: flex; align-items: center; justify-content: center; gap: 8px;
  cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.1);
  flex-shrink: 0;
}
.logo-text { color: #fff; font-size: 15px; font-weight: 600; white-space: nowrap; }
.side-menu { border-right: none; flex: 1; overflow-y: auto; }
.side-menu::-webkit-scrollbar { display: none; }
.side-menu:not(.el-menu--collapse) { width: 200px; }
.app-aside .el-menu-item {
  height: 44px !important; line-height: 44px !important;
  font-size: 13px !important; padding: 0 16px !important;
}
.app-aside .el-menu-item :deep(.el-icon) { margin-right: 8px !important; font-size: 15px !important; }
.el-menu--collapse .el-menu-item { height: 48px !important; line-height: 48px !important; }
.el-menu--collapse { width: 64px; }
.el-menu--collapse .el-menu-item span,
.el-menu--collapse .el-sub-menu__title span { display: none; }

/* ── Main Area ───────────────────────────────────────────────── */
.main-area {
  flex: 1; transition: margin-left 0.3s;
  display: flex; flex-direction: column; min-height: 100vh;
  min-width: 0; overflow-x: clip;
}
.app-header {
  height: 50px; background: #fff; display: flex; align-items: center; justify-content: space-between;
  padding: 0 20px; border-bottom: 1px solid #eee; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}
.header-left { display: flex; align-items: center; gap: 8px; }
.header-right { display: flex; gap: 8px; align-items: center; }
.user-info {
  display: flex; align-items: center; gap: 6px; cursor: pointer; color: #409EFF; font-size: 14px;
}
.user-info:hover { opacity: 0.8; }
.expiry-tag { margin-right: 8px; }
.app-main { flex: 1; padding: 16px; overflow: hidden; position: relative; background: var(--m-bg, #f0f2f5); min-width: 0; }
.app-main::-webkit-scrollbar { display: none; }
.app-footer {
  text-align: center; color: #999; font-size: 11px; padding: 6px;
  background: #fff; border-top: 1px solid #eee;
  --el-footer-height: 36px; height: 36px; line-height: 24px;
}
.keepalive-debug {
  position: fixed; bottom: 4px; right: 8px;
  font-size: 10px; color: rgba(0,0,0,0.3); z-index: 9999;
  pointer-events: none;
}

/* ── Mobile Header ───────────────────────────────────────────── */
.mobile-header {
  display: none;
}

/* ── Mobile (max-width: 768px) ───────────────────────────────── */
@media (max-width: 768px) {
  html, body { height: calc(var(--vh, 1vh) * 100) !important; max-height: calc(var(--vh, 1vh) * 100) !important; overflow: hidden !important; }
  body { background: var(--m-bg, #f5f7fa); }
  .app-aside { display: none !important; }
  .app-container { height: calc(var(--vh, 1vh) * 100) !important; min-height: calc(var(--vh, 1vh) * 100) !important; max-height: calc(var(--vh, 1vh) * 100) !important; overflow-y: auto !important; overflow-x: visible !important; }
  .main-area {
    margin-left: 0 !important;
    height: calc(var(--vh, 1vh) * 100) !important;
    min-height: calc(var(--vh, 1vh) * 100) !important;
    max-height: calc(var(--vh, 1vh) * 100) !important;
    overflow-y: auto !important;
    overflow-x: visible !important;
  }
  .app-header { display: none !important; }

  /* 移动端新 header */
  .mobile-header {
    display: flex !important;
    align-items: center;
    justify-content: space-between;
    height: var(--m-header-h);
    padding: 0 12px;
    padding-top: env(safe-area-inset-top, 0);
    background: var(--m-surface, #fff);
    border-bottom: 1px solid var(--m-border, #e0e4ea);
    flex-shrink: 0;
    position: relative;
    z-index: 100;
  }
  .m-header-placeholder { width: 40px; flex-shrink: 0; }
  .m-header-btn {
    background: none; border: none;
    font-size: 22px; cursor: pointer;
    width: 40px; height: 40px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 8px;
    color: var(--m-text, #333);
    -webkit-tap-highlight-color: transparent;
  }
  .m-header-btn:active { background: var(--m-surface2, #f0f2f5); }
  .m-header-title { font-size: 16px; font-weight: 600; color: var(--m-text, #333); }

  .app-main {
    padding: 6px !important;
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 4px) !important;
    flex: 1; min-height: 0 !important; overflow-y: auto !important; overflow-x: visible !important;
    background: var(--m-bg, #f5f7fa);
  }
  .app-main::-webkit-scrollbar { display: none; }

  .app-footer { display: none !important; }

  /* Element Plus 弹窗适配 */
  .el-dialog { --el-dialog-width: 92% !important; margin-top: 10vh !important; }
  .el-message-box { --el-messagebox-width: 92% !important; }
  .el-drawer { --el-drawer-size: 78vw !important; }
  .el-dropdown-menu { max-width: 70vw; }

  /* 触摸优化 */
  * { -webkit-tap-highlight-color: transparent; }
  .app-container { -webkit-user-select: none; user-select: none; }
  .app-container input, .app-container textarea { -webkit-user-select: text; user-select: text; }

  /* ── Grid Menu Overlay ─────────────────────────────────────── */
  .m-grid-overlay {
    position: fixed;
    top: 0; left: 0; right: 0;
    bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0));
    z-index: 9998;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: flex-end;
    justify-content: center;
  }

  .m-grid-panel {
    width: 100%;
    max-height: 70vh;
    background: #fff;
    border-radius: 14px 14px 0 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: grid-slide-up 0.3s ease-out;
  }

  @keyframes grid-slide-up {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }

  .m-grid-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 14px;
    border-bottom: 1px solid #f0f0f0;
    flex-shrink: 0;
  }

  .m-grid-title {
    font-size: 13px;
    font-weight: 600;
    color: #333;
  }

  .m-grid-close {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: none;
    background: #f5f5f5;
    font-size: 12px;
    color: #999;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }

  .m-grid-close:active {
    background: #e8e8e8;
  }

  .m-grid-body {
    padding: 6px 10px 12px;
    overflow-y: auto;
    flex: 1;
  }

  .m-grid-category {
    margin-bottom: 6px;
    border-bottom: 1px solid #f5f5f5;
    padding-bottom: 6px;
  }

  .m-grid-cat-title {
    font-size: 10px;
    color: #999;
    margin-bottom: 4px;
    font-weight: 500;
  }

  .m-grid-items {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px 2px;
  }

  .m-grid-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    padding: 4px 2px;
    border-radius: 8px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .m-grid-item:active {
    background: #f5f7fa;
  }

  .m-grid-icon {
    width: 34px;
    height: 34px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 17px;
  }

  /* Icon background colors */
  .m-gi-blue { background: linear-gradient(135deg, #409eff, #66b1ff); }
  .m-gi-green { background: linear-gradient(135deg, #52c41a, #73d13d); }
  .m-gi-orange { background: linear-gradient(135deg, #fa8c16, #ffc53d); }
  .m-gi-yellow { background: linear-gradient(135deg, #fadb14, #ffe58f); }
  .m-gi-purple { background: linear-gradient(135deg, #722ed1, #b37feb); }
  .m-gi-cyan { background: linear-gradient(135deg, #13c2c2, #36cfc9); }
  .m-gi-red { background: linear-gradient(135deg, #f5222d, #ff7875); }
  .m-gi-indigo { background: linear-gradient(135deg, #5b7cfa, #82a2f9); }
  .m-gi-pink { background: linear-gradient(135deg, #eb2f96, #f972bf); }
  .m-gi-teal { background: linear-gradient(135deg, #08979c, #36cfc9); }
  .m-gi-lime { background: linear-gradient(135deg, #a0d911, #baff59); }
  .m-gi-amber { background: linear-gradient(135deg, #faad14, #ffc53d); }
  .m-gi-sky { background: linear-gradient(135deg, #2db7f5, #69c0ff); }
  .m-gi-gray { background: linear-gradient(135deg, #8c8c8c, #bfbfbf); }
  .m-gi-danger { background: linear-gradient(135deg, #ff4d4f, #ff7875); }

  .m-grid-item span {
    font-size: 10px;
    color: #666;
    text-align: center;
    line-height: 1.2;
  }

  .m-grid-logout {
    opacity: 0.7;
  }

  /* Grid menu transition */
  .grid-fade-enter-active,
  .grid-fade-leave-active {
    transition: opacity 0.2s ease;
  }

  .grid-fade-enter-from,
  .grid-fade-leave-to {
    opacity: 0;
  }

  .grid-fade-enter-active .m-grid-panel {
    animation: grid-slide-up 0.3s ease-out;
  }
}

/* ========== 页面切换动画 ========== */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 移动端页面切换动画 */
.m-page-enter-active,
.m-page-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.m-page-enter-from {
  opacity: 0;
  transform: translateX(30px);
}

.m-page-leave-to {
  opacity: 0;
  transform: translateX(-30px);
}

/* ========== 全局 el-table ========== */
.el-table {
  width: 100% !important;
}
.el-table__inner-wrapper,
.el-table__header-wrapper,
.el-table__body-wrapper,
.el-table__footer-wrapper,
.el-scrollbar {
  width: 100% !important;
  min-width: 0 !important;
}
.el-table__header-wrapper > table,
.el-table__body-wrapper > table,
.el-table__footer-wrapper > table,
.el-scrollbar__wrap > table,
.el-table__inner-wrapper > table {
  width: 100% !important;
  table-layout: fixed !important;
}
@media (max-width: 768px) {
  .el-table { width: auto !important; min-width: 100% !important; }
}
</style>
