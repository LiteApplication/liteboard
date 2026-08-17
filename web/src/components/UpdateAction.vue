<script setup>
import Icon from './Icon.vue'

// The per-service action on the Updates page. Lives in its own component so the
// desktop table and the mobile card list share one definition of "what button
// does this row get".
defineProps({
  item: Object,
  busy: { type: String, default: null }, // service id currently applying
  applyingAll: Boolean,
  block: Boolean, // full-width, for the stacked mobile layout
})
defineEmits(['apply', 'login'])
</script>

<template>
  <button
    v-if="item.update_available"
    class="btn-accent !py-1.5 !px-3"
    :class="block && 'w-full justify-center'"
    :disabled="busy != null || applyingAll"
    @click="$emit('apply')"
  >
    <Icon :name="busy === item.id ? 'refresh' : 'download'" :size="14" :class="busy === item.id && 'animate-spin'" />
    Update
  </button>
  <button
    v-else-if="item.status === 'unpinned' && item.remote_digest"
    class="btn-ghost !py-1.5 !px-3"
    :class="block && 'w-full justify-center'"
    :disabled="busy != null || applyingAll"
    @click="$emit('apply')"
  >
    <Icon :name="busy === item.id ? 'refresh' : 'download'" :size="14" :class="busy === item.id && 'animate-spin'" />
    Pin
  </button>
  <button
    v-else-if="item.status === 'auth_required'"
    class="btn-ghost !py-1.5 !px-3"
    :class="block && 'w-full justify-center'"
    @click="$emit('login')"
  >
    <Icon name="lock" :size="14" /> Log in
  </button>
</template>
