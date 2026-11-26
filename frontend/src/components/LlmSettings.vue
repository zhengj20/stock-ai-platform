<template>
  <div class="llm-settings">
    <h3><el-icon><Setting /></el-icon> AI助手配置</h3>

    <!-- Quick connect — only shown when LM Studio is reachable but not yet enabled -->
    <div class="quick-connect" v-if="!config.enabled && connectionOk">
      <el-alert type="success" :closable="false" show-icon>
        <template #title>服务已检测到，点击下方按钮一键启用 AI助手</template>
        <el-button type="primary" size="default" @click="enableNow" :loading="connecting" style="margin-top: 8px;">🚀 立即启用</el-button>
      </el-alert>
    </div>

    <el-form :model="config" label-width="120px" size="default">
      <el-form-item label="启用AI助手">
        <el-switch v-model="config.enabled" @change="saveConfig" />
      </el-form-item>

      <el-form-item label="服务类型">
        <el-select v-model="config.provider" style="width:100%" @change="onProviderChange">
          <el-option label="LM Studio（本地）" value="lm-studio" />
          <el-option label="vLLM（远程）" value="vllm" />
          <el-option label="自定义" value="custom" />
        </el-select>
      </el-form-item>

      <el-form-item label="API地址">
        <el-input v-model="config.base_url" placeholder="http://localhost:1234/v1" />
      </el-form-item>

      <el-form-item label="模型名称">
        <el-select v-model="config.model" filterable allow-create placeholder="自动检测或手动输入" style="width:100%">
          <el-option v-for="m in availableModels" :key="m" :label="m" :value="m" />
        </el-select>
      </el-form-item>

      <el-form-item label="Temperature">
        <el-slider v-model="config.temperature" :min="0" :max="2" :step="0.1" show-input />
      </el-form-item>

      <el-form-item label="最大Token">
        <el-input-number v-model="config.max_tokens" :min="256" :max="32768" :step="256" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
        <el-button @click="testConnection" :loading="testing">测试连接</el-button>
      </el-form-item>
    </el-form>

    <div v-if="testResult" class="test-result" :class="testResult.connected ? 'success' : 'error'">
      <p><strong>{{ testResult.connected ? '✓ 连接成功' : '✗ 连接失败' }}</strong></p>
      <p v-if="!testResult.connected && testResult.error">{{ testResult.error }}</p>
      <p v-if="testResult.models?.length">可用模型: {{ testResult.models.join(', ') }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { chatApi } from '@/api'

const config = ref({ base_url: '', model: '', temperature: 0.7, max_tokens: 8192, enabled: false, provider: 'custom' })
const availableModels = ref([])
const saving = ref(false)
const testing = ref(false)
const connecting = ref(false)
const testResult = ref(null)

// Derived: LM Studio reachable but AI assistant not yet enabled
const connectionOk = computed(() => testResult.value?.connected === true)

const PROVIDER_URLS = {
  'lm-studio': 'http://localhost:1234/v1',
  'vllm': 'http://172.24.15.148:8000/v1',
}

function onProviderChange(provider) {
  if (provider !== 'custom') {
    config.value.base_url = PROVIDER_URLS[provider]
  }
}

onMounted(async () => {
  await loadConfig()
  // Auto-detect on mount — result reused by quick-connect button
  await testConnection()
})

async function loadConfig() {
  try {
    config.value = await chatApi.getConfig()
  } catch {}
}

const emit = defineEmits(['saved'])

async function saveConfig() {
  saving.value = true
  try {
    const data = await chatApi.updateConfig(config.value)
    config.value = data.config
    ElMessage.success('配置已保存')
    emit('saved')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e.detail || String(e)))
    console.error('[LlmSettings] saveConfig error:', e)
  } finally { saving.value = false }
}

async function testConnection() {
  testing.value = true
  try {
    const result = await chatApi.testConnection()
    testResult.value = result
    if (result.connected && result.models?.length) {
      availableModels.value = result.models
      // Auto-fill model from detection if not set
      if (!config.value.model && result.default_model) {
        config.value.model = result.default_model
      }
      ElMessage.success('连接成功，检测到 ' + result.models.length + ' 个模型')
    } else if (!result.connected) {
      testResult.value = { connected: false, error: result.error || '连接失败' }
      ElMessage.warning('连接失败：' + (result.error || '未知错误'))
    }
  } catch (e) {
    testResult.value = { connected: false, error: e.message || '连接失败' }
    ElMessage.error('测试连接出错')
  } finally { testing.value = false }
}

// Reuses the connection result from onMounted — no duplicate API call
async function enableNow() {
  connecting.value = true
  try {
    const newConfig = {
      base_url: config.value.base_url || PROVIDER_URLS['lm-studio'],
      model: testResult.value?.default_model || config.value.model,
      enabled: true,
      temperature: config.value.temperature,
      max_tokens: config.value.max_tokens,
      provider: config.value.provider,
    }
    const data = await chatApi.updateConfig(newConfig)
    config.value = data.config
    ElMessage.success('🚀 AI助手已启用！')
    emit('saved')
  } catch (e) {
    ElMessage.error('启用失败: ' + (e.message || e.detail || String(e)))
    console.error('[LlmSettings] enableNow error:', e)
  } finally { connecting.value = false }
}
</script>

<style scoped>
.llm-settings {
  padding: 20px;
  background: #fff;
  border-radius: 8px;
}

h3 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  color: #303133;
  font-size: 16px;
  font-weight: 600;
}

h3 .el-icon {
  color: #409eff;
}

/* Quick connect */
.quick-connect {
  margin-bottom: 20px;
  animation: fadeInUp 0.3s ease;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Form overrides */
:deep(.el-form-item) {
  margin-bottom: 20px;
}

:deep(.el-form-item__label) {
  color: #606266;
  font-weight: 500;
}

:deep(.el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #dcdfe6 inset;
  transition: all 0.25s;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c0c4cc inset;
}

:deep(.el-input.is-focus .el-input__wrapper) {
  box-shadow: 0 0 0 1px #409eff inset;
}

:deep(.el-select .el-input__wrapper) {
  border-radius: 8px;
}

/* Slider */
:deep(.el-slider__runway) {
  height: 6px;
  border-radius: 3px;
}

:deep(.el-slider__bar) {
  background: linear-gradient(90deg, #409eff, #66b1ff);
  border-radius: 3px;
}

/* Buttons */
:deep(.el-button--primary) {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  border: none;
  border-radius: 8px;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.3);
  transition: all 0.25s;
}

:deep(.el-button--primary:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(64, 158, 255, 0.4);
}

/* Test result */
.test-result {
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: 8px;
  font-size: 13px;
  animation: fadeInUp 0.3s ease;
}

.test-result p {
  margin: 4px 0;
}

.test-result.success {
  background: linear-gradient(90deg, #f0f9eb, #f6ffed);
  color: #67c23a;
  border: 1px solid #e1f3d8;
}

.test-result.error {
  background: linear-gradient(90deg, #fef0f0, #fff5f5);
  color: #f56c6c;
  border: 1px solid #fde2e2;
}
</style>