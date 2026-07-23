<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from './components/Icon.vue'
import { api, login } from './lib/api'
import { store, startStream, stopStream } from './lib/store'

const route = useRoute()
const router = useRouter()
const user = ref(null)
const ready = ref(false)

const navItems = [
  { name: 'overview', label: 'Overview', icon: 'grid', to: '/' },
  { name: 'updates', label: 'Updates', icon: 'download', to: '/updates' },
  { name: 'nodes', label: 'Nodes', icon: 'server', to: '/nodes' },
  { name: 'networks', label: 'Networks', icon: 'share', to: '/networks' },
]

// Login and Setup render full-screen without the app chrome.
const isBare = computed(() => route.name === 'login' || route.name === 'setup')

const badCount = computed(() => {
  const c = store.overview?.counts
  if (!c) return 0
  return (c['crash-loop'] || 0) + (c.down || 0) + (c.degraded || 0)
})

function toLogin() {
  stopStream()
  if (route.name !== 'login') router.push('/login')
}

onMounted(async () => {
  try {
    // Before anything else: has the server been set up? If not, run the wizard.
    const setup = await api.setupStatus().catch(() => ({ configured: true }))
    if (!setup.configured) {
      if (route.name !== 'setup') router.push('/setup')
      ready.value = true
      return
    }
    user.value = await api.me()
    startStream(toLogin)
    // Image counts are cached server-side and only recomputed on demand —
    // a fresh page load is our signal that it's worth recounting.
    api.refreshNodeImages().catch(() => {})
  } catch (e) {
    if (e.status === 401) { toLogin() }
  } finally {
    ready.value = true
  }
})

async function doLogout() {
  await api.logout().catch(() => {})
  stopStream()
  login() // send back through Authentik (which will show its logout/login)
}
</script>

<template>
  <div v-if="store.updatingServer" class="fixed inset-0 z-50 flex flex-col items-center justify-center bg-canvas text-center p-6 select-none animate-fadeIn">
    <div class="w-16 h-16 rounded-2xl bg-accent/15 text-accent flex items-center justify-center mb-6 animate-pulse">
      <Icon name="refresh" :size="32" class="animate-spin" />
    </div>
    <h1 class="text-xl font-semibold text-slate-100 tracking-tight">Updating LiteBoard Server</h1>
    <p class="text-sm text-slate-500 mt-2 max-w-sm leading-relaxed">
      The server container is restarting with the new image. The dashboard will automatically reconnect once the update completes.
    </p>
    <div class="mt-8 flex items-center gap-2.5 text-xs text-slate-400 font-mono bg-surface-2 border border-border px-3 py-1.5 rounded-full">
      <span class="w-2 h-2 rounded-full bg-accent animate-pulseGlow" />
      <span>pinging backend…</span>
    </div>
  </div>

  <div v-else-if="isBare" class="h-full">
    <router-view />
  </div>

  <div v-else class="h-full flex">
    <!-- Sidebar -->
    <aside class="w-60 shrink-0 border-r border-border/60 bg-surface/40 backdrop-blur-md flex flex-col">
      <div class="px-5 h-16 flex items-center gap-3 border-b border-border/60">
        <img src="/favicon.svg" alt="" class="w-8 h-8" />
        <div>
          <div class="font-semibold tracking-tight text-slate-100 leading-none">LiteBoard</div>
          <div class="text-[10px] text-slate-500 mt-1">swarm control</div>
        </div>
      </div>

      <nav class="flex-1 p-3 space-y-1">
        <router-link
          v-for="item in navItems" :key="item.name" :to="item.to"
          class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-slate-400
                 transition hover:bg-surface-2 hover:text-slate-100"
          active-class="!bg-accent/10 !text-accent ring-1 ring-accent/20"
          :class="{ '!bg-accent/10 !text-accent ring-1 ring-accent/20': route.name === item.name }"
        >
          <Icon :name="item.icon" :size="18" />
          {{ item.label }}
          <span v-if="item.name === 'overview' && store.overview"
                class="ml-auto text-xs px-1.5 rounded-md"
                :class="badCount > 0 ? 'bg-critical/20 text-critical' : 'bg-healthy/15 text-healthy'">
            {{ badCount || '✓' }}
          </span>
        </router-link>
      </nav>

      <div class="p-3 border-t border-border/60">
        <div class="flex items-center gap-2 px-2 mb-2">
          <span class="w-2 h-2 rounded-full" :class="store.connected ? 'bg-healthy animate-pulseGlow' : 'bg-slate-600'" />
          <span class="text-xs text-slate-500">{{ store.connected ? 'live' : 'connecting…' }}</span>
        </div>
        <div v-if="user" class="flex items-center gap-3 px-2 py-2 rounded-xl bg-surface-2">
          <div class="w-8 h-8 rounded-full bg-accent/20 text-accent flex items-center justify-center text-sm font-semibold">
            {{ (user.name || user.email || '?')[0]?.toUpperCase() }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-xs font-medium text-slate-200 truncate">{{ user.name || 'User' }}</div>
            <div class="text-[10px] text-slate-500 truncate">{{ user.email }}</div>
          </div>
          <button @click="doLogout" class="text-slate-500 hover:text-critical transition" title="Sign out">
            <Icon name="logout" :size="16" />
          </button>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <main class="flex-1 overflow-y-auto">
      <router-view v-if="ready" />
    </main>
  </div>
</template>
