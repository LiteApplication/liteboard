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

export const api = {
  me: () => request('/api/me'),
  overview: () => request('/api/overview'),
  updates: () => request('/api/updates'),
  applyUpdate: (id) => request(`/api/updates/${id}/apply`, { method: 'POST' }),
  applyAll: () => request('/api/updates/apply-all', { method: 'POST' }),
  serviceLogs: (id) => request(`/api/services/${id}/logs`),
  redeployService: (id) => request(`/api/services/${id}/redeploy`, { method: 'POST' }),
  nodes: () => request('/api/nodes'),
  nodeJoinInfo: () => request('/api/nodes/join-info'),
  networks: () => request('/api/networks'),
  daemonVersion: () => request('/api/daemons/version'),
  pushDaemonUpdate: () => request('/api/daemons/push-update', { method: 'POST' }),
  logout: () => request('/auth/logout', { method: 'POST' }),
}

export function login() {
  window.location.href = '/auth/login'
}
