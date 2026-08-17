<script setup>
import { ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import NodeCard from '../components/NodeCard.vue'
import AddNodeModal from '../components/AddNodeModal.vue'
import Icon from '../components/Icon.vue'
import { store } from '../lib/store'

const showAddNode = ref(false)
</script>

<template>
  <PageHeader title="Nodes" subtitle="Live per-node resource metrics">
    <template #actions>
      <button class="btn-accent" @click="showAddNode = true">
        <Icon name="plus" :size="15" />
        Add node
      </button>
    </template>
  </PageHeader>

  <AddNodeModal v-if="showAddNode" @close="showAddNode = false" />

  <div class="page">
    <div v-if="!store.nodes.length" class="text-center py-16 text-slate-500">
      <Icon name="server" :size="28" class="mx-auto mb-3 opacity-60" /> Discovering nodes…
    </div>
    <div v-else class="grid gap-4 sm:gap-5 md:grid-cols-2 xl:grid-cols-3">
      <NodeCard v-for="entry in store.nodes" :key="entry.node.id" :entry="entry" />
    </div>
  </div>
</template>
