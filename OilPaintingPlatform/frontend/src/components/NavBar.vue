<script setup>
import { RouterLink } from 'vue-router'
</script>

<template>
  <nav class="navbar">
    <div class="container nav-inner">
      <RouterLink to="/" class="nav-brand">🎨 油画艺术教学平台</RouterLink>
      <div class="nav-links">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/create">AI 创作</RouterLink>
        <RouterLink to="/teaching">油画教学</RouterLink>
        <RouterLink to="/gallery">作品画廊</RouterLink>
        <RouterLink to="/about">关于</RouterLink>
      </div>
    </div>
  </nav>
</template>
