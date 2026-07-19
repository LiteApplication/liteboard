import { createRouter, createWebHistory } from 'vue-router'
import Overview from './views/Overview.vue'
import Updates from './views/Updates.vue'
import Nodes from './views/Nodes.vue'
import Networks from './views/Networks.vue'
import Login from './views/Login.vue'
import Setup from './views/Setup.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview, meta: { nav: 'Overview', icon: 'grid' } },
    { path: '/updates', name: 'updates', component: Updates, meta: { nav: 'Updates', icon: 'download' } },
    { path: '/nodes', name: 'nodes', component: Nodes, meta: { nav: 'Nodes', icon: 'server' } },
    { path: '/networks', name: 'networks', component: Networks, meta: { nav: 'Networks', icon: 'share' } },
    { path: '/login', name: 'login', component: Login, meta: { public: true } },
    { path: '/setup', name: 'setup', component: Setup, meta: { public: true } },
  ],
})
