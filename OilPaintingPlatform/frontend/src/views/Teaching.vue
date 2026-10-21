<script setup>
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { getArticles } from '../api'

const articles = ref([])
const filter = ref('')
const loading = ref(true)

const categories = computed(() => {
  const set = new Set(articles.value.map((a) => a.category))
  return ['全部', ...set]
})

const filtered = computed(() => {
  if (!filter.value || filter.value === '全部') return articles.value
  return articles.value.filter((a) => a.category === filter.value)
})

onMounted(async () => {
  try {
    articles.value = await getArticles()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="container">
    <h1 class="section-title">油画教学</h1>
    <p class="section-sub">从材料工具到流派鉴赏，系统学习油画创作</p>

    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:24px;">
      <button
        v-for="c in categories"
        :key="c"
        class="btn"
        :class="filter === c ? 'btn-primary' : 'btn-outline'"
        style="padding:6px 16px; font-size:14px;"
        @click="filter = c"
      >{{ c }}</button>
    </div>

    <div v-if="loading" class="empty-state"><div class="spinner"></div></div>
    <div v-else class="grid grid-3">
      <RouterLink
        v-for="a in filtered"
        :key="a.id"
        :to="`/teaching/${a.id}`"
        class="card"
        style="text-decoration:none; color:inherit;"
      >
        <span class="badge">{{ a.category }}</span>
        <h3 style="color:var(--primary-dark); margin:10px 0 6px;">{{ a.title }}</h3>
        <p style="color:var(--text-light); font-size:14px;">{{ a.summary }}</p>
        <div style="margin-top:10px;">
          <span v-for="t in a.tags" :key="t" class="badge" style="margin-right:4px;">{{ t }}</span>
        </div>
      </RouterLink>
    </div>
  </div>
</template>
