<script setup>
import { ref, onMounted } from 'vue'
import Icon from './Icon.vue'
import { api } from '../lib/api'

const props = defineProps({ service: Object })
const emit = defineEmits(['close'])

const logs = ref('')
const since = ref(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.serviceLogs(props.service.id)
    logs.value = res.logs || ''
    since.value = res.since
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-4xl max-h-[90vh] flex flex-col p-6">
      <div class="flex items-start justify-between mb-1">
        <div class="min-w-0">
          <h2 class="text-base font-semibold text-slate-100 truncate">
            Logs · {{ service.name }}
          </h2>
          <p class="text-xs text-slate-500">
            Last session
            <span v-if="since">since {{ new Date(since).toLocaleString() }}</span>
            — full output up to the crash.
          </p>
        </div>
        <div class="flex items-center gap-1">
          <button
            class="text-slate-500 hover:text-accent p-1"
            title="Reload"
            @click="load"
          >
            <Icon name="refresh" :size="16" :class="loading && 'animate-spin'" />
          </button>
          <button class="text-slate-500 hover:text-white p-1 -mr-1" @click="emit('close')">
            <Icon name="close" :size="18" />
          </button>
        </div>
      </div>

      <div v-if="error" class="mt-4 text-sm text-critical">{{ error }}</div>
      <div v-else-if="loading && !logs" class="mt-6 text-sm text-slate-500 flex items-center gap-2">
        <Icon name="refresh" :size="15" class="animate-spin" /> Fetching logs…
      </div>
      <div v-else-if="!logs" class="mt-6 text-sm text-slate-500">
        No log output captured for the last session.
      </div>
      <pre
        v-else
        class="mt-4 flex-1 min-h-0 overflow-auto bg-canvas/80 border border-border rounded-xl p-3 text-xs leading-relaxed text-slate-300 whitespace-pre-wrap break-words"
      ><code>{{ logs }}</code></pre>
    </div>
  </div>
</template>
