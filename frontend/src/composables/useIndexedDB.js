/**
 * IndexedDB 缓存存储层（替代 localStorage）
 * v3: 清理旧缓存 + 新闻类强制TTL检查
 */

const DB_NAME = 'gp-cache-v4'
const STORE_NAME = 'entries'
const DB_VERSION = 1

// 容量限制（字节）- 约 40MB，留余量防止浏览器配额耗尽
const MAX_DB_SIZE_BYTES = 40 * 1024 * 1024

let dbPromise = null

function toPlainData(obj) {
  if (obj == null || typeof obj !== 'object') return obj
  if (Array.isArray(obj)) return obj.map(toPlainData)
  const result = {}
  for (const k of Object.keys(obj)) {
    result[k] = toPlainData(obj[k])
  }
  return result
}

function getDB() {
  if (!dbPromise) {
    dbPromise = openDB()
    // 清理旧版本数据库
    clearOldDB().catch(() => {})
  }
  return dbPromise
}

async function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = (e) => {
      const db = e.target.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' })
        store.createIndex('prefix', 'id', { unique: false })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

/**
 * 清理旧版本数据库（gp-cache-v1, gp-cache-v2）
 */
async function clearOldDB() {
  if (!isSupported()) return
  try {
    const oldDbNames = ['gp-cache-v1', 'gp-cache-v2', 'gp-cache-v3']
    for (const name of oldDbNames) {
      const checkReq = indexedDB.open(name)
      await new Promise((resolve) => {
        checkReq.onsuccess = () => {
          checkReq.result.close()
          indexedDB.deleteDatabase(name)
          console.log(`[IndexedDB] 已清理旧缓存: ${name}`)
          resolve()
        }
        checkReq.onerror = () => resolve()
      })
    }
  } catch {}
}

function isSupported() {
  try {
    return typeof indexedDB !== 'undefined' && indexedDB.open
  } catch {
    return false
  }
}

// ── 容量管理 ───────────────────────────────

// 5 分钟内复用上次清理结果，避免每次 writeDB 都跑全表 cursor
let _lastCleanupAt = 0
const CLEANUP_THROTTLE_MS = 5 * 60 * 1000

async function checkAndCleanupCapacity() {
  if (!isSupported()) return
  // 跳过节流窗口内的清理
  if (Date.now() - _lastCleanupAt < CLEANUP_THROTTLE_MS) return
  _lastCleanupAt = Date.now()
  try {
    const db = await getDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const now = Date.now()
    let cleaned = 0

    // 第一步：清理过期数据（TTL 已过）
    const cursorReq = store.openCursor()
    await new Promise((resolve) => {
      cursorReq.onsuccess = (e) => {
        const cursor = e.target.result
        if (!cursor) return resolve()
        const record = cursor.value
        if (record && now - record.timestamp > record.ttl) {
          cursor.delete()
          cleaned++
        }
        cursor.continue()
      }
    })

    // 第二步：如果记录数过多（>500条），淘汰最旧的 20%
    const countReq = store.count()
    let totalRecords = 0
    await new Promise((resolve) => {
      countReq.onsuccess = () => {
        totalRecords = countReq.result
        resolve()
      }
    })

    if (totalRecords > 500) {
      const allKeys = []
      const cursorReq2 = store.openCursor()
      await new Promise((resolve) => {
        cursorReq2.onsuccess = (e) => {
          const cursor = e.target.result
          if (!cursor) return resolve()
          allKeys.push({ id: cursor.value.id, timestamp: cursor.value.timestamp })
          cursor.continue()
        }
      })

      allKeys.sort((a, b) => a.timestamp - b.timestamp)
      const toDelete = Math.floor(allKeys.length * 0.2)
      for (let i = 0; i < toDelete; i++) {
        store.delete(allKeys[i].id)
        cleaned++
      }
    }

    if (cleaned > 0) {
      console.log(`[IndexedDB] 容量管理: 清理 ${cleaned} 条记录`)
    }
  } catch (e) {
    console.warn('[IndexedDB] 容量检查失败:', e?.message)
  }
}

// ── IndexedDB 操作 ───────────────────────────────

async function readFromDB(key) {
  if (!isSupported()) return null
  try {
    const db = await getDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const req = store.get(key)
      req.onsuccess = () => resolve(req.result || null)
      req.onerror = () => resolve(null)
    })
  } catch (e) {
    console.warn('[IndexedDB] read 失败:', key, e?.message)
    return null
  }
}

async function writeDB(key, data, ttl) {
  if (!isSupported()) return false
  try {
    await checkAndCleanupCapacity()
    const safeData = toPlainData(data)

    const db = await getDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      store.put({ id: key, data: safeData, timestamp: Date.now(), ttl })
      tx.oncomplete = () => resolve(true)
      tx.onerror = () => resolve(false)
    })
  } catch (e) {
    if (e?.name === 'QuotaExceededError') {
      await checkAndCleanupCapacity()
      try {
        const db = await getDB()
        return new Promise((resolve) => {
          const tx = db.transaction(STORE_NAME, 'readwrite')
          const store = tx.objectStore(STORE_NAME)
          store.put({ id: key, data: toPlainData(data), timestamp: Date.now(), ttl })
          tx.oncomplete = () => resolve(true)
          tx.onerror = () => resolve(false)
        })
      } catch (e) {
        console.warn('[IndexedDB] write 重试失败:', key, e?.message)
        return false
      }
    }
    console.warn('[IndexedDB] write 失败:', key, e?.message)
    return false
  }
}

async function clearDB(key) {
  if (!isSupported()) return
  try {
    const db = await getDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).delete(key)
  } catch (e) {
    console.warn('[IndexedDB] clear 失败:', key, e?.message)
  }
}

async function clearAllDB(prefix = '') {
  if (!isSupported()) return 0
  try {
    const db = await getDB()
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const countReq = store.count()
      countReq.onsuccess = () => {
        const cursorReq = store.openCursor()
        let deleted = 0
        cursorReq.onsuccess = (e) => {
          const cursor = e.target.result
          if (!cursor) return
          const recordKey = cursor.value.id || ''
          if (!prefix || recordKey.startsWith(prefix)) {
            cursor.delete()
            deleted++
          }
          cursor.continue()
        }
        tx.oncomplete = () => resolve(deleted)
      }
    })
  } catch (e) {
    console.warn('[IndexedDB] clearAll 失败:', prefix, e?.message)
    return 0
  }
}

// ── localStorage 降级操作（保留但不主动读取旧数据）──

const STORAGE_PREFIX = 'gp_cache_v3:'

function readFromStorage(key) {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    if (Date.now() - parsed.timestamp > parsed.ttl) {
      localStorage.removeItem(STORAGE_PREFIX + key)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function writeStorage(key, data, ttl) {
  try {
    localStorage.setItem(
      STORAGE_PREFIX + key,
      JSON.stringify({ data, timestamp: Date.now(), ttl })
    )
  } catch (e) {
    console.warn('[useCachedFetch] storage write failed:', e?.message)
  }
}

function clearStorage(key) {
  try { localStorage.removeItem(STORAGE_PREFIX + key) } catch {}
}

function clearAllStorage(prefix = '') {
  try {
    const keys = Object.keys(localStorage).filter(k => {
      if (!k.startsWith(STORAGE_PREFIX)) return false
      if (!prefix) return true
      const cacheKey = k.slice(STORAGE_PREFIX.length)
      return cacheKey.startsWith(prefix)
    })
    keys.forEach(k => localStorage.removeItem(k))
    return keys.length
  } catch {}
  return 0
}

// ── 统一对外接口（优先 IndexedDB，降级 localStorage）──

export async function readCache(key) {
  const dbResult = await readFromDB(key)
  if (dbResult) {
    // 新闻类缓存强制检查TTL，防止旧数据残留
    const isNewsCache = key.startsWith('news:')
    if (isNewsCache || Date.now() - dbResult.timestamp > dbResult.ttl) {
      clearDB(key).catch(() => {})
      return null
    }
    return dbResult
  }
  // localStorage 降级（不读取旧版本前缀的数据）
  const storageResult = readFromStorage(key)
  if (storageResult) {
    writeDB(key, storageResult.data, storageResult.ttl).catch(() => {})
    return storageResult
  }
  return null
}

/**
 * 读取stale缓存（不检查TTL，即使过期也返回）
 * 新闻类缓存：超过2小时的视为无效
 */
export async function readStaleCache(key) {
  const dbResult = await readFromDB(key)
  if (dbResult) {
    // 新闻类缓存：即使stale也检查是否超过2小时，防止显示过旧数据
    const isNewsCache = key.includes('news:')
    if (isNewsCache && Date.now() - dbResult.timestamp > 2 * 60 * 60 * 1000) {
      return null  // 超过2小时的新闻缓存视为无效
    }
    return dbResult
  }
  return null
}

export async function writeCache(key, data, ttl) {
  await writeDB(key, data, ttl)
}

export async function clearCache(key) {
  await clearDB(key)
}

export async function clearAllCache(prefix = '') {
  await clearAllDB(prefix)
}
