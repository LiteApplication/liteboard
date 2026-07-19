<script setup>
import { ref, onMounted, computed } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import Icon from '../components/Icon.vue'
import { api } from '../lib/api'
import { shortDigest } from '../lib/format'

const items = ref([])
const loading = ref(true)
const error = ref('')
const busy = ref(null) // service id currently applying
const applyingAll = ref(false)

const outdated = computed(() => items.value.filter((i) => i.update_available))

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = (await api.updates()).services
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function applyOne(item) {
  busy.value = item.id
  try {
    await api.applyUpdate(item.id)
    await load()
  } catch (e) {
    error.value = `${item.name}: ${e.message}`
  } finally {
    busy.value = null
  }
}

async function applyAll() {
  if (!confirm(`Update all ${outdated.value.length} out-of-date service(s)?`)) return
  applyingAll.value = true
  try {
    await api.applyAll()
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    applyingAll.value = false
  }
}

const statusMeta = {
  outdated: { label: 'Update available', cls: 'bg-degraded/15 text-degraded' },
  current: { label: 'Up to date', cls: 'bg-healthy/15 text-healthy' },
  unpinned: { label: 'Unpinned', cls: 'bg-surface-2 text-slate-400' },
  unknown: { label: 'Unknown', cls: 'bg-surface-2 text-slate-500' },
}

onMounted(load)
</script>

<template>
  <PageHeader title="Updates" subtitle="Image freshness across the registry">
    <template #actions>
      <button class="btn-ghost" :disabled="loading" @click="load">
        <Icon name="refresh" :size="15" :class="loading && 'animate-spin'" /> Refresh
      </button>
      <button v-if="outdated.length" class="btn-accent" :disabled="applyingAll || busy != null" @click="applyAll">
        <Icon :name="applyingAll ? 'refresh' : 'download'" :size="15" :class="applyingAll && 'animate-spin'" />
        Update all ({{ outdated.length }})
      </button>
    </template>
  </PageHeader>

  <div class="p-8 space-y-4">
    <div v-if="error" class="card border-critical/30 p-3 text-sm text-critical">{{ error }}</div>

    <div v-if="loading" class="text-center py-16 text-slate-500">
      <Icon name="refresh" :size="28" class="mx-auto mb-3 animate-spin" /> Checking registries…
    </div>

    <div v-else-if="!items.length" class="text-center py-16 text-slate-500">No services found.</div>

    <div v-else class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-slate-500 border-b border-border/60">
            <th class="font-medium px-5 py-3">Service</th>
            <th class="font-medium px-3 py-3 hidden md:table-cell">Tag</th>
            <th class="font-medium px-3 py-3 hidden lg:table-cell">Running</th>
            <th class="font-medium px-3 py-3 hidden lg:table-cell">Available</th>
            <th class="font-medium px-3 py-3">Status</th>
            <th class="px-5 py-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id"
              class="border-b border-border/40 last:border-0 hover:bg-surface-2/40 transition">
            <td class="px-5 py-3">
              <div class="font-medium text-slate-100">{{ item.name }}</div>
              <div class="text-xs text-slate-500 font-mono truncate max-w-[240px]">{{ item.repository }}</div>
            </td>
            <td class="px-3 py-3 hidden md:table-cell">
              <span class="pill bg-surface-2 text-slate-300 font-mono">{{ item.tag }}</span>
            </td>
            <td class="px-3 py-3 hidden lg:table-cell font-mono text-xs text-slate-400">
              {{ shortDigest(item.running_digest) }}
            </td>
            <td class="px-3 py-3 hidden lg:table-cell font-mono text-xs"
                :class="item.update_available ? 'text-degraded' : 'text-slate-400'">
              {{ shortDigest(item.remote_digest) }}
            </td>
            <td class="px-3 py-3">
              <span class="pill" :class="statusMeta[item.status]?.cls">
                {{ statusMeta[item.status]?.label || item.status }}
              </span>
            </td>
            <td class="px-5 py-3 text-right">
              <button v-if="item.update_available" class="btn-accent !py-1.5 !px-3"
                      :disabled="busy != null || applyingAll" @click="applyOne(item)">
                <Icon :name="busy === item.id ? 'refresh' : 'download'" :size="14" :class="busy === item.id && 'animate-spin'" />
                Update
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
