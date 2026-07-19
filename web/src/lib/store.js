import { reactive } from 'vue'

// Shared live store fed by the server's SSE stream (/api/stream).
export const store = reactive({
  connected: false,
  overview: null, // { counts, services, swarm }
  nodes: [],      // [{ node, metrics, reachable, daemon }]
  lastError: null,
  updatingServer: false,
})

let es = null

export function startStream(onUnauthorized) {
  if (es) return
  es = new EventSource('/api/stream', { withCredentials: true })
  es.addEventListener('tick', (e) => {
    try {
      const data = JSON.parse(e.data)
      store.overview = data.overview
      store.nodes = data.nodes || []
      store.connected = true
      store.lastError = null
    } catch { /* ignore malformed frame */ }
  })
  es.addEventListener('error', () => {
    store.connected = false
    // EventSource returns no status; probe /api/me to detect auth loss.
    fetch('/api/me', { credentials: 'same-origin' }).then((r) => {
      if (r.status === 401 && onUnauthorized) onUnauthorized()
    })
  })
}

export function stopStream() {
  if (es) { es.close(); es = null; store.connected = false }
}

export async function waitForServer() {
  store.updatingServer = true
  stopStream()
  while (true) {
    try {
      const res = await fetch('/api/me', { credentials: 'same-origin' })
      if (res.status === 200) {
        store.updatingServer = false
        window.location.reload()
        break
      }
    } catch {
      // Ignore network errors while server is offline
    }
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
}
