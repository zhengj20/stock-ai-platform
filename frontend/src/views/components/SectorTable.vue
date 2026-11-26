<template>
  <div class="sector-panel">
    <div class="panel-header">
      <span>{{ title }}</span>
      <slot name="header-actions"></slot>
    </div>
    <div class="panel-table-wrap" v-loading="loading && items.length > 0">
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>{{ columns[0] }}</th>
            <th>{{ columns[1] }}</th>
            <th>{{ columns[2] }}</th>
            <th v-if="showFlow">{{ columns[3] }}</th>
          </tr>
        </thead>
        <tbody>
          <!-- 骨架屏：首次加载（无数据）时显示 -->
          <template v-if="loading && items.length === 0">
            <tr v-for="i in 8" :key="'sk-'+i" class="skeleton-row">
              <td class="rank"><el-skeleton-item variant="text" style="width: 16px;" /></td>
              <td><el-skeleton-item variant="text" style="width: 80px;" /></td>
              <td><el-skeleton-item variant="text" style="width: 50px;" /></td>
              <td><el-skeleton-item variant="text" style="width: 45px;" /></td>
              <td v-if="showFlow"><el-skeleton-item variant="text" style="width: 45px;" /></td>
            </tr>
          </template>
          <!-- 空数据：非加载中且无数据时显示 -->
          <tr v-else-if="items.length === 0" class="empty-row">
            <td :colspan="showFlow ? 5 : 4" class="empty-cell">
              <span class="empty-text">暂无数据</span>
            </td>
          </tr>
          <!-- 正常数据 -->
          <tr v-else v-for="(item, i) in items" :key="i"
              :class="changeClass(item.change_pct)">
            <td class="rank">{{ i + 1 }}</td>
            <td>{{ item.name }}</td>
            <td :class="pctClass(item.change_pct)" class="pct">
              {{ item.change_pct > 0 ? '+' : '' }}{{ item.change_pct?.toFixed(2) }}%
            </td>
            <td :class="pctClass(item.flow_net)">
              {{ (item.flow_net || 0) > 0 ? '+' : '' }}{{ (item.flow_net || 0).toFixed(1) }}
            </td>
            <td v-if="showFlow">{{ (item.turnover || 0).toFixed(1) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
// change_pct > 0 视为涨（红），< 0 视为跌（绿），== 0 平盘用默认色
const changeClass = (v) => v > 0 ? 'row-up' : v < 0 ? 'row-down' : ''
const pctClass = (v) => v > 0 ? 'c-red' : v < 0 ? 'c-green' : ''

defineProps({
  title: { type: String, required: true },
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  // 默认：板块名、涨跌幅、净额(亿)【showFlow=true 时再加成交额(亿)】
  columns: { type: Array, default: () => ['板块', '涨跌幅', '净额(亿)', '成交额(亿)'] },
  showFlow: { type: Boolean, default: false }
})
</script>

<style scoped>
.sector-panel {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid #ebeef5;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.panel-table-wrap {
  max-height: 320px;
  overflow-y: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.data-table th {
  position: sticky; top: 0; background: #f5f7fa; padding: 8px 6px;
  text-align: left; color: #909399; font-weight: 500; border-bottom: 1px solid #ebeef5;
}
.data-table td {
  padding: 7px 6px; border-bottom: 1px solid #f2f3f5;
}
.data-table .rank { color: #909399; width: 30px; }
.data-table .pct { font-weight: 600; }
.data-table tr:hover td { background: #fafafa; }
.row-up td:first-child { border-left: 2px solid #f56c6c; }
.row-down td:first-child { border-left: 2px solid #67c23a; }

.c-red { color: #f56c6c !important; font-weight: 600; }
.c-green { color: #67c23a !important; font-weight: 600; }

.skeleton-row td { padding: 9px 6px; border-bottom: 1px solid #f2f3f5; }

.empty-row td { padding: 0; }
.empty-cell {
  text-align: center;
  padding: 36px 0 !important;
  background: #fafbfc;
  border-bottom: none;
}
.empty-text {
  color: #c0c4cc;
  font-size: 12px;
  letter-spacing: 0.3px;
}

@media (max-width: 768px) {
  .panel-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .data-table {
    min-width: 500px;
    font-size: 12px;
    table-layout: fixed;
  }
  .data-table th,
  .data-table td {
    word-break: keep-all;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
</style>
