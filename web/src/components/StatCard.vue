<script setup>
defineProps({
  label: String,
  value: [Number, String],
  accent: { type: String, default: 'accent' }, // accent|healthy|degraded|critical|info
  hint: String,
})
const ring = {
  accent: 'text-accent', healthy: 'text-healthy', degraded: 'text-degraded',
  critical: 'text-critical', info: 'text-info',
}
</script>

<template>
  <div class="card p-5 animate-fadeUp relative overflow-hidden">
    <div class="absolute -right-6 -top-6 w-24 h-24 rounded-full opacity-[0.07] blur-2xl"
         :class="ring[accent]" style="background: currentColor" />
    <div class="label">{{ label }}</div>
    <div class="stat-value mt-2" :class="ring[accent]">{{ value }}</div>
    <div v-if="hint" class="text-xs text-slate-500 mt-1">{{ hint }}</div>
  </div>
</template>
