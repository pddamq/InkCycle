import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('../views/Home.vue') },
  { path: '/new', name: 'interview', component: () => import('../views/Interview.vue') },
  { path: '/import', name: 'import', component: () => import('../views/ImportBook.vue') },
  { path: '/wizard/:pid', name: 'wizard', component: () => import('../views/Wizard.vue') },
  {
    path: '/project/:pid',
    component: () => import('../views/Project.vue'),
    children: [
      { path: '', redirect: (to) => `/project/${to.params.pid}/overview` },
      { path: 'overview', name: 'overview', component: () => import('../views/Overview.vue') },
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'world', name: 'world', component: () => import('../views/World.vue') },
      { path: 'characters', name: 'characters', component: () => import('../views/Characters.vue') },
      { path: 'characters/design', name: 'characterDesign', component: () => import('../views/CharacterDesign.vue') },
      { path: 'outline', name: 'outline', component: () => import('../views/Outline.vue') },
      { path: 'plot', name: 'plot', component: () => import('../views/PlotFlow.vue') },
      { path: 'book', name: 'book', component: () => import('../views/BookRun.vue') },
      { path: 'chapter/:chid', name: 'editor', component: () => import('../views/Editor.vue') },
      { path: 'foreshadow', name: 'foreshadow', component: () => import('../views/Foreshadow.vue') },
      { path: 'timeline', name: 'timeline', component: () => import('../views/Timeline.vue') },
      { path: 'export', name: 'export', component: () => import('../views/Export.vue') },
    ],
  },
  { path: '/extensions', name: 'extensions', component: () => import('../views/Extensions.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/Settings.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
