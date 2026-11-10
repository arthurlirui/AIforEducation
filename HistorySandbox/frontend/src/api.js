async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    // FastAPI wraps structured errors as {"detail": {...}} (e.g. 409
    // {reason, message} from the world model) — parse it once here so
    // callers can read err.detail instead of string-archaeology.
    let detail = null
    try { detail = JSON.parse(body)?.detail ?? null } catch { /* non-JSON body */ }
    const err = new Error(`API ${resp.status}: ${body || resp.statusText}`)
    err.detail = detail
    throw err
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
