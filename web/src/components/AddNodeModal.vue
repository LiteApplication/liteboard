<script setup>
import { ref, computed, onMounted } from 'vue'
import Icon from './Icon.vue'
import { api } from '../lib/api'

const emit = defineEmits(['close'])

const info = ref(null)
const error = ref('')
const role = ref('worker') // 'worker' | 'manager'
const copied = ref('')

onMounted(async () => {
  try {
    info.value = await api.nodeJoinInfo()
    if (!info.value.manager_addrs?.length) {
      error.value = 'Could not determine the manager advertise address.'
    }
  } catch (e) {
    error.value = e.message
  }
})

const managerAddr = computed(() => info.value?.manager_addrs?.[0] || '<manager-ip>:2377')

const token = computed(() =>
  role.value === 'manager' ? info.value?.manager_token : info.value?.worker_token,
)

const joinCmd = computed(() =>
  info.value ? `docker swarm join --token ${token.value} ${managerAddr.value}` : '',
)

async function copy(text, key) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = key
    setTimeout(() => (copied.value = ''), 1500)
  } catch {
    /* clipboard unavailable (e.g. non-secure context) — user can select manually */
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
      <div class="flex items-start justify-between mb-1">
        <div>
          <h2 class="text-base font-semibold text-slate-100">Add a node</h2>
          <p class="text-xs text-slate-500">
            Join a machine to the swarm — the LiteBoard daemon deploys onto it automatically.
          </p>
        </div>
        <button class="text-slate-500 hover:text-white p-1 -mr-1" @click="emit('close')">
          <Icon name="close" :size="18" />
        </button>
      </div>

      <div v-if="error" class="mt-4 text-sm text-critical">{{ error }}</div>
      <div v-else-if="!info" class="mt-6 text-sm text-slate-500 flex items-center gap-2">
        <Icon name="refresh" :size="15" class="animate-spin" /> Fetching join token…
      </div>

      <template v-else>
        <!-- role toggle -->
        <div class="mt-5 flex items-center gap-2">
          <button
            class="pill border"
            :class="role === 'worker' ? 'border-accent/50 text-accent bg-accent/10' : 'border-border text-slate-400'"
            @click="role = 'worker'"
          >Worker</button>
          <button
            class="pill border"
            :class="role === 'manager' ? 'border-accent/50 text-accent bg-accent/10' : 'border-border text-slate-400'"
            @click="role = 'manager'"
          >Manager</button>
          <span v-if="role === 'manager'" class="text-xs text-degraded ml-1">
            grants full cluster control — only for trusted hosts
          </span>
        </div>

        <!-- step 1: install docker -->
        <div class="mt-5">
          <p class="label mb-2">1 · On the new machine, install Docker Engine</p>
          <div class="group relative">
            <pre class="bg-canvas/80 border border-border rounded-xl p-3 pr-11 text-xs text-slate-300 overflow-x-auto"><code>curl -fsSL https://get.docker.com | sh</code></pre>
            <button
              class="absolute top-2.5 right-2.5 text-slate-500 hover:text-accent"
              title="Copy"
              @click="copy('curl -fsSL https://get.docker.com | sh', 'install')"
            >
              <Icon :name="copied === 'install' ? 'check' : 'copy'" :size="15" />
            </button>
          </div>
        </div>

        <!-- step 2: join -->
        <div class="mt-4">
          <p class="label mb-2">2 · Join the swarm as {{ role }}</p>
          <div class="group relative">
            <pre class="bg-canvas/80 border border-border rounded-xl p-3 pr-11 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap break-all"><code>{{ joinCmd }}</code></pre>
            <button
              class="absolute top-2.5 right-2.5 text-slate-500 hover:text-accent"
              title="Copy"
              @click="copy(joinCmd, 'join')"
            >
              <Icon :name="copied === 'join' ? 'check' : 'copy'" :size="15" />
            </button>
          </div>
        </div>

        <p class="mt-5 text-xs text-slate-500 leading-relaxed">
          Once the node joins, the <span class="text-slate-300">global</span> daemon service
          starts on it within seconds and appears here. If the daemon image isn't reachable
          from the new host, or you want the newest build, use
          <span class="text-slate-300">Update daemons</span> to push the current signed
          bundle (v{{ info.daemon_version }}).
        </p>
      </template>
    </div>
  </div>
</template>
