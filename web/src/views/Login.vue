<script setup>
import { login } from '../lib/api'
</script>

<template>
  <div class="h-full flex items-center justify-center relative overflow-hidden">
    <!-- ambient glow -->
    <div class="absolute w-[600px] h-[600px] rounded-full bg-accent/10 blur-[120px] -top-40 -left-20" />
    <div class="absolute w-[500px] h-[500px] rounded-full bg-info/10 blur-[120px] -bottom-40 -right-20" />

    <div class="card p-10 w-[380px] text-center relative animate-fadeUp">
      <img src="/favicon.svg" alt="LiteBoard" class="w-16 h-16 mx-auto mb-5 drop-shadow-glow" />
      <h1 class="text-2xl font-semibold tracking-tight text-slate-100">LiteBoard</h1>
      <p class="text-sm text-slate-500 mt-2 mb-8">
        Docker Swarm health &amp; operations dashboard
      </p>

      <button class="btn-accent w-full justify-center !py-3 text-base" @click="login">
        Sign in with Authentik
      </button>

      <p class="text-xs text-slate-600 mt-6">Authenticated access only</p>
    </div>
  </div>
</template>
