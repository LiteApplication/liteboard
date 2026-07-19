<script setup>
import { computed } from 'vue'
import { STATE_META } from '../lib/format'

const props = defineProps({ state: String })
const meta = computed(() => STATE_META[props.state] || STATE_META.healthy)

const classes = {
  critical: 'bg-critical/15 text-critical ring-1 ring-critical/30',
  degraded: 'bg-degraded/15 text-degraded ring-1 ring-degraded/30',
  info: 'bg-info/15 text-info ring-1 ring-info/30',
  healthy: 'bg-healthy/15 text-healthy ring-1 ring-healthy/30',
}
const dot = {
  critical: 'bg-critical', degraded: 'bg-degraded', info: 'bg-info', healthy: 'bg-healthy',
}
</script>

<template>
  <span class="pill" :class="classes[meta.color]">
    <span class="w-1.5 h-1.5 rounded-full" :class="[dot[meta.color], meta.glow && 'animate-pulseGlow']" />
    {{ meta.label }}
  </span>
</template>
