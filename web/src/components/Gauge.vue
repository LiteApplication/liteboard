<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 }, // 0..100
  label: String,
  sublabel: String,
  size: { type: Number, default: 120 },
})

const R = 52
const CIRC = 2 * Math.PI * R
const dash = computed(() => {
  const v = Math.max(0, Math.min(100, props.value || 0))
  return `${(v / 100) * CIRC} ${CIRC}`
})
const color = computed(() => {
  const v = props.value || 0
  if (v >= 90) return '#fb7185'
  if (v >= 75) return '#fbbf24'
  return '#2dd4bf'
})
</script>

<template>
  <div class="flex flex-col items-center">
    <div class="relative" :style="{ width: size + 'px', height: size + 'px' }">
      <svg viewBox="0 0 120 120" class="-rotate-90 w-full h-full">
        <circle cx="60" cy="60" :r="R" fill="none" stroke="#1f2937" stroke-width="9" />
        <circle
          cx="60" cy="60" :r="R" fill="none" :stroke="color" stroke-width="9"
          stroke-linecap="round" :stroke-dasharray="dash"
          class="transition-all duration-700 ease-out"
          :style="{ filter: `drop-shadow(0 0 6px ${color}88)` }"
        />
      </svg>
      <div class="absolute inset-0 flex flex-col items-center justify-center">
        <span class="text-2xl font-semibold tabular-nums" :style="{ color }">
          {{ Math.round(value || 0) }}<span class="text-sm text-slate-500">%</span>
        </span>
        <span v-if="sublabel" class="text-[10px] text-slate-500 mt-0.5">{{ sublabel }}</span>
      </div>
    </div>
    <span v-if="label" class="label mt-2">{{ label }}</span>
  </div>
</template>
