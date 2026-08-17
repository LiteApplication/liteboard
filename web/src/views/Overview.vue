<script setup>
import { computed } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import ServiceRow from '../components/ServiceRow.vue'
import NodeRow from '../components/NodeRow.vue'
import Icon from '../components/Icon.vue'
import { store } from '../lib/store'

const counts = computed(() => store.overview?.counts || {})
const services = computed(() => store.overview?.services || [])
const problems = computed(() => services.value.filter((s) => s.state !== 'healthy'))
const healthy = computed(() => services.value.filter((s) => s.state === 'healthy'))

// A node is worth attention when Swarm says it isn't ready, or when its daemon
// stopped answering (which is how an unreachable host shows up first). A daemon
// that answers 503 is merely still waiting for its pubkey — not a fault.
const problemNodes = computed(() =>
  store.nodes.filter(
    (e) =>
      e.node &&
      (e.node.state !== 'ready' || (!e.reachable && !String(e.error || '').includes('503')))
  )
)
const attentionCount = computed(() => problems.value.length + problemNodes.value.length)

const loading = computed(() => !store.overview)
</script>

<template>
  <PageHeader title="Overview" subtitle="Cluster health at a glance">
    <template #actions>
      <span v-if="store.overview?.swarm" class="text-xs text-slate-500">
        {{ store.overview.swarm.nodes }} nodes · {{ store.overview.swarm.managers }} managers
      </span>
    </template>
  </PageHeader>

  <div class="page space-y-6 sm:space-y-8">
    <!-- Counter row -->
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 sm:gap-4">
      <StatCard label="Services" :value="counts.total ?? '—'" accent="accent" />
      <StatCard label="Healthy" :value="counts.healthy ?? 0" accent="healthy" />
      <StatCard label="Degraded" :value="(counts.degraded ?? 0) + (counts.down ?? 0)" accent="degraded"
                :hint="counts.down ? `${counts.down} fully down` : ''" />
      <StatCard label="Crash-loop" :value="counts['crash-loop'] ?? 0" accent="critical" />
      <!-- Odd tile out: spans the row on a 2-up phone grid instead of sitting
           orphaned next to a gap. -->
      <StatCard label="Updating" :value="counts.updating ?? 0" accent="info"
                class="col-span-2 sm:col-span-1" />
    </div>

    <div v-if="loading" class="text-center py-16 text-slate-500">
      <Icon name="refresh" :size="28" class="mx-auto mb-3 animate-spin" /> Loading cluster state…
    </div>

    <!-- Problems -->
    <section v-if="attentionCount">
      <h2 class="flex items-center gap-2 text-sm font-semibold text-slate-300 mb-3">
        <Icon name="alert" :size="16" class="text-critical" />
        Needs attention
        <span class="pill bg-critical/15 text-critical">{{ attentionCount }}</span>
      </h2>
      <div class="space-y-2.5">
        <NodeRow v-for="e in problemNodes" :key="e.node.id" :entry="e" />
        <ServiceRow v-for="s in problems" :key="s.id" :service="s" />
      </div>
    </section>

    <!-- All good banner -->
    <div v-else-if="!loading" class="card p-6 sm:p-8 text-center border-healthy/20">
      <div class="w-14 h-14 rounded-2xl bg-healthy/15 text-healthy flex items-center justify-center mx-auto mb-3">
        <Icon name="check" :size="28" />
      </div>
      <div class="text-slate-100 font-medium">All services healthy</div>
      <div class="text-sm text-slate-500 mt-1">
        No crash loops, under-replicated services, or unreachable nodes detected.
      </div>
    </div>

    <!-- Healthy list (collapsed-ish) -->
    <section v-if="healthy.length">
      <h2 class="text-sm font-semibold text-slate-400 mb-3">Healthy services</h2>
      <div class="grid xl:grid-cols-2 gap-2.5">
        <ServiceRow v-for="s in healthy" :key="s.id" :service="s" />
      </div>
    </section>
  </div>
</template>
