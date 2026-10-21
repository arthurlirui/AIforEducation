import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Create from '../views/Create.vue'
import Teaching from '../views/Teaching.vue'
import Gallery from '../views/Gallery.vue'
import About from '../views/About.vue'

const routes = [
  { path: '/', name: 'home', component: Home, meta: { title: '首页' } },
  { path: '/create', name: 'create', component: Create, meta: { title: 'AI 油画创作' } },
  { path: '/teaching', name: 'teaching', component: Teaching, meta: { title: '油画教学' } },
  { path: '/teaching/:id', name: 'article', component: () => import('../views/Article.vue'), meta: { title: '教学文章' } },
  { path: '/gallery', name: 'gallery', component: Gallery, meta: { title: '作品画廊' } },
  { path: '/about', name: 'about', component: About, meta: { title: '关于平台' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.afterEach((to) => {
  document.title = `${to.meta.title || ''} · 油画艺术教学平台`
})

export default router
