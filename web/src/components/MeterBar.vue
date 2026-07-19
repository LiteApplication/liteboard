<script setup>
defineProps({
  label: String,
  value: String,
  ratio: { type: Number, default: 0 }, // 0..1 fill
  color: { type: String, default: '#2dd4bf' },
  icon: String,
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-1">
      <span class="text-xs text-slate-400">{{ label }}</span>
      <span class="text-xs font-mono text-slate-200 tabular-nums">{{ value }}</span>
    </div>
    <div class="h-1.5 rounded-full bg-surface-2 overflow-hidden">
      <div class="h-full rounded-full transition-all duration-700 ease-out"
           :style="{ width: Math.min(100, ratio * 100) + '%', background: color, boxShadow: `0 0 8px ${color}66` }" />
    </div>
  </div>
</template>
