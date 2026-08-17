<script setup>
import { useSlots } from 'vue'

defineProps({ title: String, subtitle: String })
const slots = useSlots()
</script>

<template>
  <header
    class="static lg:sticky lg:top-0 z-10 border-b border-border/60 bg-canvas/70 backdrop-blur-md
           px-4 py-3 sm:px-6 lg:px-8 lg:h-16 lg:py-0
           flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between"
  >
    <div class="min-w-0">
      <h1 class="text-lg font-semibold tracking-tight text-slate-100 truncate">{{ title }}</h1>
      <p v-if="subtitle" class="text-xs text-slate-500 truncate">{{ subtitle }}</p>
    </div>
    <!-- Actions wrap onto their own line(s) on narrow screens rather than
         squeezing the title out of the row. -->
    <div v-if="slots.actions" class="flex flex-wrap items-center gap-2 lg:gap-3">
      <slot name="actions" />
    </div>
  </header>
</template>
