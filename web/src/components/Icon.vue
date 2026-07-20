<script setup>
defineProps({ name: String, size: { type: [Number, String], default: 18 } })
const paths = {
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  download: 'M12 3v12m0 0l-4-4m4 4l4-4M4 21h16',
  server: 'M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01',
  share: 'M18 8a3 3 0 100-6 3 3 0 000 6zM6 15a3 3 0 100-6 3 3 0 000 6zM18 22a3 3 0 100-6 3 3 0 000 6zM8.5 13.5l7 3M15.5 7.5l-7 3',
  activity: 'M3 12h4l3-9 4 18 3-9h4',
  alert: 'M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z',
  check: 'M20 6L9 17l-5-5',
  refresh: 'M21 12a9 9 0 11-3-6.7M21 3v6h-6',
  logout: 'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9',
  cpu: 'M9 9h6v6H9zM4 9H2M4 15H2M22 9h-2M22 15h-2M9 4V2M15 4V2M9 22v-2M15 22v-2M5 5h14v14H5z',
  memory: 'M6 19v-3M10 19v-3M14 19v-3M18 19v-3M4 15h16V6a2 2 0 00-2-2H6a2 2 0 00-2 2z',
  clock: 'M12 6v6l4 2M12 22a10 10 0 100-20 10 10 0 000 20z',
  crown: 'M2 18h20M3 8l4 4 5-7 5 7 4-4v8H3z',
  disk: 'M22 12A10 10 0 112 12a10 10 0 0120 0zM12 12h.01M12 8a4 4 0 100 8',
  net: 'M12 20v-6M5 20v-3M19 20v-9M3 4h18M4 4v4h16V4',
  plus: 'M12 5v14M5 12h14',
  copy: 'M9 9h10v10H9zM5 15H4a1 1 0 01-1-1V4a1 1 0 011-1h10a1 1 0 011 1v1',
  close: 'M18 6L6 18M6 6l12 12',
  terminal: 'M4 17l6-6-6-6M12 19h8M3 4h18v16H3z',
  redeploy: 'M21 12a9 9 0 11-3-6.7M21 3v6h-6',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  lock: 'M6 11V7a6 6 0 1112 0v4M5 11h14v10H5z',
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path :d="paths[name] || paths.grid" />
  </svg>
</template>
