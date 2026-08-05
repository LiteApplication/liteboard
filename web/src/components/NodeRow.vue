<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({ entry: Object })
const node = computed(() => props.entry.node)

// Swarm's own view is authoritative for "the node is gone"; an unreachable
// daemon on an otherwise-ready node is a lesser (metrics-only) problem.
const nodeDown = computed(() => node.value.state !== 'ready')

const badge = computed(() =>
  nodeDown.value
    ? { label: node.value.state || 'unknown', color: 'critical' }
    : { label: 'daemon unreachable', color: 'degraded' }
)

const detail = computed(() => {
  if (nodeDown.value) return 'Swarm reports this node as not ready — its tasks will be rescheduled elsewhere.'
  return props.entry.error
    ? `No metrics — ${props.entry.error}`
    : 'No metrics — the LiteBoard daemon is not answering on this node.'
})
</script>

<template>
  <RouterLink
    to="/nodes"
    class="card card-hover p-4 flex items-center gap-4 animate-fadeUp"
  >
    <div
      class="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
      :class="nodeDown ? 'bg-critical/15 text-critical' : 'bg-degraded/15 text-degraded'"
    >
      <Icon name="server" :size="17" />
    </div>

    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2.5">
        <span class="font-medium text-slate-100 truncate">{{ node.hostname || node.id.slice(0, 12) }}</span>
        <span
          class="pill ring-1"
          :class="nodeDown
            ? 'bg-critical/15 text-critical ring-critical/30'
            : 'bg-degraded/15 text-degraded ring-degraded/30'"
        >
          <span class="w-1.5 h-1.5 rounded-full" :class="nodeDown ? 'bg-critical' : 'bg-degraded'" />
          {{ badge.label }}
        </span>
        <Icon v-if="node.leader" name="crown" :size="13" class="text-degraded" title="Leader" />
      </div>
      <div class="text-xs text-slate-500 truncate mt-1">{{ detail }}</div>
    </div>

    <div class="text-right">
      <div class="text-sm font-medium text-slate-300 capitalize">{{ node.role }}</div>
      <div class="label">node</div>
    </div>
  </RouterLink>
</template>
