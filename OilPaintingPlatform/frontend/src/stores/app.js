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
  const error = ref('')

  async function bootstrap() {
    // Always fetch providers (may have changed); fetch rest only once
    error.value = ''
    try {
      providers.value = await getProviders().catch(() => [])
      if (!loaded.value) {
        const [s, h, a, p] = await Promise.all([
          // styles 是核心数据：不加 catch，失败时保持 loaded=false，
          // 下一次 bootstrap() 会重试
          getStyles(),
          getHealth().catch(() => null),
          getArticles().catch(() => []),
          getPrompts().catch(() => []),
        ])
        styles.value = s
        health.value = h
        articles.value = a
        prompts.value = p
        // 只有 styles 加载成功才置 true，避免坏状态永久固化
        loaded.value = true
      }
    } catch (e) {
      error.value = '数据加载失败，请检查网络或后端服务后重试'
    }
  }

  return { styles, articles, prompts, providers, health, loaded, error, bootstrap }
})
