import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'

const routes = [
  { path: '/', name: 'home', component: Home, meta: { title: '名画目录' } },
  {
    path: '/painting/:id',
    name: 'tour',
    component: () => import('../views/Tour.vue'),
    meta: { title: '沉浸导览' },
  },
  {
    path: '/quiz/:id',
    name: 'quiz',
    component: () => import('../views/Quiz.vue'),
    meta: { title: '学习检验' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.afterEach((to) => {
  document.title = `${to.meta.title || ''} · 艺境 ArtRealm3D`
})

export default router
