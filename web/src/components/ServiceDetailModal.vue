<script setup>
import { computed, ref, onMounted } from 'vue'
import Icon from './Icon.vue'
import Gauge from './Gauge.vue'
import { api } from '../lib/api'
import { store, nodeEntry } from '../lib/store'
import { bytes } from '../lib/format'

const props = defineProps({ service: Object })
const emit = defineEmits(['close'])

const s = computed(() => props.service)

// Node(s) the service is currently executing on, with their live metrics.
const nodeEntries = computed(() =>
  (s.value.running_node_ids || []).map((id) => ({ id, entry: nodeEntry(id) }))
)

const logs = ref('')
const since = ref(null)
const logsLoading = ref(true)
const logsError = ref('')

async function loadLogs() {
  logsLoading.value = true
  logsError.value = ''
  try {
    const res = await api.serviceLogs(s.value.id)
    logs.value = res.logs || ''
    since.value = res.since
  } catch (e) {
    logsError.value = e.message
  } finally {
    logsLoading.value = false
  }
}

onMounted(loadLogs)
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-4xl max-h-[90vh] flex flex-col p-6 overflow-y-auto">
      <div class="flex items-start justify-between mb-1">
        <div class="min-w-0">
          <h2 class="text-base font-semibold text-slate-100 truncate">{{ s.name }}</h2>
          <p class="text-xs text-slate-500 font-mono truncate">{{ s.image }}</p>
        </div>
        <button class="text-slate-500 hover:text-white p-1 -mr-1 shrink-0" @click="emit('close')">
          <Icon name="close" :size="18" />
        </button>
      </div>

      <!-- Nodes + resource usage -->
      <section class="mt-5">
        <h3 class="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
          <Icon name="server" :size="13" /> Running on
        </h3>
        <div v-if="!nodeEntries.length" class="text-sm text-slate-500">
          Not currently running on any node.
        </div>
        <div v-else class="grid sm:grid-cols-2 gap-3">
          <div v-for="{ id, entry } in nodeEntries" :key="id" class="rounded-xl border border-border/60 bg-canvas/50 p-3.5">
            <div class="flex items-center gap-2 mb-2">
              <span class="font-medium text-slate-200 text-sm truncate">
                {{ entry?.node?.hostname || id.slice(0, 8) }}
              </span>
              <Icon v-if="entry?.node?.leader" name="crown" :size="12" class="text-degraded" title="Leader" />
              <span
                v-if="entry"
                class="pill ml-auto"
                :class="entry.reachable ? 'bg-healthy/15 text-healthy' : 'bg-critical/15 text-critical'"
              >
                {{ entry.reachable ? 'daemon up' : 'unreachable' }}
              </span>
            </div>
            <div v-if="entry?.reachable && entry.metrics" class="flex justify-around">
              <Gauge :value="entry.metrics.cpu_percent" label="CPU" :size="76" />
              <Gauge
                :value="entry.metrics.mem_percent"
                label="Memory"
                :sublabel="`${bytes(entry.metrics.mem_used)} / ${bytes(entry.metrics.mem_total)}`"
                :size="76"
              />
            </div>
            <div v-else class="text-xs text-slate-500 py-2">
              {{ entry?.error || 'No live metrics for this node.' }}
            </div>
          </div>
        </div>
      </section>

      <!-- Logs -->
      <section class="mt-6 flex-1 min-h-0 flex flex-col">
        <div class="flex items-center justify-between mb-2">
          <h3 class="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wide">
            <Icon name="terminal" :size="13" /> Recent logs
            <span v-if="since" class="text-slate-600 normal-case font-normal">
              since {{ new Date(since).toLocaleString() }}
            </span>
          </h3>
          <button class="text-slate-500 hover:text-accent p-1" title="Reload" @click="loadLogs">
            <Icon name="refresh" :size="14" :class="logsLoading && 'animate-spin'" />
          </button>
        </div>

        <div v-if="logsError" class="text-sm text-critical">{{ logsError }}</div>
        <div v-else-if="logsLoading && !logs" class="text-sm text-slate-500 flex items-center gap-2">
          <Icon name="refresh" :size="15" class="animate-spin" /> Fetching logs…
        </div>
        <div v-else-if="!logs" class="text-sm text-slate-500">
          No log output captured for the last session.
        </div>
        <pre
          v-else
          class="flex-1 min-h-0 overflow-auto bg-canvas/80 border border-border rounded-xl p-3 text-xs leading-relaxed text-slate-300 whitespace-pre-wrap break-words"
        ><code>{{ logs }}</code></pre>
      </section>
    </div>
  </div>
</template>
