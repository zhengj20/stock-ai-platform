<template>
  <div class="register-container">
    <div class="register-card">
      <div class="logo-area">
        <el-icon :size="40" color="#409EFF"><TrendCharts /></el-icon>
        <h1>注册新账号</h1>
        <p class="subtitle">需要管理员发放的邀请码才能注册</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        @keyup.enter="handleRegister"
      >
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名（2-50个字符）"
            prefix-icon="User"
          />
        </el-form-item>

        <el-form-item prop="email">
          <el-input
            v-model="form.email"
            placeholder="邮箱地址"
            prefix-icon="Message"
          />
        </el-form-item>

        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码（至少6个字符）"
            prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-form-item prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="确认密码"
            prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-form-item prop="inviteCode">
          <el-input
            v-model="form.inviteCode"
            placeholder="邀请码（16位）"
            prefix-icon="Ticket"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            class="register-btn"
            @click="handleRegister"
          >
            {{ loading ? '注册中...' : '注 册' }}
          </el-button>
        </el-form-item>

        <div class="footer-link">
          已有账号？
          <router-link to="/login">返回登录</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  inviteCode: '',
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '长度2-50个字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '至少6个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
  inviteCode: [
    { required: true, message: '请输入邀请码', trigger: 'blur' },
  ],
}

async function handleRegister() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.register(
      form.username,
      form.email,
      form.password,
      form.inviteCode,
    )
    ElMessage.success('注册成功，欢迎加入！')
    router.push('/market')
  } catch (e) {
    const msg = e.response?.data?.detail || '注册失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}

.register-card {
  width: 460px;
  padding: 40px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.logo-area {
  text-align: center;
  margin-bottom: 32px;
}

.logo-area h1 {
  font-size: 24px;
  color: #1a1a2e;
  margin: 12px 0 8px;
}

.subtitle {
  color: #666;
  font-size: 13px;
}

.register-btn {
  width: 100%;
}

.footer-link {
  text-align: center;
  color: #999;
  font-size: 14px;
}

.footer-link a {
  color: #409EFF;
  text-decoration: none;
}

.footer-link a:hover {
  text-decoration: underline;
}

@media (max-width: 768px) {
  .register-card {
    width: calc(100% - 32px);
    padding: 28px 20px;
  }
  .logo-area h1 { font-size: 20px; }
}

@media (max-width: 480px) {
  .register-card {
    width: calc(100% - 24px);
    padding: 24px 16px;
    border-radius: 12px;
  }
  .logo-area h1 { font-size: 18px; }
  .subtitle { font-size: 12px; }
}
</style>
