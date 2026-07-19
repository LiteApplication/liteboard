<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api } from '../lib/api'

const form = reactive({
  token: '',
  base_url: '',
  oidc_issuer: '',
  oidc_client_id: '',
  oidc_client_secret: '',
  oidc_required_group: '',
})

const submitting = ref(false)
const applying = ref(false)   // POST accepted; server restarting
const error = ref(null)

onMounted(() => {
  form.base_url = window.location.origin
})

async function waitUntilConfigured() {
  // The server restarts to load the new config, so requests will fail for a
  // few seconds — keep polling until it comes back configured.
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2000))
    try {
      const s = await api.setupStatus()
      if (s.configured) return true
    } catch { /* server restarting — retry */ }
  }
  return false
}

async function submit() {
  error.value = null
  submitting.value = true
  try {
    await api.submitSetup({ ...form })
    applying.value = true
    const ok = await waitUntilConfigured()
    if (ok) {
      window.location.href = '/auth/login'
    } else {
      applying.value = false
      error.value = 'Timed out waiting for the server to restart. Reload to retry.'
    }
  } catch (e) {
    error.value = e.message || 'Setup failed'
  } finally {
    submitting.value = false
  }
}

const inputCls =
  'w-full px-3 py-2.5 rounded-xl bg-surface-2 border border-border text-sm text-slate-100 ' +
  'placeholder:text-slate-600 outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30 transition'
</script>

<template>
  <div class="min-h-full flex items-center justify-center relative overflow-hidden py-10">
    <div class="absolute w-[600px] h-[600px] rounded-full bg-accent/10 blur-[120px] -top-40 -left-20" />
    <div class="absolute w-[500px] h-[500px] rounded-full bg-info/10 blur-[120px] -bottom-40 -right-20" />

    <div class="card p-8 w-[460px] max-w-[92vw] relative animate-fadeUp">
      <div class="text-center mb-6">
        <img src="/favicon.svg" alt="LiteBoard" class="w-14 h-14 mx-auto mb-4 drop-shadow-glow" />
        <h1 class="text-xl font-semibold tracking-tight text-slate-100">Set up LiteBoard</h1>
        <p class="text-sm text-slate-500 mt-2">
          First-time configuration. This runs once, then the app locks behind your identity provider.
        </p>
      </div>

      <!-- Applying / restarting state -->
      <div v-if="applying" class="text-center py-8">
        <div class="w-10 h-10 mx-auto mb-4 rounded-full border-2 border-accent/30 border-t-accent animate-spin" />
        <p class="text-sm text-slate-300">Applying configuration &amp; restarting…</p>
        <p class="text-xs text-slate-500 mt-2">You'll be sent to sign in when it's back.</p>
      </div>

      <form v-else class="space-y-4" @submit.prevent="submit">
        <div>
          <label class="label block mb-1.5">Setup token</label>
          <input v-model.trim="form.token" :class="inputCls" type="password" autocomplete="off"
                 placeholder="from `docker service logs liteboard_server`" required />
          <p class="text-[11px] text-slate-600 mt-1">Printed in the server logs on first boot.</p>
        </div>

        <div>
          <label class="label block mb-1.5">Public URL</label>
          <input v-model.trim="form.base_url" :class="inputCls" type="url"
                 placeholder="https://liteboard.example.com" required />
          <p class="text-[11px] text-slate-600 mt-1">Must match your OIDC redirect URI's host.</p>
        </div>

        <div class="pt-2 border-t border-border/60">
          <div class="label mb-3">Authentik OIDC</div>
          <div class="space-y-3">
            <input v-model.trim="form.oidc_issuer" :class="inputCls" type="url"
                   placeholder="Issuer — https://authentik…/application/o/liteboard/" required />
            <input v-model.trim="form.oidc_client_id" :class="inputCls" type="text"
                   placeholder="Client ID" required />
            <input v-model.trim="form.oidc_client_secret" :class="inputCls" type="password"
                   autocomplete="off" placeholder="Client secret" required />
            <input v-model.trim="form.oidc_required_group" :class="inputCls" type="text"
                   placeholder="Required group (optional)" />
          </div>
        </div>

        <p v-if="error" class="text-sm text-critical bg-critical/10 rounded-lg px-3 py-2">{{ error }}</p>

        <button class="btn-accent w-full justify-center !py-3 text-base" type="submit" :disabled="submitting">
          {{ submitting ? 'Validating…' : 'Complete setup' }}
        </button>
      </form>
    </div>
  </div>
</template>
