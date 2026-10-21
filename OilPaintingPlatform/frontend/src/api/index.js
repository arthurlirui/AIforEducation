import axios from 'axios'

// Vite dev proxy forwards /api and /files to the FastAPI backend.
const http = axios.create({
  baseURL: '/api',
  timeout: 180000,
})

export async function getHealth() {
  const { data } = await http.get('/health')
  return data
}

export async function getStyles() {
  const { data } = await http.get('/styles')
  return data
}

export async function getStyle(id) {
  const { data } = await http.get(`/styles/${id}`)
  return data
}

export async function generateImage(payload) {
  const { data } = await http.post('/generate', payload)
  return data
}

export async function getArticles() {
  const { data } = await http.get('/teaching')
  return data
}

export async function getArticle(id) {
  const { data } = await http.get(`/teaching/${id}`)
  return data
}

export async function getGallery(limit = 50) {
  const { data } = await http.get('/gallery', { params: { limit } })
  return data
}

export async function getPrompts(category = null) {
  const params = category ? { category } : {}
  const { data } = await http.get('/prompts', { params })
  return data
}

export async function getPromptCategories() {
  const { data } = await http.get('/prompts/categories')
  return data
}

export async function getProviders() {
  const { data } = await http.get('/providers')
  return data
}

export default http
