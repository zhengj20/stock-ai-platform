import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresGuest: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Register.vue'),
    meta: { requiresGuest: true },
  },
  { path: '/', redirect: '/market' },
  {
    path: '/market',
    name: 'Market',
    component: () => import('@/views/MarketDashboard.vue'),
    meta: { title: '市场看板', icon: 'DataBoard', requiresAuth: true },
  },
  {
    path: '/stock',
    name: 'Stock',
    component: () => import('@/views/StockDiagnosis.vue'),
    meta: { title: '个股诊断', icon: 'DataLine', requiresAuth: true },
  },
  {
    path: '/strategy',
    name: 'Strategy',
    component: () => import('@/views/SmartStockPick.vue'),
    meta: { title: '智能选股', icon: 'Aim', requiresAuth: true },
  },
  {
    path: '/ai-stock-pick',
    name: 'AIStockPick',
    component: () => import('@/views/AIStockPick.vue'),
    meta: { title: 'AI股票推荐', icon: 'MagicStick', requiresAuth: true },
  },
  {
    path: '/daily-report',
    name: 'DailyReport',
    component: () => import('@/views/DailyReport.vue'),
    meta: { title: 'AI每日复盘', icon: 'Notebook', requiresAuth: true },
  },
  {
    path: '/dragon',
    name: 'Dragon',
    component: () => import('@/views/DragonList.vue'),
    meta: { title: '龙虎榜', icon: 'Star', requiresAuth: true },
  },
  {
    path: '/sector-analysis',
    name: 'SectorAnalysis',
    component: () => import('@/views/SectorAnalysis.vue'),
    meta: { title: '板块分析', icon: 'DataAnalysis', requiresAuth: true },
  },
  {
    path: '/watchlist',
    name: 'WatchList',
    component: () => import('@/views/WatchList.vue'),
    meta: { title: '自选股', icon: 'StarFilled', requiresAuth: true },
  },
  {
    path: '/holdings',
    name: 'Holdings',
    redirect: '/watchlist',
    meta: { title: '持仓管理', icon: 'Wallet', requiresAuth: true },
  },
  {
    path: '/strategy-center',
    name: 'StrategyCenter',
    redirect: '/watchlist',
    meta: { title: '策略中心', icon: 'TrendCharts', requiresAuth: true, requiresAdmin: true },
  },
  {
    path: '/news',
    name: 'News',
    component: () => import('@/views/NewsSearch.vue'),
    meta: { title: '资讯研报', icon: 'Notebook', requiresAuth: true },
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatAssistant.vue'),
    meta: { title: 'AI助手', icon: 'ChatDotRound', requiresAuth: true },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/AdminDashboard.vue'),
    meta: { title: '系统管理', icon: 'Setting', requiresAuth: true, requiresAdmin: true },
  },
  {
    path: '/sim-trading',
    name: 'SimTrading',
    component: () => import('@/views/SimTrading.vue'),
    meta: { title: 'AI模拟交易', icon: 'Money', requiresAuth: true },
  },
  {
    path: '/backtest',
    name: 'StrategyBacktest',
    component: () => import('@/views/StrategyBacktest.vue'),
    meta: { title: '策略回测', icon: 'TrendCharts', requiresAuth: true },
  },
  {
    path: '/alerts',
    name: 'SmartAlert',
    component: () => import('@/views/SmartAlert.vue'),
    meta: { title: '智能预警', icon: 'Warning', requiresAuth: true },
  },
  {
    path: '/decision',
    name: 'DecisionCenter',
    component: () => import('@/views/DecisionCenter.vue'),
    meta: { title: '决策中心', icon: 'Compass', requiresAuth: true },
  },
  {
    path: '/scanner',
    name: 'StockScanner',
    component: () => import('@/views/StockScanner.vue'),
    meta: { title: '算法选股器', icon: 'Aim', requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  document.title = `${to.meta.title || 'A股智能分析平台'} - A股智能分析平台`

  const authStore = useAuthStore()

  // 初始化认证状态（只在首次访问时）
  if (!authStore.user && localStorage.getItem('gp_access_token')) {
    await authStore.initAuth()
  }

  const isLoggedIn = authStore.isLoggedIn

  // 已登录用户不能访问登录/注册页
  if (to.meta.requiresGuest && isLoggedIn) {
    return { path: '/market' }
  }

  // 未登录用户访问需要认证的页面，跳转到登录
  if (to.meta.requiresAuth && !isLoggedIn) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
    }
  }

  // 非管理员访问管理页面，跳转到首页
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return { path: '/market' }
  }
})

export default router
