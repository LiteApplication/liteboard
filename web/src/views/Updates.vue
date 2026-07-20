<script setup>
import { ref, onMounted, computed } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import Icon from '../components/Icon.vue'
import RegistryLoginModal from '../components/RegistryLoginModal.vue'
import { api } from '../lib/api'
import { shortDigest } from '../lib/format'
import { store, waitForServer } from '../lib/store'

const items = ref([])
const loading = ref(true)
const error = ref('')
const busy = ref(null) // service id currently applying
const applyingAll = ref(false)
const showLogin = ref(false)
const loginPrefill = ref('')
const authSuggestions = ref([])

const outdated = computed(() => items.value.filter((i) => i.update_available))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.updates()
    items.value = res.services
    authSuggestions.value = res.registries_needing_auth || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function openLogin(registry = '') {
  loginPrefill.value = registry
  showLogin.value = true
}

async function applyOne(item) {
  const isServer = item.id === store.overview?.server_service_id
  if (isServer) {
    if (!confirm('You are updating the LiteBoard server itself. This will temporarily take the dashboard offline. Proceed?')) {
      return
    }
  }
  busy.value = item.id
  try {
    await api.applyUpdate(item.id)
    if (isServer) {
      waitForServer()
    } else {
      await load()
    }
  } catch (e) {
    error.value = `${item.name}: ${e.message}`
  } finally {
    if (!isServer) busy.value = null
  }
}

async function applyAll() {
  const hasServer = outdated.value.some((i) => i.id === store.overview?.server_service_id)
  const msg = hasServer
    ? 'Update all services? Note that this includes the LiteBoard server itself, which will temporarily take the dashboard offline.'
    : `Update all ${outdated.value.length} out-of-date service(s)?`
  if (!confirm(msg)) return

  applyingAll.value = true
  try {
    const result = await api.applyAll()
    if (result.server_updated) {
      waitForServer()
    } else {
      await load()
      applyingAll.value = false
    }
  } catch (e) {
    error.value = e.message
    applyingAll.value = false
  }
}

const statusMeta = {
  outdated: { label: 'Update available', cls: 'bg-degraded/15 text-degraded' },
  current: { label: 'Up to date', cls: 'bg-healthy/15 text-healthy' },
  unpinned: { label: 'Unpinned', cls: 'bg-surface-2 text-slate-400' },
  unknown: { label: 'Unknown', cls: 'bg-surface-2 text-slate-500' },
  auth_required: { label: 'Needs registry login', cls: 'bg-critical/15 text-critical' },
}

onMounted(load)
</script>

<template>
  <PageHeader title="Updates" subtitle="Image freshness across the registry">
    <template #actions>
      <button class="btn-ghost" @click="openLogin()">
        <Icon name="logout" :size="15" /> Registry Login
      </button>
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

    <div v-if="authSuggestions.length" class="card border-critical/30 p-4 flex flex-wrap items-center gap-3">
      <Icon name="lock" :size="18" class="text-critical shrink-0" />
      <div class="text-sm text-slate-300">
        {{ authSuggestions.length === 1 ? 'A registry lookup' : `${authSuggestions.length} registry lookups` }}
        failed as unauthorized. Log in to continue checking for updates.
      </div>
      <div class="flex flex-wrap gap-2 ml-auto">
        <button
          v-for="reg in authSuggestions"
          :key="reg"
          class="btn-ghost !py-1.5 !px-3"
          @click="openLogin(reg)"
        >
          <Icon name="logout" :size="14" /> Log in to {{ reg }}
        </button>
      </div>
    </div>

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
              <button v-else-if="item.status === 'unpinned' && item.remote_digest" class="btn-ghost !py-1.5 !px-3"
                      :disabled="busy != null || applyingAll" @click="applyOne(item)">
                <Icon :name="busy === item.id ? 'refresh' : 'download'" :size="14" :class="busy === item.id && 'animate-spin'" />
                Pin
              </button>
              <button v-else-if="item.status === 'auth_required'" class="btn-ghost !py-1.5 !px-3"
                      @click="openLogin(item.registry)">
                <Icon name="lock" :size="14" /> Log in
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <RegistryLoginModal v-if="showLogin" :prefill="loginPrefill" @close="showLogin = false; load()" />
</template>
