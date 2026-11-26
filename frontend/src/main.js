import { createApp, h, computed, defineComponent } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { ElTable } from 'element-plus'

import App from './App.vue'
import router from './router'

const app = createApp(App)

// Vue 全局错误处理：捕获组件级错误，避免整页白屏
app.config.errorHandler = (err, instance, info) => {
  console.error('[Vue Error]', info, err)
}

// 捕获未处理的 Promise 拒绝（如 async setup 内的异常）
app.config.warnHandler = (msg, instance, trace) => {
  if (import.meta.env.DEV) {
    console.warn('[Vue Warn]', msg, trace)
  }
}

window.addEventListener('unhandledrejection', (e) => {
  console.error('[Unhandled Promise Rejection]', e.reason)
  e.preventDefault()
})

// 注册所有Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 安全包装 ElTable：确保 data prop 永远是数组
// 修复 Element Plus 内部 updateAllSelected / table-body reduce 在 data 为非数组时的崩溃
const SafeElTable = defineComponent({
  name: 'ElTable',
  props: ElTable.props,
  setup(props, { slots, attrs }) {
    const safeData = computed(() => {
      const d = props.data
      return Array.isArray(d) ? d : (d || [])
    })
    return () => h(ElTable, { ...attrs, data: safeData.value }, slots)
  },
})

// 直接覆盖已注册的 ElTable，避免 app.component 重复注册警告
app._context.components.ElTable = SafeElTable

app.mount('#app')
