/**
 * useTableFit - 强制 el-table 内部列宽按容器比例分配
 *
 * 解决 Element Plus 2.8 el-table 列宽固定 px 导致右侧大片留白的问题：
 * - 默认 fit=true 时列宽按 colgroup 中 col width (px) 设置
 * - 列总宽 < 容器宽时，列集中在左侧，右侧大片空白
 * - 本 hook 启动后把所有 col width 改为百分比，让列按比例填满容器
 *
 * 用法：
 *   useTableFit('.section .el-table')  // 传入选择器
 *   useTableFit()                        // 默认作用于 .el-table
 */
import { onMounted, onBeforeUnmount, onActivated, nextTick } from 'vue'

export function useTableFit(selector = '.el-table') {
  let observer = null
  let resizeHandler = null
  const containerObservers = new Map()

  const fitToContainer = () => {
    // 移动端不执行百分比适配，避免破坏 min-width 横向滚动布局
    if (window.innerWidth < 768) return

    const tables = document.querySelectorAll(selector)
    tables.forEach(t => {
      const parent = t.parentElement
      if (!parent) return
      const parentWidth = parent.getBoundingClientRect().width
      if (parentWidth < 100) return

      // 跳过有固定列的表格（fixed="left"/fixed="right"），el-table 固定列与百分比列宽不兼容
      const wrapper = t.closest('.el-table') || t
      if (wrapper.querySelector('.el-table__fixed-right, .el-table__fixed-left, .el-table__fixed')) {
        return
      }

      // 跳过设置了 :height 的表格（Element Plus 固定表头+滚动模式），避免破坏滚动布局
      const innerWrapper = t.querySelector('.el-table__inner-wrapper')
      if (innerWrapper && innerWrapper.style.height) return
      // 跳过标记了 data-no-fit 的表格，并清理之前可能已应用的样式
      if (t.closest('[data-no-fit]')) {
        t.style.removeProperty('display')
        t.style.removeProperty('box-sizing')
        t.querySelectorAll('table').forEach(tb => {
          tb.querySelectorAll('colgroup col').forEach(c => c.style.removeProperty('width'))
        })
        return
      }

      // 跳过设置了 min-width 的表格（通常是移动端横向滚动场景）
      const computedMinWidth = getComputedStyle(t).minWidth
      if (computedMinWidth !== '0px' && computedMinWidth !== 'none') {
        return
      }

      t.style.width = '100%'
      t.style.maxWidth = '100%'
      t.style.minWidth = '0'
      t.style.boxSizing = 'border-box'

      const innerWrappers = t.querySelectorAll('.el-table__inner-wrapper, .el-table__header-wrapper, .el-table__body-wrapper, .el-scrollbar')
      innerWrappers.forEach(w => {
        w.style.width = '100%'
        w.style.maxWidth = '100%'
        w.style.minWidth = '0'
      })

      const tableEls = t.querySelectorAll('table')
      tableEls.forEach(tb => {
        const cols = tb.querySelectorAll('colgroup col')
        if (cols.length === 0) return

        let totalColWidth = 0
        const colWidths = []
        cols.forEach(c => {
          const w = parseFloat(c.getAttribute('width')) || 60
          colWidths.push(w)
          totalColWidth += w
        })
        if (totalColWidth === 0) return

        cols.forEach((c, i) => {
          const pct = (colWidths[i] / totalColWidth * 100).toFixed(3) + '%'
          c.style.width = pct
        })

        tb.style.width = '100%'
        tb.style.minWidth = '0'
        tb.style.maxWidth = '100%'
        tb.style.tableLayout = 'fixed'
        tb.removeAttribute('width')
      })

      // 为每个表格的父容器挂载 ResizeObserver，容器尺寸变化时自动重新适配
      if (!containerObservers.has(t) && typeof ResizeObserver !== 'undefined') {
        const ro = new ResizeObserver(() => fitToContainer())
        ro.observe(parent)
        containerObservers.set(t, ro)
      }
    })
  }

  const start = () => {
    nextTick(() => {
      // 多次尝试，确保侧边栏 margin-left transition 完成后也能适配
      fitToContainer()
      setTimeout(fitToContainer, 150)
      setTimeout(fitToContainer, 400)

      // 监听 DOM 变化（数据更新时重新计算）
      if (observer) observer.disconnect()
      observer = new MutationObserver(() => fitToContainer())
      document.querySelectorAll(selector).forEach(t => {
        // 不监听 data-no-fit 容器内的表格
        if (t.closest('[data-no-fit]')) return
        observer.observe(t, { childList: true, subtree: true, attributes: true })
      })

      // 窗口大小变化时重新适配
      if (resizeHandler) window.removeEventListener('resize', resizeHandler)
      resizeHandler = () => fitToContainer()
      window.addEventListener('resize', resizeHandler)
    })
  }

  onMounted(() => {
    start()
  })

  // keep-alive 切回时重新适配
  onActivated(() => {
    nextTick(() => {
      fitToContainer()
      setTimeout(fitToContainer, 150)
    })
  })

  onBeforeUnmount(() => {
    if (observer) observer.disconnect()
    if (resizeHandler) window.removeEventListener('resize', resizeHandler)
    // 清理容器 ResizeObserver
    containerObservers.forEach(ro => ro.disconnect())
    containerObservers.clear()
  })

  return { fitToContainer }
}
