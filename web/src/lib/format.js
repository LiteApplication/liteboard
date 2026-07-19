export function bytes(n, perSec = false) {
  if (n == null || isNaN(n)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  const suffix = perSec ? '/s' : ''
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}${suffix}`
}

export function pct(n) {
  if (n == null || isNaN(n)) return '—'
  return `${n.toFixed(n < 10 ? 1 : 0)}%`
}

export function shortDigest(d) {
  if (!d) return '—'
  const s = d.replace('sha256:', '')
  return s.slice(0, 12)
}

export function uptime(seconds) {
  if (!seconds) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export const STATE_META = {
  'crash-loop': { label: 'Crash-loop', color: 'critical', glow: true },
  down: { label: 'Down', color: 'critical', glow: false },
  degraded: { label: 'Degraded', color: 'degraded', glow: false },
  updating: { label: 'Updating', color: 'info', glow: false },
  healthy: { label: 'Healthy', color: 'healthy', glow: false },
}
