<script setup>
import { ref } from 'vue'
import Icon from './Icon.vue'
import { api } from '../lib/api'

const emit = defineEmits(['close'])

const registry = ref('ghcr.io')
const username = ref('')
const password = ref('')

const submitting = ref(false)
const error = ref('')
const success = ref(false)

const inputCls =
  'w-full px-3 py-2.5 rounded-xl bg-surface-2 border border-border text-sm text-slate-100 ' +
  'placeholder:text-slate-600 outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30 transition'

async function submit() {
  if (!registry.value || !username.value || !password.value) {
    error.value = 'All fields are required.'
    return
  }
  error.value = ''
  submitting.value = true
  success.value = false
  try {
    await api.registryLogin({
      registry: registry.value,
      username: username.value,
      password: password.value,
    })
    success.value = true
    setTimeout(() => {
      emit('close')
    }, 1500)
  } catch (e) {
    error.value = e.message || 'Login failed. Please check registry host and credentials.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-md p-6 relative">
      <button class="absolute top-4 right-4 text-slate-500 hover:text-white p-1" @click="emit('close')">
        <Icon name="close" :size="18" />
      </button>

      <div>
        <h2 class="text-base font-semibold text-slate-100">Registry Login</h2>
        <p class="text-xs text-slate-500 mt-0.5">
          Configure registry credentials so LiteBoard can fetch manifest digests for private repositories.
        </p>
      </div>

      <form @submit.prevent="submit" class="mt-5 space-y-4">
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

        <div v-if="error" class="text-sm text-critical mt-1">{{ error }}</div>
        <div v-if="success" class="text-sm text-healthy mt-1 flex items-center gap-1.5">
          <Icon name="check" :size="16" /> Credentials saved successfully!
        </div>

        <div class="flex justify-end gap-2 pt-2">
          <button
            type="button"
            class="btn-ghost"
            :disabled="submitting || success"
            @click="emit('close')"
          >
            Cancel
          </button>
          <button
            type="submit"
            class="btn-accent"
            :disabled="submitting || success"
          >
            <Icon v-if="submitting" name="refresh" :size="14" class="animate-spin mr-1" />
            Login
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
