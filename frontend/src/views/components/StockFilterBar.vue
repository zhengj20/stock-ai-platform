<template>
  <div class="tab-filter-bar">
    <span class="filter-label">筛选条件</span>
    <div class="filter-grid">
      <!-- 数量选择 -->
      <span v-if="showTopN" class="filter-item">
        <label>数量</label>
        <el-input-number v-model="localFilters.topN" :min="5" :max="100" size="small" controls-position="right" @update:model-value="emitChange" />
      </span>

      <!-- 市值筛选 -->
      <span v-if="showMarketCap" class="filter-item">
        <label>市值</label>
        <el-select v-model="localFilters.marketCap" size="small" @change="emitChange">
          <el-option label="全部" value="all" />
          <el-option label="大盘" value="large" />
          <el-option label="中盘" value="mid" />
          <el-option label="小盘" value="small" />
        </el-select>
      </span>

      <!-- 成交额筛选 -->
      <span v-if="showMinAmount" class="filter-item">
        <label>成交额</label>
        <el-select v-model="localFilters.minAmount" size="small" @change="emitChange">
          <el-option label="不限" :value="0" />
          <el-option label="≥1000万" :value="1000" />
          <el-option label="≥5000万" :value="5000" />
          <el-option label="≥1亿" :value="10000" />
          <el-option label="≥5亿" :value="50000" />
        </el-select>
      </span>

      <!-- 涨跌幅筛选 -->
      <span v-if="showChangeRange" class="filter-item">
        <label>涨跌幅</label>
        <el-select v-model="localFilters.changeRange" size="small" @change="emitChange">
          <el-option label="不限" value="all" />
          <el-option label="排涨停" value="no_limit_up" />
          <el-option label="排跌停" value="no_limit_down" />
          <el-option label="排停" value="no_limit" />
          <el-option label="仅上涨" value="up" />
          <el-option label="仅下跌" value="down" />
        </el-select>
      </span>

      <!-- 排除ST -->
      <span v-if="showExcludeSt" class="filter-item">
        <label>排除ST</label>
        <el-checkbox v-model="localFilters.excludeST" size="small" @change="emitChange" />
      </span>

      <!-- 自定义插槽（龙虎榜策略类型、组合模式等） -->
      <slot />

      <!-- 操作按钮 -->
      <span class="filter-buttons">
        <el-button type="primary" size="small" @click="emitChange">开始筛选</el-button>
        <el-button type="info" size="small" @click="resetFilters">重置</el-button>
      </span>
    </div>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  defaults: { type: Object, default: () => ({ topN: 20, marketCap: 'all', minAmount: 0, changeRange: 'all', excludeST: true }) },
  showTopN: { type: Boolean, default: true },
  showMarketCap: { type: Boolean, default: false },
  showMinAmount: { type: Boolean, default: false },
  showChangeRange: { type: Boolean, default: false },
  showExcludeSt: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const localFilters = reactive({ ...props.defaults, ...props.modelValue })

watch(() => props.modelValue, (newVal) => {
  Object.assign(localFilters, newVal)
}, { deep: true })

function emitChange() {
  emit('update:modelValue', { ...localFilters })
  emit('change', { ...localFilters })
}

function resetFilters() {
  const defaults = { ...props.defaults }
  Object.assign(localFilters, defaults)
  emit('update:modelValue', { ...defaults })
  emit('change', { ...defaults })
}
</script>

<style scoped>
.tab-filter-bar {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 10px 0;
  margin-bottom: 8px;
  border-bottom: 1px dashed #ebeef5;
}

.filter-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  flex-shrink: 0;
  height: 32px;
  line-height: 32px;
}

.filter-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.filter-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.filter-item label {
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
  flex-shrink: 0;
}

.filter-item :deep(.el-input-number) { width: 100px; }
.filter-item :deep(.el-input-number .el-input__wrapper) { padding: 1px 28px 1px 6px; }
.filter-item :deep(.el-select) { width: 100px; }

.filter-buttons {
  display: inline-flex;
  gap: 6px;
  margin-left: auto;
  flex-shrink: 0;
}

.dragon-type-group { flex-shrink: 0; }

@media (max-width: 768px) {
  .tab-filter-bar {
    gap: 2px 4px;
    padding: 4px 0;
    margin-bottom: 4px;
  }

  .filter-label {
    width: 100%;
    height: auto;
    line-height: normal;
    margin-bottom: 0;
    font-size: 11px;
  }

  .filter-grid {
    display: grid !important;
    grid-template-columns: repeat(3, 1fr) !important;
    gap: 4px !important;
  }

  .filter-item {
    display: inline-flex !important;
    align-items: center !important;
    gap: 3px !important;
    width: 100% !important;
    min-width: 0 !important;
    overflow: hidden !important;
  }

  .filter-item label {
    font-size: 10px;
    flex-shrink: 0 !important;
    white-space: nowrap !important;
    width: auto !important;
  }

  .filter-item :deep(.el-input-number),
  .filter-item :deep(.el-select) {
    flex: 1 !important;
    min-width: 0 !important;
    width: auto !important;
  }

  .filter-item :deep(.el-input__wrapper) {
    padding: 0px 20px 0px 6px !important;
    box-shadow: 0 0 0 1px #dcdfe6 inset !important;
    height: 28px !important;
    min-width: 0 !important;
  }

  .filter-item :deep(.el-select .el-input__wrapper) {
    padding: 0px 20px 0px 6px !important;
    height: 28px !important;
    min-width: 0 !important;
  }

  .filter-buttons {
    grid-column: 1 / -1 !important;
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
    padding-top: 4px;
  }

  .filter-buttons :deep(.el-button) {
    flex: 1;
    min-height: 28px;
    font-size: 11px;
    padding: 4px 6px;
  }
}

@media (max-width: 480px) {
.filter-item label {
font-size: 9px !important;
}

  .filter-buttons :deep(.el-button) {
    min-height: 30px;
    font-size: 11px;
    padding: 5px 6px;
  }
}
</style>
