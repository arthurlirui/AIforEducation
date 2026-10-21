<script setup>
import { RouterLink } from 'vue-router'
import { useStore } from '../stores/app'

const store = useStore()
</script>

<template>
  <div>
    <section class="hero">
      <h1>用 AI 创作属于你的油画</h1>
      <p>
        输入一句提示词，选择艺术风格，让主流视觉大模型为你生成一幅
        印象派、巴洛克、写实主义……风格的油画作品。同时提供系统的
        油画教学课程，助你从入门到鉴赏。
      </p>
      <RouterLink to="/create" class="btn btn-primary">开始创作 →</RouterLink>
      <RouterLink to="/teaching" class="btn btn-outline" style="margin-left:12px;">学习油画</RouterLink>
    </section>

    <div class="container">
      <!-- Features -->
      <h2 class="section-title">平台特色</h2>
      <p class="section-sub">三大模块，覆盖创作、学习与分享</p>
      <div class="grid grid-3" style="margin-bottom:48px;">
        <div class="card">
          <h3 style="color:var(--primary-dark); margin-bottom:10px;">🎨 AI 文生图</h3>
          <p style="color:var(--text-light);">支持 OpenAI DALL·E、通义万相、智谱 CogView、Stable Diffusion 等主流视觉大模型。输入提示词 + 选择风格即可生成油画。</p>
        </div>
        <div class="card">
          <h3 style="color:var(--primary-dark); margin-bottom:10px;">📚 油画教学</h3>
          <p style="color:var(--text-light);">从材料工具到明暗对照法，从色彩理论到流派鉴赏，系统化的教学文章带你走进油画世界。</p>
        </div>
        <div class="card">
          <h3 style="color:var(--primary-dark); margin-bottom:10px;">🖼 作品画廊</h3>
          <p style="color:var(--text-light);">所有生成的作品自动保存到画廊，可随时回看创作过程、提示词与所用风格。</p>
        </div>
      </div>

      <!-- Styles preview -->
      <h2 class="section-title">支持的艺术风格</h2>
      <p class="section-sub">{{ store.styles.length }} 种油画流派，预设风格关键词自动拼接</p>
      <div class="grid grid-4" style="margin-bottom:48px;">
        <div v-for="s in store.styles" :key="s.id" class="card" style="padding:16px;">
          <h4 style="color:var(--primary-dark);">{{ s.name }}</h4>
          <p style="font-size:12px; color:var(--text-light);">{{ s.name_en }} · {{ s.era }}</p>
        </div>
      </div>

      <!-- Articles preview -->
      <h2 class="section-title">教学文章精选</h2>
      <p class="section-sub">从零开始学习油画</p>
      <div class="grid grid-3" style="margin-bottom:48px;">
        <RouterLink
          v-for="a in store.articles.slice(0, 6)"
          :key="a.id"
          :to="`/teaching/${a.id}`"
          class="card"
          style="text-decoration:none; color:inherit;"
        >
          <span class="badge">{{ a.category }}</span>
          <h3 style="color:var(--primary-dark); margin:10px 0 6px;">{{ a.title }}</h3>
          <p style="color:var(--text-light); font-size:14px;">{{ a.summary }}</p>
        </RouterLink>
      </div>
    </div>
  </div>
</template>
