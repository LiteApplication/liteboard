<script setup>
import { computed } from 'vue'
import Gauge from './Gauge.vue'
import MeterBar from './MeterBar.vue'
import Icon from './Icon.vue'
import { bytes, uptime } from '../lib/format'

const props = defineProps({ entry: Object })
const node = computed(() => props.entry.node)
const m = computed(() => props.entry.metrics)
const reachable = computed(() => props.entry.reachable)

// Scale throughput bars against a soft 100 MB/s reference.
const REF = 100 * 1024 * 1024
</script>

<template>
  <div class="card p-5 animate-fadeUp" :class="reachable ? 'card-hover' : 'opacity-70'">
    <div class="flex items-start justify-between mb-4">
      <div>
        <div class="flex items-center gap-2">
          <span class="font-semibold text-slate-100">{{ node.hostname }}</span>
          <Icon v-if="node.leader" name="crown" :size="14" class="text-degraded" title="Leader" />
        </div>
        <div class="flex items-center gap-2 mt-1">
          <span class="pill bg-surface-2 text-slate-400 ring-1 ring-border">{{ node.role }}</span>
          <span class="pill" :class="node.state === 'ready' ? 'bg-healthy/15 text-healthy' : 'bg-critical/15 text-critical'">
            {{ node.state }}
          </span>
        </div>
      </div>
      <div class="text-right">
        <span class="pill" :class="reachable ? 'bg-healthy/15 text-healthy' : 'bg-critical/15 text-critical'">
          <span class="w-1.5 h-1.5 rounded-full" :class="reachable ? 'bg-healthy animate-pulseGlow' : 'bg-critical'" />
          {{ reachable ? 'daemon up' : 'unreachable' }}
        </span>
        <div v-if="entry.daemon" class="text-[10px] text-slate-500 mt-1 font-mono">v{{ entry.daemon.version }}</div>
      </div>
    </div>

    <div v-if="reachable && m" class="space-y-4">
      <div class="flex justify-around">
        <Gauge :value="m.cpu_percent" label="CPU" :sublabel="`${m.cpu_count} cores`" :size="104" />
        <Gauge :value="m.mem_percent" label="Memory"
               :sublabel="`${bytes(m.mem_used)} / ${bytes(m.mem_total)}`" :size="104" />
      </div>

      <div class="grid grid-cols-3 gap-3 text-center py-2 border-y border-border/60">
        <div>
          <div class="text-sm font-semibold text-slate-200 tabular-nums">{{ (m.load_avg[0] || 0).toFixed(2) }}</div>
          <div class="label">load 1m</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-200 tabular-nums">{{ (m.load_avg[1] || 0).toFixed(2) }}</div>
          <div class="label">load 5m</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-200 tabular-nums">{{ uptime(m.uptime_s) }}</div>
          <div class="label">uptime</div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <MeterBar label="Net ↓" :value="bytes(m.net_recv_bps, true)" :ratio="m.net_recv_bps / REF" color="#60a5fa" />
        <MeterBar label="Net ↑" :value="bytes(m.net_sent_bps, true)" :ratio="m.net_sent_bps / REF" color="#818cf8" />
        <MeterBar label="Disk R" :value="bytes(m.disk_read_bps, true)" :ratio="m.disk_read_bps / REF" color="#2dd4bf" />
        <MeterBar label="Disk W" :value="bytes(m.disk_write_bps, true)" :ratio="m.disk_write_bps / REF" color="#fbbf24" />
      </div>
    </div>

    <div v-else class="py-8 text-center text-sm text-slate-500">
      <Icon name="alert" :size="24" class="mx-auto mb-2 text-critical/70" />
      {{ entry.error || 'No metrics — daemon not reachable' }}
    </div>
  </div>
</template>
