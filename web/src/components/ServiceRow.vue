<script setup>
import { computed, ref } from 'vue'
import HealthBadge from './HealthBadge.vue'
import Icon from './Icon.vue'
import LogsModal from './LogsModal.vue'
import { api } from '../lib/api'

const props = defineProps({ service: Object })
const s = computed(() => props.service)

const replicaText = computed(() =>
  s.value.desired == null ? `${s.value.running}` : `${s.value.running}/${s.value.desired}`
)
const replicaBad = computed(() => s.value.desired != null && s.value.running < s.value.desired)

// Crash-looping rows open their logs on click ("last session" up to the crash).
const canViewLogs = computed(() => s.value.state === 'crash-loop')
const showLogs = ref(false)

const redeploying = ref(false)
const redeployError = ref('')

async function redeploy() {
  if (redeploying.value) return
  if (!confirm(`Redeploy ${s.value.name}? This restarts all its tasks.`)) return
  redeploying.value = true
  redeployError.value = ''
  try {
    await api.redeployService(s.value.id)
    // The SSE stream will flip the service to "updating" on the next tick.
  } catch (e) {
    redeployError.value = e.message
  } finally {
    redeploying.value = false
  }
}
</script>

<template>
  <div
    class="card card-hover p-4 flex items-center gap-4 animate-fadeUp"
    :class="canViewLogs && 'cursor-pointer'"
    @click="canViewLogs && (showLogs = true)"
  >
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2.5">
        <span class="font-medium text-slate-100 truncate">{{ s.name }}</span>
        <HealthBadge :state="s.state" />
        <span
          v-if="canViewLogs"
          class="hidden sm:inline-flex items-center gap-1 text-xs text-slate-500"
        >
          <Icon name="terminal" :size="13" /> view logs
        </span>
      </div>
      <div class="text-xs text-slate-500 font-mono truncate mt-1">{{ s.image }}</div>
      <div v-if="s.last_error" class="text-xs text-critical/90 mt-1.5 truncate">
        ⚠ {{ s.last_error }}
        <span v-if="s.last_exit_code != null" class="text-slate-500">(exit {{ s.last_exit_code }})</span>
      </div>
      <div v-if="redeployError" class="text-xs text-critical/90 mt-1.5 truncate">
        ⚠ {{ redeployError }}
      </div>
    </div>

    <div v-if="s.recent_failures" class="text-center px-2">
      <div class="text-lg font-semibold text-critical tabular-nums">{{ s.recent_failures }}</div>
      <div class="label">fails/10m</div>
    </div>

    <div class="text-right">
      <div class="text-xl font-semibold tabular-nums" :class="replicaBad ? 'text-degraded' : 'text-slate-200'">
        {{ replicaText }}
      </div>
      <div class="label">{{ s.mode === 'global' ? 'global' : 'replicas' }}</div>
    </div>

    <button
      class="shrink-0 p-2 rounded-lg text-slate-500 hover:text-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed"
      :title="`Redeploy ${s.name}`"
      :disabled="redeploying"
      @click.stop="redeploy"
    >
      <Icon name="redeploy" :size="16" :class="redeploying && 'animate-spin'" />
    </button>
  </div>

  <LogsModal v-if="showLogs" :service="s" @close="showLogs = false" />
</template>
