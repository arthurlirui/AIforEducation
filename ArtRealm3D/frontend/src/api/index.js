import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 20000 })

export async function fetchCatalog() {
  const { data } = await http.get('/masterpieces')
  return data
}

export async function fetchMasterpiece(id) {
  const { data } = await http.get(`/masterpieces/${id}`)
  return data
}

export async function submitQuiz(id, answers) {
  const { data } = await http.post(`/masterpieces/${id}/quiz`, { answers })
  return data
}
