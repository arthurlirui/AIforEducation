import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getStyles, getHealth, getArticles, getPrompts, getProviders } from '../api'

export const useStore = defineStore('app', () => {
  const styles = ref([])
  const articles = ref([])
  const prompts = ref([])
  const providers = ref([])
  const health = ref(null)
  const loaded = ref(false)

  async function bootstrap() {
    // Always fetch providers (may have changed); fetch rest only once
    try {
      if (!loaded.value) {
        const [s, h, a, p] = await Promise.all([
          getStyles(),
          getHealth().catch(() => null),
          getArticles().catch(() => []),
          getPrompts().catch(() => []),
        ])
        styles.value = s
        health.value = h
        articles.value = a
        prompts.value = p
      }
      // Always refresh providers
      providers.value = await getProviders().catch(() => [])
    } finally {
      loaded.value = true
    }
  }

  return { styles, articles, prompts, providers, health, loaded, bootstrap }
})
