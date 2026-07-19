<script setup>
import { ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import NodeCard from '../components/NodeCard.vue'
import AddNodeModal from '../components/AddNodeModal.vue'
import Icon from '../components/Icon.vue'
import { store } from '../lib/store'
import { api } from '../lib/api'

const pushing = ref(false)
const pushMsg = ref('')
const showAddNode = ref(false)

async function pushUpdate() {
  pushing.value = true
  pushMsg.value = ''
  try {
    const r = await api.pushDaemonUpdate()
    const updated = r.results.filter((x) => x.body?.updated).length
    pushMsg.value = `Pushed v${r.version} → ${updated}/${r.results.length} node(s) updated`
  } catch (e) {
    pushMsg.value = `Failed: ${e.message}`
  } finally {
    pushing.value = false
  }
}
</script>

<template>
  <PageHeader title="Nodes" subtitle="Live per-node resource metrics">
    <template #actions>
      <span v-if="pushMsg" class="text-xs text-slate-400">{{ pushMsg }}</span>
      <button class="btn-ghost" :disabled="pushing" @click="pushUpdate">
        <Icon name="refresh" :size="15" :class="pushing && 'animate-spin'" />
        Update daemons
      </button>
      <button class="btn-accent" @click="showAddNode = true">
        <Icon name="plus" :size="15" />
        Add node
      </button>
    </template>
  </PageHeader>

  <AddNodeModal v-if="showAddNode" @close="showAddNode = false" />

  <div class="p-8">
    <div v-if="!store.nodes.length" class="text-center py-16 text-slate-500">
      <Icon name="server" :size="28" class="mx-auto mb-3 opacity-60" /> Discovering nodes…
    </div>
    <div v-else class="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      <NodeCard v-for="entry in store.nodes" :key="entry.node.id" :entry="entry" />
    </div>
  </div>
</template>
