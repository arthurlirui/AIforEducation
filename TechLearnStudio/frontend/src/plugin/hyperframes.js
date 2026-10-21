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
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function renderText(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  // 简易 markdown：## → h2，# → h1，**bold** → <strong>，其余当 <p>
  let md = block.md || ''
  md = md.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  md = md.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  md = md.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  md = md.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  md = md.replace(/\n/g, '<br>')
  return `<div class="block-text ${frag}">${md}</div>`
}

function renderCode(block) {
  const frag = block.fragment !== undefined ? `fragment fade-up` : ''
  const runnable = block.runnable ? `data-runnable="true"` : ''
  const lang = block.lang || 'python'
  const id = `code-${Math.random().toString(36).slice(2, 8)}`
  return `<div class="block-code ${frag}" ${runnable} data-lang="${lang}" data-code-id="${id}">
    <pre><code data-code-id="${id}" class="language-${lang}">${escapeHtml(block.src || '')}</code></pre>
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
  return `<div class="block-callout callout-${block.kind || 'tip'} ${frag}">
    <span class="callout-icon">${block.kind === 'pitfall' ? '⚠️' : block.kind === 'warn' ? '⚠️' : '💡'}</span>
    ${escapeHtml(block.md || '')}
  </div>`
}

function renderMotionCanvas(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  // 优先内嵌 fallbackSvg（真实 SVG 动画），M4 已由 AnimGen 生成
  if (block.fallbackSvg && block.fallbackSvg !== '<svg/>') {
    return `<div class="block-mc ${frag}" data-mc-block="${escapeHtml(block.sceneRef || '')}">
      <div class="mc-svg-container">${block.fallbackSvg}</div>
    </div>`
  }
  // 无 SVG 时按需从后端加载（live 模式接口）
  return `<div class="block-mc ${frag}" data-mc-block="${escapeHtml(block.sceneRef || '')}" data-mc-needs-load="true">
    <div class="mc-placeholder">🎬 动画：${escapeHtml(block.sceneRef || '')}（加载中…）</div>
  </div>`
}

function renderQuiz(block) {
  const frag = block.fragment !== undefined ? 'fragment fade-up' : ''
  const opts = (block.opts || []).map((o, i) =>
    `<label><input type="radio" name="quiz" value="${i}"> ${escapeHtml(o)}</label>`
  ).join('')
  return `<div class="block-quiz ${frag}" data-answer="${block.answer}" data-why="${escapeHtml(block.why || '')}">
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
  const inner = blocks.map(renderBlock).join('\n')
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
        container.innerHTML = `<div class="mc-svg-container">${data.content}</div>`
      } catch (err) {
        container.innerHTML = `<div class="mc-placeholder">动画加载失败：${escapeHtml(String(err))}</div>`
      }
    })
  })

  // quiz 提交
  sections.forEach(el => {
    el.querySelectorAll('.quiz-submit').forEach(btn => {
      btn.addEventListener('click', () => {
        const quiz = btn.closest('.block-quiz')
        const answer = parseInt(quiz.getAttribute('data-answer'))
        const why = quiz.getAttribute('data-why')
        const selected = quiz.querySelector('input[name="quiz"]:checked')
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

export { framesToHTML, frameToSection, renderBlock, bindInteractions, escapeHtml }
