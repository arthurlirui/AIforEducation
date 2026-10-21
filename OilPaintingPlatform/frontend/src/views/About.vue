<script setup>
import { useStore } from '../stores/app'

const store = useStore()
</script>

<template>
  <div class="container" style="max-width:800px;">
    <h1 class="section-title">关于平台</h1>
    <div class="card">
      <h3 style="color:var(--primary-dark); margin-bottom:12px;">项目简介</h3>
      <p style="color:var(--text); margin-bottom:16px;">
        油画艺术教学平台是一个面向艺术爱好者与学习者的 Web 应用，
        将<strong>主流视觉大模型文生图能力</strong>与<strong>系统化油画教学</strong>
        结合在一起。用户只需输入简单的自然语言提示词并选择艺术风格，
        平台即可自动合成专业提示词并调用大模型生成对应风格的油画作品。
      </p>

      <h3 style="color:var(--primary-dark); margin:20px 0 10px;">技术架构</h3>
      <ul style="padding-left:24px; color:var(--text);">
        <li><strong>后端</strong>：Python · FastAPI · Pydantic · httpx</li>
        <li><strong>前端</strong>：Vue 3 · Vue Router · Pinia · Vite · Axios</li>
        <li><strong>视觉大模型</strong>：OpenAI DALL·E · 阿里通义万相 · 智谱 CogView · Stable Diffusion WebUI</li>
      </ul>

      <h3 style="color:var(--primary-dark); margin:20px 0 10px;">已接入模型</h3>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <span v-for="p in (store.health?.providers || ['mock'])" :key="p" class="badge">{{ p }}</span>
      </div>
      <p style="font-size:13px; color:var(--text-light); margin-top:8px;">
        当前默认模型：{{ store.health?.default_provider || 'mock' }}
      </p>

      <h3 style="color:var(--primary-dark); margin:20px 0 10px;">工作流程</h3>
      <ol style="padding-left:24px; color:var(--text); line-height:2;">
        <li>用户在前端输入提示词并选择艺术风格</li>
        <li>前端将请求发送至 FastAPI 后端</li>
        <li>后端根据风格预设自动拼接专业关键词，合成完整提示词</li>
        <li>后端调用对应的视觉大模型 API 生成图像</li>
        <li>图像保存到服务器并通过 URL 返回前端展示</li>
        <li>作品自动归档至画廊</li>
      </ol>

      <h3 style="color:var(--primary-dark); margin:20px 0 10px;">免责声明</h3>
      <p style="font-size:14px; color:var(--text-light);">
        本平台仅供学习交流使用，生成的图像版权归原始模型服务方所有。
        请勿将生成内容用于商业用途。
      </p>
    </div>
  </div>
</template>
