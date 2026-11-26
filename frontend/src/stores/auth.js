import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const AUTH_BASE = '/api/v1/auth'

// 创建独立的axios实例，不受api/index.js拦截器影响
const authAxios = axios.create({
  baseURL: '',
  timeout: 30000,
})

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const accessToken = ref(localStorage.getItem('gp_access_token') || '')
  const refreshToken = ref(localStorage.getItem('gp_refresh_token') || '')
  const expiryStartDate = ref(localStorage.getItem('gp_expiry_start_date') || null)
  const expiryDate = ref(localStorage.getItem('gp_expiry_date') || null)

  const isLoggedIn = computed(() => !!accessToken.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  // 计算剩余天数（每次调用实时计算，不依赖computed缓存）
  function getRemainingDays() {
    if (!expiryDate.value) return null
    const now = new Date()
    const expiry = new Date(expiryDate.value)
    const diff = expiry - now
    const days = Math.ceil(diff / (1000 * 60 * 60 * 24))
    return days > 0 ? days : 0
  }

  // 是否已过期（每次调用实时计算）
  function getIsExpired() {
    const days = getRemainingDays()
    return days !== null && days <= 0
  }

  function setTokens(access, refresh, expiryStart, expiry) {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('gp_access_token', access)
    localStorage.setItem('gp_refresh_token', refresh)
    if (expiryStart) {
      expiryStartDate.value = expiryStart
      localStorage.setItem('gp_expiry_start_date', expiryStart)
    } else {
      expiryStartDate.value = null
      localStorage.removeItem('gp_expiry_start_date')
    }
    if (expiry) {
      expiryDate.value = expiry
      localStorage.setItem('gp_expiry_date', expiry)
    } else {
      expiryDate.value = null
      localStorage.removeItem('gp_expiry_date')
    }
  }

  function clearAuth() {
    user.value = null
    accessToken.value = ''
    refreshToken.value = ''
    expiryStartDate.value = null
    expiryDate.value = null
    localStorage.removeItem('gp_access_token')
    localStorage.removeItem('gp_refresh_token')
    localStorage.removeItem('gp_expiry_start_date')
    localStorage.removeItem('gp_expiry_date')
  }

  async function login(username, password) {
    const formData = new URLSearchParams()
    formData.append('username', username)
    formData.append('password', password)

    try {
      const response = await authAxios.post(`${AUTH_BASE}/login`, formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })

      const data = response.data
      setTokens(data.access_token, data.refresh_token, data.expiry_start_date, data.expiry_date)
      user.value = {
        id: data.user_id,
        username: data.username,
        role: data.role,
      }
      return data
    } catch (error) {
      console.error('登录请求失败:', error.response?.data || error.message)
      throw error
    }
  }

  async function register(username, email, password, inviteCode) {
    const response = await authAxios.post(`${AUTH_BASE}/register`, {
      username,
      email,
      password,
      invite_code: inviteCode,
    })

    const data = response.data
    setTokens(data.access_token, data.refresh_token, data.expiry_start_date, data.expiry_date)
    user.value = {
      id: data.user_id,
      username: data.username,
      role: data.role,
    }
    return data
  }

  async function fetchUserInfo() {
    if (!accessToken.value) return false

    try {
      const response = await authAxios.get(`${AUTH_BASE}/me`, {
        headers: { Authorization: `Bearer ${accessToken.value}` },
      })
      user.value = response.data
      if (response.data.expiry_start_date) {
        expiryStartDate.value = response.data.expiry_start_date
        localStorage.setItem('gp_expiry_start_date', response.data.expiry_start_date)
      } else {
        expiryStartDate.value = null
        localStorage.removeItem('gp_expiry_start_date')
      }
      if (response.data.expiry_date) {
        expiryDate.value = response.data.expiry_date
        localStorage.setItem('gp_expiry_date', response.data.expiry_date)
      } else {
        expiryDate.value = null
        localStorage.removeItem('gp_expiry_date')
      }
      return true
    } catch {
      clearAuth()
      return false
    }
  }

  async function refreshTokenIfNeeded() {
    if (!refreshToken.value) return false

    try {
      const response = await authAxios.post(`${AUTH_BASE}/refresh`, {
        refresh_token: refreshToken.value,
      })
      accessToken.value = response.data.access_token
      localStorage.setItem('gp_access_token', accessToken.value)
      return true
    } catch {
      clearAuth()
      return false
    }
  }

  async function logout() {
    clearAuth()
  }

  // 初始化：检查本地token是否有效
  let _initPromise = null
  async function initAuth() {
    if (_initPromise) return _initPromise
    _initPromise = (async () => {
      if (accessToken.value) {
        const valid = await fetchUserInfo()
        if (!valid) {
          await refreshTokenIfNeeded()
        }
      }
    })()
    await _initPromise
    _initPromise = null
  }

  return {
    user,
    accessToken,
    isLoggedIn,
    isAdmin,
    expiryStartDate,
    expiryDate,
    remainingDays: getRemainingDays,
    isExpired: getIsExpired,
    login,
    register,
    logout,
    fetchUserInfo,
    initAuth,
    clearAuth,
  }
})
