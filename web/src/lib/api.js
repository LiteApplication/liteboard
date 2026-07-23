// Thin fetch wrapper. On 401 we bounce to the Authentik login.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  })
  if (res.status === 401) {
    const err = new Error('unauthenticated')
    err.status = 401
    throw err
  }
  if (!res.ok) {
    let detail
    try { detail = (await res.json()).detail } catch { detail = res.statusText }
    const err = new Error(detail || `HTTP ${res.status}`)
    err.status = res.status
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}

function qs(params) {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null)
  if (!entries.length) return ''
  return '?' + new URLSearchParams(entries).toString()
}

export const api = {
  setupStatus: () => request('/api/setup/status'),
  submitSetup: (payload) => request('/api/setup', { method: 'POST', body: JSON.stringify(payload) }),
  me: () => request('/api/me'),
  overview: () => request('/api/overview'),
  updates: () => request('/api/updates'),
  applyUpdate: (id) => request(`/api/updates/${id}/apply`, { method: 'POST' }),
  applyAll: () => request('/api/updates/apply-all', { method: 'POST' }),
  serviceLogs: (id, params = {}) => request(`/api/services/${id}/logs${qs(params)}`),
  redeployService: (id) => request(`/api/services/${id}/redeploy`, { method: 'POST' }),
  nodes: () => request('/api/nodes'),
  nodeJoinInfo: () => request('/api/nodes/join-info'),
  pruneNodeImages: (nodeId) => request(`/api/nodes/${nodeId}/images/prune`, { method: 'POST' }),
  networks: () => request('/api/networks'),
  daemonVersion: () => request('/api/daemons/version'),
  pushDaemonUpdate: () => request('/api/daemons/push-update', { method: 'POST' }),
  registryLogin: (payload) => request('/api/registry/login', { method: 'POST', body: JSON.stringify(payload) }),
  registryList: () => request('/api/registry/list'),
  registryLogout: (registry) => request(`/api/registry/${encodeURIComponent(registry)}`, { method: 'DELETE' }),
  logout: () => request('/auth/logout', { method: 'POST' }),
}

export function login() {
  window.location.href = '/auth/login'
}
