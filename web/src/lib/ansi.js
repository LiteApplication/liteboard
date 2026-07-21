// Minimal ANSI SGR -> HTML renderer for container log output. Only handles
// color/style ("m") sequences; other escapes (cursor movement, OSC, etc.) are
// stripped since they have no meaning in a static scrollback view.

const FG = {
  30: '#1e293b', 31: '#f87171', 32: '#4ade80', 33: '#facc15',
  34: '#60a5fa', 35: '#c084fc', 36: '#22d3ee', 37: '#e2e8f0',
  90: '#64748b', 91: '#fca5a5', 92: '#86efac', 93: '#fde047',
  94: '#93c5fd', 95: '#d8b4fe', 96: '#67e8f9', 97: '#f8fafc',
}
const BG = {
  40: '#1e293b', 41: '#f87171', 42: '#4ade80', 43: '#facc15',
  44: '#60a5fa', 45: '#c084fc', 46: '#22d3ee', 47: '#e2e8f0',
  100: '#64748b', 101: '#fca5a5', 102: '#86efac', 103: '#fde047',
  104: '#93c5fd', 105: '#d8b4fe', 106: '#67e8f9', 107: '#f8fafc',
}

const ESCAPE_RE = /\x1b\[([0-9;]*)([a-zA-Z])|\x1b\].*?(?:\x07|\x1b\\)/g

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function styleFor(state) {
  const decl = []
  if (state.fg) decl.push(`color:${state.fg}`)
  if (state.bg) decl.push(`background-color:${state.bg}`)
  if (state.bold) decl.push('font-weight:600')
  if (state.dim) decl.push('opacity:0.6')
  if (state.italic) decl.push('font-style:italic')
  if (state.underline) decl.push('text-decoration:underline')
  return decl.join(';')
}

/** Convert a single log line (may contain ANSI SGR codes) to safe inline HTML. */
export function ansiToHtml(text) {
  if (!text) return ''
  let out = ''
  let last = 0
  let state = {}
  let open = false
  ESCAPE_RE.lastIndex = 0
  let m
  while ((m = ESCAPE_RE.exec(text))) {
    const chunk = text.slice(last, m.index)
    if (chunk) out += escapeHtml(chunk)
    last = ESCAPE_RE.lastIndex

    const [, codes, kind] = m
    if (kind !== 'm') continue // non-SGR escape: dropped, no state change

    const parts = (codes || '0').split(';').filter((p) => p !== '')
    const nums = parts.length ? parts.map(Number) : [0]
    for (let i = 0; i < nums.length; i++) {
      const n = nums[i]
      if (n === 0) state = {}
      else if (n === 1) state.bold = true
      else if (n === 2) state.dim = true
      else if (n === 3) state.italic = true
      else if (n === 4) state.underline = true
      else if (n === 22) { state.bold = false; state.dim = false }
      else if (n === 23) state.italic = false
      else if (n === 24) state.underline = false
      else if (n === 39) state.fg = undefined
      else if (n === 49) state.bg = undefined
      else if (FG[n]) state.fg = FG[n]
      else if (BG[n]) state.bg = BG[n]
      else if (n === 38 || n === 48) {
        // 256-color / truecolor: skip the following params, best-effort only.
        if (nums[i + 1] === 5) i += 2
        else if (nums[i + 1] === 2) i += 4
      }
    }
    if (open) { out += '</span>'; open = false }
    const style = styleFor(state)
    if (style) { out += `<span style="${style}">`; open = true }
  }
  const rest = text.slice(last)
  if (rest) out += escapeHtml(rest)
  if (open) out += '</span>'
  return out
}
