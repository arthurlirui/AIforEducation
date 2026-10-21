<script setup>
import { ref, onMounted } from 'vue'
import { getGallery } from '../api'

const items = ref([])
const loading = ref(true)

onMounted(async () => {
  try {
    items.value = await getGallery(50)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="container">
    <h1 class="section-title">作品画廊</h1>
    <p class="section-sub">平台生成的油画作品集</p>

    <div v-if="loading" class="empty-state"><div class="spinner"></div></div>
    <div v-else-if="items.length === 0" class="empty-state">
      <p>画廊还是空的，去 <a href="/create">AI 创作</a> 生成第一幅作品吧！</p>
    </div>
    <div v-else class="grid grid-3">
      <div v-for="item in items" :key="item.id" class="card" style="padding:14px;">
        <img :src="item.url" class="gen-image" style="margin-bottom:12px;" />
        <span class="badge badge-accent">{{ item.style_name }}</span>
        <span class="badge" style="margin-left:4px;">{{ item.provider }}</span>
        <p style="font-size:13px; color:var(--text-light); margin-top:8px; word-break:break-all;">
          {{ item.prompt }}
        </p>
        <p style="font-size:12px; color:var(--text-light); margin-top:4px;">{{ item.created_at }}</p>
      </div>
    </div>
  </div>
</template>
