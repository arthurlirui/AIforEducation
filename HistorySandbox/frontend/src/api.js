const BASE = import.meta.env.DEV ? '' : ''

async function request(path, options = {}) {
  const resp = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => resp.statusText)
    throw new Error(`API ${resp.status}: ${detail}`)
  }
  return resp.json()
}

export function fetchEvents() {
  return request('/api/events')
}

export function fetchEvent(id) {
  return request(`/api/events/${encodeURIComponent(id)}`)
}

export function fetchNarration(eventId, stepId, style = 'immersive') {
  return request('/api/narrate', {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId, step_id: stepId, style }),
  })
}

export function askAI(eventId, stepId, question) {
  return request('/api/ask', {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId, step_id: stepId, question, top_k: 3 }),
  })
}

export function simulate(eventId, stepId, command) {
  return request('/api/simulate', {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId, step_id: stepId, seed: 42, ...command }),
  })
}
