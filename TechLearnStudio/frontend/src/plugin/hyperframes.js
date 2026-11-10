/**
 * hyperframes 插件层（~250 行）
 *
 * 职责：
 *  1. frames.json → reveal.js <section> 序列化渲染
 *  2. 跨帧超链接路由（data-frame-link → Reveal.slide）
 *  3. sandbox 运行按钮绑定（data-runnable → /api/sandbox/run）
 *  4. Motion Canvas block 挂载（video 模式用 <video>，live 留接口）
 *
 * 不重新实现 reveal.js 幻灯内核，也不重新实现动画引擎。
 */

// ---------- block → HTML 渲染 ----------

function escapeHtml(s) {
  // 覆盖 & < > " '（引号必须转义：本函数大量用于双引号属性插值上下文）
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&#34;')
    .replace(/'/g, '&#39;')
}

// SVG 白名单：只接受以 <svg 开头、且不含 script/事件处理器/javascript: 协议的字符串。
// fallbackSvg 与 /api/anim/render 响应都来自不可信内容（LLM/公开端点），注入前必须过检（B1/S6）。
function isSafeSvg(svg) {
  if (typeof svg !== 'string') return false
  const s = svg.trim()
  if (!s.startsWith('<svg')) return false
  if (/<script/i.test(s)) return false
  if (/\son\w+\s*=/i.test(s)) return false
  if (/javascript:/i.test(s)) return false
  return true
}

function renderText(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  // 安全 markdown：先整体 escapeHtml，再做受限替换。
  // 行级结构（标题/列表/引用）逐行处理；行内强调的内容模式不含 '<'，不会跨越已生成的 HTML 标签。
  const esc = escapeHtml(block.md || '')
  const out = []
  let listBuf = null
  const flushList = () => { if (listBuf) { out.push(`<ul>${listBuf.join('')}</ul>`); listBuf = null } }
  for (const line of esc.split('\n')) {
    let m
    if ((m = line.match(/^### (.*)$/))) { flushList(); out.push(`<h3>${m[1]}</h3>`) }
    else if ((m = line.match(/^## (.*)$/))) { flushList(); out.push(`<h2>${m[1]}</h2>`) }
    else if ((m = line.match(/^# (.*)$/))) { flushList(); out.push(`<h1>${m[1]}</h1>`) }
    else if ((m = line.match(/^&gt; ?(.*)$/))) { flushList(); out.push(`<blockquote>${m[1]}</blockquote>`) }
    else if ((m = line.match(/^- (.*)$/))) {
      if (!listBuf) listBuf = []
      listBuf.push(`<li>${m[1]}</li>`)
    }
    else { flushList(); out.push(line) }
  }
  flushList()
  let md = out.join('\n')
  md = md.replace(/\*\*([^*<]+)\*\*/g, '<strong>$1</strong>')
  md = md.replace(/\*([^*<]+)\*/g, '<em>$1</em>')
  md = md.replace(/`([^`<]+)`/g, '<code>$1</code>')
  md = md.replace(/\n/g, '<br>')
  return `<div class="block-text ${frag}">${md}</div>`
}

function renderCode(block) {
  const frag = block.fragment !== undefined ? `fragment fade-up` : ''
  const runnable = block.runnable ? `data-runnable="true"` : ''
  const lang = block.lang || 'python'
  const id = `code-${Math.random().toString(36).slice(2, 8)}`
  return `<div class="block-code ${frag}" ${runnable} data-lang="${escapeHtml(lang)}" data-code-id="${id}">
    <pre><code data-code-id="${id}" class="language-${escapeHtml(lang)}">${escapeHtml(block.src || '')}</code></pre>
    ${block.runnable ? `<button class="run-btn" data-code-id="${id}">▶ 运行</button>` : ''}
    <div class="run-output" data-output-for="${id}"></div>
  </div>`
}

function renderFormula(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  // 用 KaTeX CDN（App.vue 引入），这里只写容器
  return `<div class="block-formula ${frag}" data-tex="${escapeHtml(block.tex || '')}">
    <div class="katex-container"></div>
    ${block.explain ? `<p class="formula-explain">${escapeHtml(block.explain)}</p>` : ''}
  </div>`
}

function renderCallout(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  return `<div class="block-callout callout-${escapeHtml(block.kind || 'tip')} ${frag}">
    <span class="callout-icon">${block.kind === 'pitfall' ? '⚠️' : block.kind === 'warn' ? '⚠️' : '💡'}</span>
    ${escapeHtml(block.md || '')}
  </div>`
}

function renderMotionCanvas(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  const sceneRef = escapeHtml(block.sceneRef || '')
  // 优先内嵌 fallbackSvg（真实 SVG 动画），M4 已由 AnimGen 生成
  if (block.fallbackSvg && block.fallbackSvg !== '<svg/>') {
    if (isSafeSvg(block.fallbackSvg)) {
      return `<div class="block-mc ${frag}" data-mc-block="${sceneRef}">
        <div class="mc-svg-container">${block.fallbackSvg}</div>
      </div>`
    }
    // 不合规的 SVG 一律拒绝注入，渲染占位提示（B1）
    return `<div class="block-mc ${frag}" data-mc-block="${sceneRef}">
      <div class="mc-placeholder">🎬 动画内容未通过安全校验，已拒绝渲染</div>
    </div>`
  }
  // 无 SVG 时按需从后端加载（live 模式接口）
  return `<div class="block-mc ${frag}" data-mc-block="${sceneRef}" data-mc-needs-load="true">
    <div class="mc-placeholder">🎬 动画：${sceneRef}（加载中…）</div>
  </div>`
}

let _quizSeq = 0

function renderQuiz(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  // 每个 quiz block 独立的单选组（F3）：同帧/跨帧多个测验互不干扰
  const name = `quiz-${++_quizSeq}`
  const opts = (block.opts || []).map((o, i) =>
    `<label><input type="radio" name="${name}" value="${i}"> ${escapeHtml(o)}</label>`
  ).join('')
  return `<div class="block-quiz ${frag}" data-answer="${escapeHtml(block.answer)}" data-why="${escapeHtml(block.why || '')}">
    <p>${escapeHtml(block.q || '')}</p>
    ${opts}
    <button class="quiz-submit">提交</button>
    <div class="quiz-feedback"></div>
  </div>`
}

function renderLink(block) {
  return `<a class="block-link" data-frame-link="${escapeHtml(block.to || '')}">${escapeHtml(block.label || '→')}</a>`
}

function renderBlock(block) {
  switch (block.type) {
    case 'text': return renderText(block)
    case 'code': return renderCode(block)
    case 'formula': return renderFormula(block)
    case 'callout': return renderCallout(block)
    case 'motionCanvas': return renderMotionCanvas(block)
    case 'quiz': return renderQuiz(block)
    case 'link': return renderLink(block)
    default: return `<div class="block-unknown">${escapeHtml(JSON.stringify(block))}</div>`
  }
}

// ---------- frames → <section> ----------

function frameToSection(frame) {
  let blocks
  try {
    blocks = typeof frame.blocks_json === 'string' ? JSON.parse(frame.blocks_json) : (frame.blocks_json || [])
  } catch {
    blocks = []
  }
  if (!Array.isArray(blocks)) blocks = []
  // 逐块容错（S1）：坏块渲染为错误占位，不炸整课
  const inner = blocks.map((b, i) => {
    try {
      return renderBlock(b)
    } catch (err) {
      return `<div class="block-error">⚠ 内容块 #${i} 渲染失败：${escapeHtml(String(err && err.message || err))}</div>`
    }
  }).join('\n')
  return `<section data-frame-id="${frame.id || frame.course_id + '#' + frame.index}" data-layout="${frame.layout || 'title'}">
    <h2>${escapeHtml(frame.title || '')}</h2>
    ${inner}
    ${frame.notes ? `<aside class="notes">${escapeHtml(frame.notes)}</aside>` : ''}
  </section>`
}

function framesToHTML(frames) {
  return `<div class="reveal"><div class="slides">${frames.map(frameToSection).join('\n')}</div></div>`
}

// ---------- 交互绑定 ----------

function bindInteractions(reveal, sections, frames, apiBase) {
  // 跨帧超链接
  sections.forEach(el => {
    el.querySelectorAll('[data-frame-link]').forEach(a => {
      a.style.cursor = 'pointer'
      a.addEventListener('click', e => {
        e.preventDefault()
        const targetId = a.getAttribute('data-frame-link')
        const idx = frames.findIndex(f => f.id === targetId)
        if (idx >= 0) reveal.slide(idx)
      })
    })
  })

  // sandbox 运行按钮
  sections.forEach(el => {
    el.querySelectorAll('.run-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const codeId = btn.getAttribute('data-code-id')
        const codeEl = el.querySelector(`code[data-code-id="${codeId}"]`)
        const output = el.querySelector(`[data-output-for="${codeId}"]`)
        const lang = el.querySelector(`[data-code-id="${codeId}"]`)?.getAttribute('data-lang') || 'python'
        if (!codeEl || !output) return
        const code = codeEl.textContent
        output.innerHTML = '<em>运行中…</em>'
        try {
          const r = await fetch(`${apiBase}/api/sandbox/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lang, code }),
          })
          const data = await r.json()
          output.innerHTML = `<pre>${escapeHtml(data.stdout || '')}\n${escapeHtml(data.stderr || '')}</pre>`
        } catch (err) {
          output.innerHTML = `<pre style="color:red">运行失败：${escapeHtml(String(err))}</pre>`
        }
      })
    })
  })

  // MC 按需加载（无内嵌 SVG 时从后端获取）
  sections.forEach(el => {
    el.querySelectorAll('[data-mc-needs-load="true"]').forEach(async (container) => {
      const sceneRef = container.getAttribute('data-mc-block')
      try {
        const r = await fetch(`${apiBase}/api/anim/render`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sceneRef, params: {} }),
        })
        const data = await r.json()
        // anim 响应内容同样过 SVG 白名单（B1/S6）
        if (r.ok && isSafeSvg(data.content)) {
          container.innerHTML = `<div class="mc-svg-container">${data.content}</div>`
        } else {
          container.innerHTML = `<div class="mc-placeholder">动画加载失败：内容未通过安全校验</div>`
        }
      } catch (err) {
        container.innerHTML = `<div class="mc-placeholder">动画加载失败：${escapeHtml(String(err))}</div>`
      }
    })
  })

  // KaTeX 公式渲染（F1）：App.vue 动态加载 katex + auto-render；
  // 未加载/渲染失败时保留现有 explain 文本展示，不崩。
  sections.forEach(el => {
    el.querySelectorAll('.block-formula[data-tex]').forEach(f => {
      const tex = f.getAttribute('data-tex') || ''
      const container = f.querySelector('.katex-container')
      if (!tex || !container) return
      if (typeof window.renderMathInElement !== 'function') return
      try {
        container.textContent = `\\(${tex}\\)`
        window.renderMathInElement(container, {
          delimiters: [
            { left: '\\(', right: '\\)', display: false },
            { left: '$$', right: '$$', display: true },
          ],
          throwOnError: false,
        })
      } catch { /* 公式渲染失败：保留 explain 文本 */ }
    })
  })

  // quiz 提交
  sections.forEach(el => {
    el.querySelectorAll('.quiz-submit').forEach(btn => {
      btn.addEventListener('click', () => {
        const quiz = btn.closest('.block-quiz')
        const answer = parseInt(quiz.getAttribute('data-answer'))
        const why = quiz.getAttribute('data-why')
        const selected = quiz.querySelector('input[type="radio"]:checked')
        const fb = quiz.querySelector('.quiz-feedback')
        if (!selected) { fb.innerHTML = '<em>请选择一个答案</em>'; return }
        const val = parseInt(selected.value)
        if (val === answer) {
          fb.innerHTML = `<span style="color:#4f4">✓ 正确</span> ${escapeHtml(why)}`
        } else {
          fb.innerHTML = `<span style="color:#f44">✗ 不对</span> ${escapeHtml(why)}`
        }
      })
    })
  })
}

export { framesToHTML, frameToSection, renderBlock, bindInteractions, escapeHtml, isSafeSvg }
