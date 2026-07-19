<script setup>
import { ref, onMounted } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import Icon from '../components/Icon.vue'
import { api } from '../lib/api'

const report = ref(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    report.value = await api.networks()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const typeMeta = {
  'ip-collision': { icon: 'alert', label: 'IP collision' },
  'subnet-mismatch': { icon: 'share', label: 'Subnet mismatch' },
  'task-ip-conflict': { icon: 'net', label: 'Task IP conflict' },
}

onMounted(load)
</script>

<template>
  <PageHeader title="Networks" subtitle="Cross-node overlay consistency">
    <template #actions>
      <button class="btn-ghost" :disabled="loading" @click="load">
        <Icon name="refresh" :size="15" :class="loading && 'animate-spin'" /> Refresh
      </button>
    </template>
  </PageHeader>

  <div class="p-8 space-y-5">
    <div v-if="error" class="card border-critical/30 p-3 text-sm text-critical">{{ error }}</div>

    <div v-if="loading" class="text-center py-16 text-slate-500">
      <Icon name="refresh" :size="28" class="mx-auto mb-3 animate-spin" /> Correlating node views…
    </div>

    <template v-else-if="report">
      <!-- Consistent banner -->
      <div v-if="report.consistent" class="card p-8 text-center border-healthy/20">
        <div class="w-14 h-14 rounded-2xl bg-healthy/15 text-healthy flex items-center justify-center mx-auto mb-3">
          <Icon name="check" :size="28" />
        </div>
        <div class="text-slate-100 font-medium">Networks consistent</div>
        <div class="text-sm text-slate-500 mt-1">
          No IP collisions, subnet mismatches, or divergent task IPs across nodes.
        </div>
      </div>

      <!-- Warnings -->
      <div v-else class="space-y-3">
        <div v-for="(w, i) in report.warnings" :key="i"
             class="card p-4 animate-fadeUp"
             :class="w.severity === 'critical' ? 'border-critical/30 shadow-glow-critical' : 'border-degraded/30'">
          <div class="flex items-start gap-3">
            <div class="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
                 :class="w.severity === 'critical' ? 'bg-critical/15 text-critical' : 'bg-degraded/15 text-degraded'">
              <Icon :name="typeMeta[w.type]?.icon || 'alert'" :size="18" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-medium text-slate-100">{{ typeMeta[w.type]?.label || w.type }}</span>
                <span class="pill bg-surface-2 text-slate-400 font-mono">{{ w.network }}</span>
              </div>
              <p class="text-sm text-slate-400 mt-1">{{ w.message }}</p>
              <div v-if="w.ips || w.subnets || w.owners" class="flex flex-wrap gap-1.5 mt-2">
                <span v-for="v in (w.ips || w.subnets || w.owners)" :key="v"
                      class="pill bg-surface-2 text-slate-300 font-mono">{{ v }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Service IP map -->
      <section v-if="report.service_ips && Object.keys(report.service_ips).length" class="pt-2">
        <h2 class="text-sm font-semibold text-slate-400 mb-3">Service IP map</h2>
        <div class="card divide-y divide-border/40">
          <div v-for="(ips, svc) in report.service_ips" :key="svc"
               class="flex items-center justify-between px-5 py-3">
            <span class="font-medium text-slate-200">{{ svc }}</span>
            <div class="flex flex-wrap gap-1.5 justify-end">
              <span v-for="ip in ips" :key="ip" class="pill bg-surface-2 text-slate-400 font-mono">{{ ip }}</span>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
