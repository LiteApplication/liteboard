<script setup>
defineProps({ title: String, subtitle: String })
</script>

<template>
  <header class="h-16 px-8 flex items-center justify-between border-b border-border/60 sticky top-0 z-10 bg-canvas/70 backdrop-blur-md">
    <div>
      <h1 class="text-lg font-semibold tracking-tight text-slate-100">{{ title }}</h1>
      <p v-if="subtitle" class="text-xs text-slate-500">{{ subtitle }}</p>
    </div>
    <div class="flex items-center gap-3">
      <slot name="actions" />
    </div>
  </header>
</template>
