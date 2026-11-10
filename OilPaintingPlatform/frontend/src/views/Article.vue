<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { getArticle } from '../api'

const route = useRoute()
const article = ref(null)
const loading = ref(true)
const loadError = ref('')

async function load(id) {
  loading.value = true
  loadError.value = ''
  try {
    article.value = await getArticle(id)
  } catch (e) {
    // 网络/后端失败与"文章不存在"区分开
    loadError.value = '文章加载失败，请检查网络或后端服务后重试'
    article.value = null
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
    <div v-else-if="loadError" class="empty-state">
      <p>{{ loadError }}</p>
      <button class="btn btn-outline" style="margin-top:12px;" @click="load(route.params.id)">重试</button>
    </div>
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
// Minimal markdown renderer for our teaching content (##, >, -, **, *, `code`, 1.)
// 安全说明：内容先整体转义再按行处理，行内标记（**、*、`）只作用于
// 已转义文本且逐行替换，不会跨段落产生非法嵌套标签。
function renderMarkdown(text) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // 行内格式：加粗 → 斜体 → 行内代码（** 先于 * 处理避免互相干扰）
  const inline = (s) =>
    s
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
  let html = ''
  let inList = false
  const closeList = () => {
    if (inList) { html += '</ul>'; inList = false }
  }
  // 结构判断在原始行上进行，内容切片后再转义（否则 ">" 引用行会被转义掉）
  for (const line of text.split('\n')) {
    if (line.startsWith('## ')) {
      closeList()
      html += `<h2>${inline(esc(line.slice(3)))}</h2>`
    } else if (line.startsWith('> ')) {
      closeList()
      html += `<blockquote>${inline(esc(line.slice(2)))}</blockquote>`
    } else if (line.startsWith('- ')) {
      if (!inList) { html += '<ul>'; inList = true }
      html += `<li>${inline(esc(line.slice(2)))}</li>`
    } else if (/^\d+\.\s/.test(line)) {
      closeList()
      html += `<p>${inline(esc(line))}</p>`
    } else if (line.trim() === '') {
      closeList()
    } else {
      closeList()
      html += `<p>${inline(esc(line))}</p>`
    }
  }
  closeList()
  return html
}
export default { methods: { renderMarkdown } }
</script>
