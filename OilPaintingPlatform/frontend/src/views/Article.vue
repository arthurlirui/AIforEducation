<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { getArticle } from '../api'

const route = useRoute()
const article = ref(null)
const loading = ref(true)

async function load(id) {
  loading.value = true
  try {
    article.value = await getArticle(id)
  } finally {
    loading.value = false
  }
}

onMounted(() => load(route.params.id))
watch(() => route.params.id, (id) => id && load(id))
</script>

<template>
  <div class="container" style="max-width:800px;">
    <div v-if="loading" class="empty-state"><div class="spinner"></div></div>
    <article v-else-if="article" class="card article-content">
      <RouterLink to="/teaching" style="font-size:14px;">← 返回教学列表</RouterLink>
      <h1 style="color:var(--primary-dark); margin:16px 0 8px;">{{ article.title }}</h1>
      <p style="color:var(--text-light);">
        <span class="badge">{{ article.category }}</span>
        <span v-for="t in article.tags" :key="t" class="badge" style="margin-left:4px;">{{ t }}</span>
      </p>
      <p style="margin-top:16px; font-size:16px; color:var(--text);">{{ article.summary }}</p>
      <hr style="border:none; border-top:1px solid var(--border); margin:20px 0;" />
      <div v-html="renderMarkdown(article.content)"></div>
    </article>
    <div v-else class="empty-state"><p>文章未找到</p></div>
  </div>
</template>

<script>
// Minimal markdown renderer for our teaching content (##, -, **, 1.)
function renderMarkdown(text) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const lines = esc(text).split('\n')
  let html = ''
  let inList = false
  for (const line of lines) {
    if (line.startsWith('## ')) {
      if (inList) { html += '</ul>'; inList = false }
      html += `<h2>${line.slice(3)}</h2>`
    } else if (line.startsWith('- ')) {
      if (!inList) { html += '<ul>'; inList = true }
      html += `<li>${line.slice(2)}</li>`
    } else if (/^\d+\.\s/.test(line)) {
      if (inList) { html += '</ul>'; inList = false }
      html += `<p>${line}</p>`
    } else if (line.trim() === '') {
      if (inList) { html += '</ul>'; inList = false }
    } else {
      if (inList) { html += '</ul>'; inList = false }
      html += `<p>${line}</p>`
    }
  }
  if (inList) html += '</ul>'
  return html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
}
export default { methods: { renderMarkdown } }
</script>
