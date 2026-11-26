<template>
  <div class="login-container">
    <!-- 背景动画元素 -->
    <div class="bg-grid">
      <div v-for="i in 20" :key="'h' + i" class="grid-line-h" :style="{ top: `${(i - 1) * 5}%` }" />
      <div v-for="i in 30" :key="'v' + i" class="grid-line-v" :style="{ left: `${(i - 1) * 3.57}%` }" />
    </div>

    <!-- K线装饰 -->
    <div class="candlestick-chart">
      <div v-for="(c, idx) in candles" :key="idx" class="candle" :style="{ left: `${idx * 3.5}%`, bottom: `${c.bottom}%` }">
        <div class="candle-body" :class="c.up ? 'up' : 'down'" :style="{ height: `${c.body}px`, marginBottom: `${c.lower}px` }" />
        <div class="candle-wick" :style="{ height: `${c.wick}px` }" />
      </div>
    </div>

    <!-- 浮动数据粒子 -->
    <div class="particles">
      <div v-for="(p, idx) in particles" :key="idx" class="particle" :style="{ left: p.x + '%', top: p.y + '%', animationDelay: p.delay + 's' }">
        {{ p.value }}
      </div>
    </div>

    <!-- 登录卡片 -->
    <div class="login-card">
      <div class="card-glow" />
      
      <div class="logo-area">
        <div class="logo-icon">
          <el-icon :size="48"><TrendCharts /></el-icon>
        </div>
        <h1 class="platform-name">A股智能分析平台</h1>
        <p class="platform-subtitle">AI驱动 · 全市场扫描 · 20+分析模块</p>
      </div>

      <!-- 实时行情装饰条 -->
      <div class="ticker-bar">
        <span v-for="(t, idx) in tickers" :key="idx" class="ticker-item">
          <span class="ticker-name">{{ t.name }}</span>
          <span :class="['ticker-price', t.change >= 0 ? 'up' : 'down']">{{ t.price }} {{ t.change >= 0 ? '+' : '' }}{{ t.change }}%</span>
        </span>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        class="login-form"
        @keyup.enter="handleLogin"
      >
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名或邮箱"
            prefix-icon="User"
            class="custom-input"
          />
        </el-form-item>

        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            prefix-icon="Lock"
            show-password
            class="custom-input"
          />
        </el-form-item>

        <div class="form-extras">
          <el-checkbox v-model="rememberPassword" size="small">记住密码</el-checkbox>
        </div>

        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            {{ loading ? loadingText : '登 录' }}
          </el-button>
        </el-form-item>

        <div class="footer-link">
          还没有账号？
          <router-link to="/register">使用邀请码注册</router-link>
        </div>
      </el-form>
    </div>

    <!-- 加载遮罩层 -->
    <Transition name="fade">
      <div v-if="loading" class="loading-overlay">
        <div class="loading-content">
          <div class="loading-spinner">
            <div class="spinner-ring" />
            <div class="spinner-ring" />
            <div class="spinner-ring" />
          </div>
          <p class="loading-text">{{ loadingText }}</p>
          <p v-if="loadingText === '正在加载数据...'" class="loading-hint">
            正在同步市场数据、龙虎榜和策略信号，请稍候...
          </p>
        </div>
      </div>
    </Transition>

    <!-- 底部信息 -->
    <div class="bottom-info">
      <span>数据仅供参考，不构成投资建议</span>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { TrendCharts } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { preloadDashboardData } from '@/composables/usePreload'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const loading = ref(false)
const loadingText = ref('登录中...')

const rememberPassword = ref(false)

// 简单的 XOR 加密，避免纯明文存储
function encrypt(text, key) {
  let result = ''
  for (let i = 0; i < text.length; i++) {
    result += String.fromCharCode(text.charCodeAt(i) ^ key.charCodeAt(i % key.length))
  }
  return btoa(result)
}

function decrypt(encoded, key) {
  const text = atob(encoded)
  let result = ''
  for (let i = 0; i < text.length; i++) {
    result += String.fromCharCode(text.charCodeAt(i) ^ key.charCodeAt(i % key.length))
  }
  return result
}

const CREDENTIALS_KEY = 'gp_credentials'
const ENCRYPT_KEY = 'a-stock-secure-key-2024'

// 加载保存的凭据
function loadCredentials() {
  try {
    const saved = localStorage.getItem(CREDENTIALS_KEY)
    if (saved) {
      const decrypted = decrypt(saved, ENCRYPT_KEY)
      const creds = JSON.parse(decrypted)
      form.username = creds.username || ''
      form.password = creds.password || ''
      rememberPassword.value = true
    }
  } catch (e) {
    console.error('加载保存的凭据失败:', e)
    localStorage.removeItem(CREDENTIALS_KEY)
  }
}

// 保存/清除凭据
function saveCredentials(remember) {
  if (remember) {
    const creds = JSON.stringify({ username: form.username, password: form.password })
    localStorage.setItem(CREDENTIALS_KEY, encrypt(creds, ENCRYPT_KEY))
  } else {
    localStorage.removeItem(CREDENTIALS_KEY)
  }
}

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// K线装饰数据
const candles = ref([])

// 浮动粒子
const particles = ref([])

// 行情模拟数据
const tickers = reactive([
  { name: '上证指数', price: '3,287.56', change: 1.24 },
  { name: '深证成指', price: '10,892.33', change: -0.56 },
  { name: '创业板指', price: '2,198.77', change: 2.13 },
  { name: '科创50', price: '756.42', change: -1.08 },
])

let tickerTimer = null

// 生成K线数据
function generateCandles() {
  const data = []
  let bottom = 20 + Math.random() * 30
  for (let i = 0; i < 25; i++) {
    const up = Math.random() > 0.45
    const body = 15 + Math.random() * 35
    const wick = 10 + Math.random() * 20
    const lower = Math.random() * 15
    data.push({ up, body, wick, lower, bottom })
    bottom += (Math.random() - 0.4) * 8
    bottom = Math.max(15, Math.min(60, bottom))
  }
  candles.value = data
}

// 生成浮动粒子
function generateParticles() {
  const values = ['+2.3%', '-1.5%', '+0.8%', '3,287', 'VOL↑', 'MA5', 'MACD', 'RSI62', 'BOLL', 'KDJ']
  const data = []
  for (let i = 0; i < 12; i++) {
    data.push({
      x: Math.random() * 90 + 5,
      y: Math.random() * 80 + 10,
      delay: Math.random() * 8,
      value: values[Math.floor(Math.random() * values.length)],
    })
  }
  particles.value = data
}

// 模拟行情更新
function updateTickers() {
  tickers.forEach(t => {
    const delta = (Math.random() - 0.5) * 0.3
    t.change = parseFloat((t.change + delta).toFixed(2))
  })
}

async function handleLogin() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  loadingText.value = '登录中...'
  try {
    await authStore.login(form.username, form.password)
    // 记住密码处理
    saveCredentials(rememberPassword.value)
    // 同步预加载：等待数据写入 IndexedDB 后再跳转，确保进入页面立即有数据
    loadingText.value = '正在加载数据...'
    await preloadDashboardData().catch(() => {})
    ElMessage.success('登录成功')
    router.push(router.currentRoute.value.query.redirect || '/market')
  } catch (e) {
    let msg = '登录失败，请检查用户名和密码'
    if (e.response?.data?.detail) {
      msg = e.response.data.detail
    } else if (e.code === 'ERR_NETWORK') {
      msg = '网络连接失败，请确保后端服务已启动（端口5174）'
    } else if (e.message) {
      msg = `请求错误: ${e.message}`
    }
    console.error('登录错误详情:', e)
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  generateCandles()
  generateParticles()
  tickerTimer = setInterval(updateTickers, 3000)

  // 加载保存的凭据（只填充表单，不自动登录）
  loadCredentials()
})

onUnmounted(() => {
  if (tickerTimer) clearInterval(tickerTimer)
})
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 40%, #0d1b2a 100%);
  position: relative;
  overflow: hidden;
}

/* ========== 背景网格 ========== */
.bg-grid {
  position: absolute;
  inset: 0;
  opacity: 0.06;
  pointer-events: none;
}

.grid-line-h, .grid-line-v {
  position: absolute;
  background: #4fc3f7;
}

.grid-line-h {
  left: 0; right: 0; height: 1px;
}

.grid-line-v {
  top: 0; bottom: 0; width: 1px;
}

/* ========== K线装饰 ========== */
.candlestick-chart {
  position: absolute;
  bottom: 8%;
  left: 5%;
  right: 5%;
  height: 200px;
  opacity: 0.12;
  pointer-events: none;
}

.candle {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.candle-body {
  width: 8px;
  border-radius: 1px;
}

.candle-body.up {
  background: #ef5350;
}

.candle-body.down {
  background: #26a69a;
}

.candle-wick {
  width: 1px;
  background: currentColor;
  margin-top: -1px;
}

/* ========== 浮动粒子 ========== */
.particles {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.particle {
  position: absolute;
  color: #4fc3f7;
  font-size: 11px;
  opacity: 0.15;
  animation: floatParticle 12s ease-in-out infinite;
  font-family: 'Courier New', monospace;
}

@keyframes floatParticle {
  0%, 100% { transform: translateY(0) translateX(0); opacity: 0.15; }
  25% { transform: translateY(-20px) translateX(10px); opacity: 0.25; }
  50% { transform: translateY(-10px) translateX(-5px); opacity: 0.1; }
  75% { transform: translateY(-30px) translateX(15px); opacity: 0.2; }
}

/* ========== 登录卡片 ========== */
.login-card {
  position: relative;
  width: 440px;
  padding: 48px 40px 40px;
  background: rgba(15, 23, 42, 0.85);
  border-radius: 20px;
  border: 1px solid rgba(79, 195, 247, 0.15);
  backdrop-filter: blur(20px);
  box-shadow: 
    0 25px 60px rgba(0, 0, 0, 0.5),
    0 0 80px rgba(79, 195, 247, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  z-index: 1;
}

.card-glow {
  position: absolute;
  top: -1px; left: -1px; right: -1px; bottom: -1px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(79, 195, 247, 0.2), transparent 50%, rgba(239, 83, 80, 0.1));
  z-index: -1;
  filter: blur(1px);
}

/* ========== Logo区域 ========== */
.logo-area {
  text-align: center;
  margin-bottom: 28px;
}

.logo-icon {
  width: 72px;
  height: 72px;
  margin: 0 auto 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(79, 195, 247, 0.15), rgba(79, 195, 247, 0.05));
  border: 1px solid rgba(79, 195, 247, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4fc3f7;
}

.platform-name {
  font-size: 26px;
  font-weight: 700;
  background: linear-gradient(135deg, #e2e8f0, #ffffff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 8px;
  letter-spacing: 2px;
}

.platform-subtitle {
  color: rgba(148, 163, 184, 0.8);
  font-size: 13px;
  letter-spacing: 3px;
}

/* ========== 行情装饰条 ========== */
.ticker-bar {
  display: flex;
  justify-content: space-between;
  padding: 10px 16px;
  margin-bottom: 24px;
  background: rgba(15, 23, 42, 0.6);
  border-radius: 10px;
  border: 1px solid rgba(79, 195, 247, 0.08);
}

.ticker-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.ticker-name {
  font-size: 10px;
  color: rgba(148, 163, 184, 0.7);
}

.ticker-price {
  font-size: 12px;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.ticker-price.up { color: #ef5350; }
.ticker-price.down { color: #26a69a; }

/* ========== 表单样式 ========== */
.login-form {
  margin-top: 8px;
}

.custom-input :deep(.el-input__wrapper) {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(79, 195, 247, 0.12);
  border-radius: 10px;
  padding: 12px 16px;
  transition: all 0.3s;
}

.custom-input :deep(.el-input__wrapper:hover) {
  border-color: rgba(79, 195, 247, 0.3);
}

.custom-input :deep(.el-input__wrapper.is-focus) {
  border-color: #4fc3f7;
  box-shadow: 0 0 0 2px rgba(79, 195, 247, 0.15);
}

.custom-input :deep(.el-input__inner) {
  color: #e2e8f0;
}

.custom-input :deep(.el-input__prefix .el-icon) {
  color: rgba(79, 195, 247, 0.5);
}

.login-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 8px;
  border-radius: 12px;
  background: linear-gradient(135deg, #4fc3f7, #0288d1);
  border: none;
  transition: all 0.3s;
}

.login-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(79, 195, 247, 0.35);
}

.login-btn:active {
  transform: translateY(0);
}

/* ========== 表单附加选项 ========== */
.form-extras {
  margin-bottom: 16px;
}

.form-extras :deep(.el-checkbox__label) {
  color: rgba(148, 163, 184, 0.7);
  font-size: 13px;
}

.form-extras :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: #4fc3f7;
  border-color: #4fc3f7;
}

/* ========== 底部链接 ========== */
.footer-link {
  text-align: center;
  color: rgba(148, 163, 184, 0.7);
  font-size: 13px;
  margin-top: 20px;
}

.footer-link a {
  color: #4fc3f7;
  text-decoration: none;
  font-weight: 500;
  transition: opacity 0.2s;
}

.footer-link a:hover {
  opacity: 0.8;
  text-decoration: underline;
}

/* ========== 底部信息 ========== */
.bottom-info {
  position: absolute;
  bottom: 24px;
  left: 0; right: 0;
  text-align: center;
  color: rgba(148, 163, 184, 0.4);
  font-size: 12px;
}

/* ========== Element Plus 覆盖 ========== */
:deep(.el-form-item__error) {
  color: #ef5350;
  padding-top: 4px;
}

/* ========== 加载遮罩层 ========== */
.loading-overlay {
  position: fixed;
  inset: 0;
  background: rgba(10, 14, 39, 0.92);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.loading-content {
  text-align: center;
  color: #e2e8f0;
}

.loading-spinner {
  position: relative;
  width: 80px;
  height: 80px;
  margin: 0 auto 24px;
}

.spinner-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 3px solid transparent;
  animation: spinRing 1.5s linear infinite;
}

.spinner-ring:nth-child(1) {
  border-top-color: #4fc3f7;
  animation-duration: 1.5s;
}

.spinner-ring:nth-child(2) {
  inset: 8px;
  border-right-color: #0288d1;
  animation-duration: 2s;
  animation-direction: reverse;
}

.spinner-ring:nth-child(3) {
  inset: 16px;
  border-bottom-color: #4fc3f7;
  animation-duration: 1s;
}

@keyframes spinRing {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.loading-text {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
  letter-spacing: 2px;
}

.loading-hint {
  font-size: 13px;
  color: rgba(148, 163, 184, 0.7);
  line-height: 1.6;
}

/* ========== 过渡动画 ========== */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .login-card {
    width: calc(100% - 32px);
    padding: 36px 24px 32px;
  }
  
  .platform-name { font-size: 22px; }
  
  .ticker-bar { flex-wrap: wrap; gap: 8px; }
  .ticker-item { min-width: 40%; }
}

@media (max-width: 480px) {
  .login-card { padding: 28px 20px 24px; }
  .logo-icon { width: 60px; height: 60px; }
  .platform-name { font-size: 20px; letter-spacing: 1px; }
  .platform-subtitle { font-size: 11px; }
  
  .loading-spinner {
    width: 60px;
    height: 60px;
  }
  
  .loading-text { font-size: 16px; }
  .loading-hint { font-size: 12px; }
}
</style>
