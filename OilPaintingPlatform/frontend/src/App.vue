<script setup>
import { onMounted } from 'vue'
import { useStore } from './stores/app'
import NavBar from './components/NavBar.vue'
import SiteFooter from './components/SiteFooter.vue'

const store = useStore()
onMounted(() => store.bootstrap())
</script>

<template>
  <div class="app-layout">
    <NavBar />
    <main class="app-main">
      <router-view />
    </main>
    <SiteFooter />
  </div>
</template>
