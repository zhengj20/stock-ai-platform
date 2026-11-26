/**
 * A股交易时间判断工具
 */

/**
 * 判断是否为周末（0=周日, 6=周六）
 */
export function isWeekend() {
  const day = new Date().getDay()
  return day === 0 || day === 6
}

/**
 * 判断当前是否在A股交易时间段内
 * 交易时间：9:00-11:30, 13:00-15:00（排除周末）
 */
export function isTradingHours() {
  if (isWeekend()) return false

  const now = new Date()
  const hours = now.getHours()
  const minutes = now.getMinutes()
  const totalMinutes = hours * 60 + minutes

  // 9:00-11:30 (540-690)
  if (totalMinutes >= 540 && totalMinutes < 690) return true
  // 13:00-15:00 (780-900)
  if (totalMinutes >= 780 && totalMinutes < 900) return true

  return false
}
