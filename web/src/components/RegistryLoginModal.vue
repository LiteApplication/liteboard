<script setup>
import { ref, onMounted } from 'vue'
import Icon from './Icon.vue'
import { api } from '../lib/api'

const props = defineProps({
  // Pre-fills + opens the add-registry form, e.g. when suggested after a failed lookup.
  prefill: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const entries = ref([])
const loadingList = ref(true)
const listError = ref('')
const removing = ref(null) // registry currently being removed

const showForm = ref(!!props.prefill)
const registry = ref(props.prefill || 'ghcr.io')
const username = ref('')
const password = ref('')

const submitting = ref(false)
const formError = ref('')
const success = ref(false)

const inputCls =
  'w-full px-3 py-2.5 rounded-xl bg-surface-2 border border-border text-sm text-slate-100 ' +
  'placeholder:text-slate-600 outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30 transition'

async function loadEntries() {
  loadingList.value = true
  listError.value = ''
  try {
    entries.value = (await api.registryList()).registries
  } catch (e) {
    listError.value = e.message || 'Could not load registries.'
  } finally {
    loadingList.value = false
  }
}

async function removeEntry(entry) {
  if (!confirm(`Remove stored credentials for ${entry.registry}?`)) return
  removing.value = entry.registry
  try {
    await api.registryLogout(entry.registry)
    await loadEntries()
  } catch (e) {
    listError.value = e.message || 'Could not remove credentials.'
  } finally {
    removing.value = null
  }
}

async function submit() {
  if (!registry.value || !username.value || !password.value) {
    formError.value = 'All fields are required.'
    return
  }
  formError.value = ''
  submitting.value = true
  success.value = false
  try {
    await api.registryLogin({
      registry: registry.value,
      username: username.value,
      password: password.value,
    })
    success.value = true
    username.value = ''
    password.value = ''
    await loadEntries()
    setTimeout(() => {
      success.value = false
      showForm.value = false
    }, 1200)
  } catch (e) {
    formError.value = e.message || 'Login failed. Please check registry host and credentials.'
  } finally {
    submitting.value = false
  }
}

onMounted(loadEntries)
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-lg p-6 relative">
      <button class="absolute top-4 right-4 text-slate-500 hover:text-white p-1" @click="emit('close')">
        <Icon name="close" :size="18" />
      </button>

      <div>
        <h2 class="text-base font-semibold text-slate-100">Registry Logins</h2>
        <p class="text-xs text-slate-500 mt-0.5">
          Credentials LiteBoard uses to fetch manifest digests for private repositories.
        </p>
      </div>

      <div class="mt-5">
        <div v-if="listError" class="text-sm text-critical mb-3">{{ listError }}</div>

        <div v-if="loadingList" class="text-center py-6 text-slate-500 text-sm">
          <Icon name="refresh" :size="18" class="mx-auto mb-2 animate-spin" /> Checking registries…
        </div>

        <div v-else-if="!entries.length" class="text-sm text-slate-500 py-2">
          No registries configured yet.
        </div>

        <ul v-else class="space-y-2">
          <li
            v-for="entry in entries"
            :key="entry.registry"
            class="flex items-center justify-between gap-3 rounded-xl bg-surface-2 border border-border px-3 py-2.5"
          >
            <div class="min-w-0">
              <div class="text-sm font-medium text-slate-100 truncate">{{ entry.registry }}</div>
              <div class="text-xs text-slate-500 truncate">
                {{ entry.username || 'unknown user' }}
                <span v-if="entry.source === 'secret'" class="text-slate-600"> · read-only (secret)</span>
              </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <span
                class="pill"
                :class="entry.valid ? 'bg-healthy/15 text-healthy' : 'bg-critical/15 text-critical'"
              >
                <Icon :name="entry.valid ? 'check' : 'alert'" :size="12" class="mr-1 inline" />
                {{ entry.valid ? 'Valid' : 'Invalid' }}
              </span>
              <button
                v-if="entry.source !== 'secret'"
                class="text-slate-500 hover:text-critical p-1 disabled:opacity-50"
                :disabled="removing === entry.registry"
                title="Remove credentials"
                @click="removeEntry(entry)"
              >
                <Icon :name="removing === entry.registry ? 'refresh' : 'trash'" :size="15"
                      :class="removing === entry.registry && 'animate-spin'" />
              </button>
            </div>
          </li>
        </ul>
      </div>

      <div class="mt-5 pt-4 border-t border-border/60">
        <button v-if="!showForm" class="btn-ghost w-full justify-center" @click="showForm = true">
          <Icon name="plus" :size="15" /> Log in to a registry
        </button>

        <form v-else @submit.prevent="submit" class="space-y-4">
          <div>
            <label class="label mb-1.5 block">Registry Host</label>
            <input
              v-model.trim="registry"
              :class="inputCls"
              type="text"
              placeholder="e.g. ghcr.io, index.docker.io"
              required
              :disabled="submitting || success"
            />
          </div>

          <div>
            <label class="label mb-1.5 block">Username</label>
            <input
              v-model.trim="username"
              :class="inputCls"
              type="text"
              placeholder="Username"
              required
              :disabled="submitting || success"
            />
          </div>

          <div>
            <label class="label mb-1.5 block">Password / Access Token</label>
            <input
              v-model.trim="password"
              :class="inputCls"
              type="password"
              placeholder="Password or Personal Access Token"
              required
              :disabled="submitting || success"
            />
          </div>

          <div v-if="formError" class="text-sm text-critical mt-1">{{ formError }}</div>
          <div v-if="success" class="text-sm text-healthy mt-1 flex items-center gap-1.5">
            <Icon name="check" :size="16" /> Credentials saved successfully!
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <button
              type="button"
              class="btn-ghost"
              :disabled="submitting || success"
              @click="showForm = false; formError = ''"
            >
              Cancel
            </button>
            <button type="submit" class="btn-accent" :disabled="submitting || success">
              <Icon v-if="submitting" name="refresh" :size="14" class="animate-spin mr-1" />
              Login
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
