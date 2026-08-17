<script setup>
import { ref, computed, onMounted } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import Icon from '../components/Icon.vue'
import { api } from '../lib/api'

const report = ref(null)
const fabric = ref(null)
const loading = ref(true)
const error = ref('')
// Keyed by finding index: 'busy' while a repair is in flight, then the outcome.
const repairState = ref({})

async function load() {
  loading.value = true
  error.value = ''
  repairState.value = {}
  try {
    const [networks, fabricReport] = await Promise.all([api.networks(), api.fabric()])
    report.value = networks
    fabric.value = fabricReport
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function repair(finding, index) {
  repairState.value = { ...repairState.value, [index]: { status: 'busy' } }
  try {
    await api.repairFabric({
      node_id: finding.node_id,
      action: finding.repair.action,
      params: finding.repair.params,
    })
    repairState.value = { ...repairState.value, [index]: { status: 'done' } }
    // The server re-probes before responding, so this reflects the repaired state.
    fabric.value = await api.fabric()
  } catch (e) {
    repairState.value = { ...repairState.value, [index]: { status: 'failed', message: e.message } }
  }
}

const typeMeta = {
  'ip-collision': { icon: 'alert', label: 'IP collision' },
  'subnet-mismatch': { icon: 'share', label: 'Subnet mismatch' },
  'task-ip-conflict': { icon: 'net', label: 'Task IP conflict' },
  'vxlan-fdb-desync': { icon: 'net', label: 'Blackholed route' },
  'overlay-mtu-oversize': { icon: 'activity', label: 'Overlay MTU too large' },
  'service-dns-desync': { icon: 'share', label: 'Service DNS desync' },
  'swarm-engine-degraded': { icon: 'server', label: 'Swarm engine degraded' },
  'stale-vxlan-iface': { icon: 'trash', label: 'Orphaned vxlan interface' },
  'dns-egress-blackhole': { icon: 'alert', label: 'DNS egress blocked' },
}

// Probes that could not run (missing capabilities, unreachable daemon) get their
// own panel: "no findings" from a probe that never ran is not health.
const degradedProbes = computed(() =>
  (fabric.value?.probes || []).filter(
    (p) => !p.reachable || p.namespaces !== 'ok' || p.root_namespace !== 'ok',
  ),
)

onMounted(load)
</script>

<template>
  <PageHeader title="Networks" subtitle="Overlay fabric health & cross-node consistency">
    <template #actions>
      <button class="btn-ghost" :disabled="loading" @click="load">
        <Icon name="refresh" :size="15" :class="loading && 'animate-spin'" /> Refresh
      </button>
    </template>
  </PageHeader>

  <div class="page space-y-6 sm:space-y-8">
    <div v-if="error" class="card border-critical/30 p-3 text-sm text-critical">{{ error }}</div>

    <div v-if="loading" class="text-center py-16 text-slate-500">
      <Icon name="refresh" :size="28" class="mx-auto mb-3 animate-spin" /> Probing overlay fabric…
    </div>

    <template v-else>
      <!-- ── Fabric findings ─────────────────────────────────────────────── -->
      <section v-if="fabric" class="space-y-3">
        <h2 class="text-sm font-semibold text-slate-400">Overlay fabric</h2>

        <div v-if="fabric.healthy" class="card p-6 sm:p-8 text-center border-healthy/20">
          <div class="w-14 h-14 rounded-2xl bg-healthy/15 text-healthy flex items-center justify-center mx-auto mb-3">
            <Icon name="check" :size="28" />
          </div>
          <div class="text-slate-100 font-medium">Fabric intact</div>
          <div class="text-sm text-slate-500 mt-1">
            Forwarding tables match task placement, MTUs fit the underlay, and every node
            agrees on the service table.
          </div>
        </div>

        <div v-for="(f, i) in fabric.findings" :key="i"
             class="card p-4 animate-fadeUp"
             :class="f.severity === 'critical' ? 'border-critical/30 shadow-glow-critical' : 'border-degraded/30'">
          <div class="flex items-start gap-3">
            <div class="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
                 :class="f.severity === 'critical' ? 'bg-critical/15 text-critical' : 'bg-degraded/15 text-degraded'">
              <Icon :name="typeMeta[f.type]?.icon || 'alert'" :size="18" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-medium text-slate-100">{{ typeMeta[f.type]?.label || f.type }}</span>
                <span v-if="f.node" class="pill bg-surface-2 text-slate-400 font-mono">{{ f.node }}</span>
                <span v-if="f.network" class="pill bg-surface-2 text-slate-400 font-mono">{{ f.network }}</span>
              </div>
              <p class="text-sm text-slate-300 mt-1">{{ f.message }}</p>
              <p v-if="f.hint" class="text-xs text-slate-500 mt-1.5 leading-relaxed">{{ f.hint }}</p>

              <div class="flex flex-wrap items-center gap-x-3 gap-y-2 mt-3">
                <button v-if="f.repair && repairState[i]?.status !== 'done'"
                        class="btn-ghost text-xs"
                        :disabled="repairState[i]?.status === 'busy'"
                        @click="repair(f, i)">
                  <Icon name="redeploy" :size="14"
                        :class="repairState[i]?.status === 'busy' && 'animate-spin'" />
                  {{ repairState[i]?.status === 'busy' ? 'Repairing…' : f.repair.label }}
                </button>
                <span v-if="repairState[i]?.status === 'done'"
                      class="text-xs text-healthy flex items-center gap-1">
                  <Icon name="check" :size="14" /> Repaired
                </span>
                <span v-if="repairState[i]?.status === 'failed'" class="text-xs text-critical">
                  Repair failed: {{ repairState[i].message }}
                </span>
                <span v-if="!f.repair" class="text-xs text-slate-600">Manual fix required</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Probes that never ran — absence of findings means nothing here. -->
        <div v-if="degradedProbes.length" class="card p-4 border-border/60">
          <div class="text-sm font-medium text-slate-300 mb-2">Limited visibility</div>
          <div v-for="p in degradedProbes" :key="p.node_id" class="text-xs text-slate-500 py-0.5">
            <span class="font-mono text-slate-400">{{ p.node }}</span> —
            <template v-if="!p.reachable">daemon unreachable ({{ p.error }})</template>
            <template v-else>
              namespaces: {{ p.namespaces }} · host namespace: {{ p.root_namespace }}
            </template>
          </div>
        </div>
      </section>

      <!-- ── Cross-node endpoint consistency ─────────────────────────────── -->
      <section v-if="report" class="space-y-3">
        <h2 class="text-sm font-semibold text-slate-400">Endpoint consistency</h2>

        <div v-if="report.consistent" class="card p-5 text-sm text-slate-400 flex items-center gap-3">
          <Icon name="check" :size="18" class="text-healthy shrink-0" />
          No IP collisions, subnet mismatches, or divergent task IPs across nodes.
        </div>

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
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium text-slate-100">{{ typeMeta[w.type]?.label || w.type }}</span>
                  <span class="pill bg-surface-2 text-slate-400 font-mono break-all">{{ w.network }}</span>
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
      </section>

      <!-- ── Service IP map ──────────────────────────────────────────────── -->
      <section v-if="report?.service_ips && Object.keys(report.service_ips).length">
        <h2 class="text-sm font-semibold text-slate-400 mb-3">Service IP map</h2>
        <div class="card divide-y divide-border/40">
          <div v-for="(ips, svc) in report.service_ips" :key="svc"
               class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <span class="font-medium text-slate-200 break-all">{{ svc }}</span>
            <div class="flex flex-wrap gap-1.5 sm:justify-end">
              <span v-for="ip in ips" :key="ip" class="pill bg-surface-2 text-slate-400 font-mono">{{ ip }}</span>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
