<script setup>
import { computed, ref } from 'vue'
import HealthBadge from './HealthBadge.vue'
import Icon from './Icon.vue'
import ServiceDetailModal from './ServiceDetailModal.vue'
import { api } from '../lib/api'
import { nodeName } from '../lib/store'
import { ago } from '../lib/format'

const props = defineProps({ service: Object })
const s = computed(() => props.service)

const replicaText = computed(() =>
  s.value.desired == null ? `${s.value.running}` : `${s.value.running}/${s.value.desired}`
)
const replicaBad = computed(() => s.value.desired != null && s.value.running < s.value.desired)

const nodeNames = computed(() => (s.value.running_node_ids || []).map(nodeName))
const showDetail = ref(false)

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

const clearing = ref(false)
const cleared = ref(false)
const clearError = ref('')

async function clearRollout() {
  if (clearing.value) return
  clearing.value = true
  clearError.value = ''
  try {
    await api.clearRollout(s.value.id)
    // Nothing restarts; the advisory disappears once Swarm settles the update
    // and the SSE stream delivers the next overview.
    cleared.value = true
  } catch (e) {
    clearError.value = e.message
  } finally {
    clearing.value = false
  }
}
</script>

<template>
  <div
    class="card card-hover p-4 flex items-center gap-4 animate-fadeUp cursor-pointer"
    @click="showDetail = true"
  >
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2.5">
        <span class="font-medium text-slate-100 truncate">{{ s.name }}</span>
        <HealthBadge :state="s.state" />
      </div>
      <div class="text-xs text-slate-500 font-mono truncate mt-1">{{ s.image }}</div>
      <div v-if="nodeNames.length" class="text-xs text-slate-500 truncate mt-1">
        <Icon name="server" :size="12" class="inline -mt-0.5 mr-1" />{{ nodeNames.join(', ') }}
      </div>
      <div v-if="s.last_error && s.state !== 'healthy'" class="text-xs text-critical/90 mt-1.5 truncate">
        ⚠ {{ s.last_error }}
        <span v-if="s.last_exit_code != null" class="text-slate-500">(exit {{ s.last_exit_code }})</span>
      </div>
      <div v-if="s.transitioning && s.transitioning.length > 0" class="mt-2 space-y-1">
        <div v-for="t in s.transitioning" :key="t.slot || t.node_id" class="flex items-center gap-2 text-xs text-slate-400">
          <Icon name="refresh" :size="12" class="animate-spin text-accent" />
          <span class="font-medium text-slate-300">
            Task {{ s.mode === 'global' ? `(Node: ${nodeName(t.node_id)})` : `#${t.slot}` }}:
          </span>
          <span class="capitalize text-accent font-semibold">{{ t.state }}</span>
          <span v-if="t.message" class="text-slate-500">({{ t.message }})</span>
          <span v-if="t.err" class="text-critical/90">({{ t.err }})</span>
        </div>
      </div>
      <div v-if="s.rollout" class="mt-2 flex items-start gap-2 text-xs">
        <Icon name="pause" :size="12" class="text-degraded mt-0.5 shrink-0" />
        <div class="min-w-0">
          <span class="text-degraded font-medium">
            Rollout paused<span v-if="ago(s.rollout.started_at)"> {{ ago(s.rollout.started_at) }} ago</span>
          </span>
          <span v-if="s.rollout.message" class="text-slate-500"> — {{ s.rollout.message }}</span>
        </div>
        <button
          class="shrink-0 text-slate-400 hover:text-accent underline decoration-dotted disabled:opacity-50 disabled:no-underline"
          :title="'Re-submit the spec unchanged so Swarm settles the rollout — nothing restarts'"
          :disabled="clearing || cleared"
          @click.stop="clearRollout"
        >
          {{ cleared ? 'clearing…' : clearing ? '…' : 'clear' }}
        </button>
      </div>
      <div v-if="clearError" class="text-xs text-critical/90 mt-1.5 truncate">
        ⚠ {{ clearError }}
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

  <ServiceDetailModal v-if="showDetail" :service="s" @close="showDetail = false" />
</template>
