// PaintingStudio 前端 API 客户端 (§3.5 读写 API 总表)
const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function req(method, url, body, isForm = false) {
  const opts = { method }
  if (body !== undefined) {
    if (isForm) opts.body = body
    else { opts.body = JSON.stringify(body); opts.headers = JSON_HEADERS }
  }
  const r = await fetch(url, opts)
  if (r.status === 204) return null
  const ct = r.headers.get('content-type') || ''
  const data = ct.includes('json') ? await r.json() : await r.blob()
  if (!r.ok) {
    const msg = data && data.detail ? data.detail : `${r.status} ${r.statusText}`
    throw new Error(msg)
  }
  return data
}

export const api = {
  // projects
  listProjects: () => req('GET', '/api/projects'),
  createProject: (name, file) => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('painting', file)
    return req('POST', '/api/projects', fd, true)
  },
  getProject: (pid) => req('GET', `/api/projects/${pid}`),
  deleteProject: (pid) => req('DELETE', `/api/projects/${pid}`),
  paintingUrl: (pid, thumb = false) =>
    `/api/projects/${pid}/painting${thumb ? '?thumb=true' : ''}`,
  depthUrl: (pid) => `/api/projects/${pid}/depth`,
  maskUrl: (pid, oid) => `/api/projects/${pid}/objects/${oid}/mask`,
  plyUrl: (pid, oid, version) =>
    `/api/projects/${pid}/gs/${oid}/ply${version != null ? `?version=${version}` : ''}`,

  // objects / segment
  listObjects: (pid) => req('GET', `/api/projects/${pid}/objects`),
  updateObject: (pid, oid, patch) => req('PUT', `/api/projects/${pid}/objects/${oid}`, patch),
  paintMask: (pid, oid, payload) => req('PUT', `/api/projects/${pid}/objects/${oid}/mask`, payload),
  runSegment: (pid, params = {}) => req('POST', `/api/projects/${pid}/segment/run`, params),

  // gs
  runGs: (pid, objectIds = []) => req('POST', `/api/projects/${pid}/gs/run`, { object_ids: objectIds }),

  // scene
  getScene: (pid) => req('GET', `/api/projects/${pid}/scene`),
  patchScene: (pid, patches) => req('PATCH', `/api/projects/${pid}/scene`, patches),
  addNode: (pid, node) => req('POST', `/api/projects/${pid}/scene/nodes`, node),
  deleteNode: (pid, nodeId) => req('DELETE', `/api/projects/${pid}/scene/nodes/${nodeId}`),
  putCamera: (pid, camera) => req('PUT', `/api/projects/${pid}/scene/camera`, camera),
  snapshot: (pid) => req('POST', `/api/projects/${pid}/scene/snapshot`),

  // keyframes
  listKeyframes: (pid) => req('GET', `/api/projects/${pid}/keyframes`),
  keyframeUrl: (pid, kid, kind = 'rgb') =>
    `/api/projects/${pid}/keyframes/${kid}/image?kind=${kind}`,
  uploadLineart: (pid, kid, pngB64) =>
    req('POST', `/api/projects/${pid}/keyframes/${kid}/lineart`, { png_b64: pngB64 }),

  // compose
  runCompose: (pid, params) => req('POST', `/api/projects/${pid}/compose/run`, params),

  // tasks / undo
  listTasks: () => req('GET', '/api/tasks'),
  getTask: (tid) => req('GET', `/api/tasks/${tid}`),
  cancelTask: (tid) => req('POST', `/api/tasks/${tid}/cancel`),
  undo: (pid) => req('POST', `/api/projects/${pid}/undo`),
  redo: (pid) => req('POST', `/api/projects/${pid}/undo/redo`),
}

/** 轮询任务到终态 */
export async function waitTask(taskId, onProgress, intervalMs = 400, timeoutMs = 300000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const t = await api.getTask(taskId)
    if (onProgress) onProgress(t)
    if (['done', 'failed', 'cancelled'].includes(t.status)) return t
    await new Promise(r => setTimeout(r, intervalMs))
  }
  throw new Error('任务超时')
}
