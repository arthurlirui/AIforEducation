"""AnimGen: Motion Canvas 场景生成。

M4 实现：生成可播放的 SVG 动画（SMIL/CSS），不依赖 MC npm 包或 ffmpeg。
Backend 托管 SVG 文件，前端用 <iframe> 或内联 <svg> 播放。
API 兼容设计文档：sceneRef → scene 代码 → 渲染产物。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AnimResult:
    scene_ref: str
    content: str       # SVG 动画内容
    content_type: str  # "image/svg+xml"
    duration_s: float


# ---------- 模板库 ----------

def _convolution_svg(signal: list[float], kernel: list[float], mode: str = "full") -> str:
    """卷积滑窗动画：核滑过信号，逐点相乘累加。"""
    n = len(signal)
    m = len(kernel)
    out_n = n + m - 1 if mode == "full" else n
    w, h = 600, 300
    bar_w = 40
    gap = 10
    total_w = max(n, out_n) * (bar_w + gap) + 60

    # 信号条
    signal_bars = ""
    for i, v in enumerate(signal):
        x = 30 + i * (bar_w + gap)
        bh = max(10, abs(v) * 60)
        y = 120 - bh
        signal_bars += f'<rect class="sig-{i}" x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="#58a6ff" rx="3"/>'
        signal_bars += f'<text x="{x+bar_w/2}" y="140" text-anchor="middle" font-size="12" fill="#aaa">{v}</text>'

    # 核（滑动窗口）
    kernel_rects = ""
    for j in range(m):
        kernel_rects += f'<rect class="ker-{j}" x="0" y="0" width="{bar_w}" height="100" fill="none" stroke="#e94560" stroke-width="2" rx="3"/>'

    # 输出条
    output_bars = ""
    for i in range(out_n):
        x = 30 + i * (bar_w + gap)
        output_bars += f'<rect class="out-{i}" x="{x}" y="220" width="{bar_w}" height="0" fill="#4f4" rx="3" opacity="0.3"/>'

    # 动画：核从左滑到右
    slide_dur = 4.0
    max_slide = (n - 1) * (bar_w + gap)
    anim = f"""
    <animateTransform class="kernel-slide"
        attributeName="transform" type="translate"
        from="30 20" to="{30 + max_slide} 20"
        dur="{slide_dur}s" repeatCount="indefinite"/>
    """

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(total_w, 400)} {h}" style="background:#0d1117;border-radius:8px;">
  <text x="20" y="20" fill="#8b949e" font-size="14">信号</text>
  <text x="20" y="210" fill="#8b949e" font-size="14">输出 (卷积结果)</text>
  <g class="signal">{signal_bars}</g>
  <g class="kernel">{kernel_rects}{anim}</g>
  <g class="output">{output_bars}</g>
  <text x="50%" y="280" text-anchor="middle" fill="#666" font-size="12">卷积动画: 核(红框)滑过信号(蓝条) → 输出(绿条)</text>
</svg>"""
    return svg


def _ownership_move_svg(vars: list[str] = None, move_from: str = "s", move_to: str = "t") -> str:
    """Rust 所有权移动动画：指针从 from 迁移到 to。"""
    vars = vars or ["s", "t"]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 250" style="background:#0d1117;border-radius:8px;">
  <!-- 内存块 -->
  <rect x="200" y="80" width="100" height="60" fill="#1a3a5a" stroke="#58a6ff" stroke-width="2" rx="8"/>
  <text x="250" y="115" text-anchor="middle" fill="#58a6ff" font-size="16">"hi"</text>
  <text x="250" y="70" text-anchor="middle" fill="#8b949e" font-size="12">Heap 内存</text>

  <!-- 变量 s -->
  <rect class="var-s" x="80" y="80" width="60" height="40" fill="#238636" stroke="#4f4" stroke-width="2" rx="6"/>
  <text x="110" y="105" text-anchor="middle" fill="#fff" font-size="14">s</text>
  <!-- 箭头 s → 内存 -->
  <line x1="140" y1="100" x2="200" y2="100" stroke="#4f4" stroke-width="2" marker-end="url(#arrow)"/>

  <!-- 变量 t -->
  <rect class="var-t" x="360" y="80" width="60" height="40" fill="#333" stroke="#666" stroke-width="2" rx="6" opacity="0">
    <animate attributeName="opacity" values="0;1" dur="0.5s" begin="1s" fill="freeze"/>
  </rect>
  <text x="390" y="105" text-anchor="middle" fill="#aaa" font-size="14" opacity="0">
    t
    <animate attributeName="opacity" values="0;1" dur="0.5s" begin="1s" fill="freeze"/>
  </text>
  <!-- 箭头 t → 内存 -->
  <line x1="360" y1="100" x2="300" y2="100" stroke="#e94560" stroke-width="2" marker-end="url(#arrow-red)" opacity="0">
    <animate attributeName="opacity" values="0;1" dur="0.5s" begin="1.5s" fill="freeze"/>
  </line>

  <!-- s 变灰 -->
  <rect class="var-s-gray" x="80" y="80" width="60" height="40" fill="#333" stroke="#666" stroke-width="2" rx="6" opacity="0">
    <animate attributeName="opacity" values="0;1" dur="0.5s" begin="2s" fill="freeze"/>
  </rect>
  <line x1="140" y1="100" x2="200" y2="100" stroke="#666" stroke-width="2" stroke-dasharray="5,5" opacity="0">
    <animate attributeName="opacity" values="0;0.5" dur="0.5s" begin="2s" fill="freeze"/>
  </line>

  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
      <path d="M0,0 L0,6 L9,3 z" fill="#4f4"/>
    </marker>
    <marker id="arrow-red" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
      <path d="M0,0 L0,6 L9,3 z" fill="#e94560"/>
    </marker>
  </defs>
  <text x="50%" y="200" text-anchor="middle" fill="#8b949e" font-size="13">let t = s; — 所有权从 s 移动到 t，s 失效</text>
  <text x="50%" y="225" text-anchor="middle" fill="#666" font-size="11">1s: t 出现 → 1.5s: t 指向内存 → 2s: s 变灰失效</text>
</svg>"""
    return svg


def _ofdm_svg(n_subcarriers: int = 4, symbols: list[float] = None, show_fft: bool = True) -> str:
    """OFDM 子载波叠加动画。"""
    import math
    n = n_subcarriers
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300" style="background:#0d1117;border-radius:8px;">
  <text x="300" y="20" text-anchor="middle" fill="#8b949e" font-size="14">OFDM: {n} 个正交子载波叠加</text>
  <line x1="50" y1="150" x2="550" y2="150" stroke="#333" stroke-width="1"/>"""

    colors = ["#58a6ff", "#4f4", "#e94560", "#ffa500", "#a855f7", "#06b6d4"]
    for i in range(n):
        color = colors[i % len(colors)]
        freq = (i + 1) * 2
        path_d = "M50,150 "
        for x in range(500):
            xp = 50 + x
            y = 150 + 40 * math.sin(freq * x * 0.012)
            path_d += f"L{xp},{y:.1f} "
        svg += f'<path d="{path_d}" stroke="{color}" stroke-width="1.5" fill="none" opacity="0.7">'
        svg += f'<animate attributeName="opacity" values="0;0.7" dur="0.5s" begin="{i*0.3}s" fill="freeze"/></path>'

    svg += '<text x="300" y="280" text-anchor="middle" fill="#666" font-size="12">子载波逐个出现并叠加 → OFDM 符号</text></svg>'
    return svg


def _attention_flow_svg(seq_len: int = 4, heads: int = 1, weights: list = None) -> str:
    """注意力矩阵热力图动画。"""
    n = seq_len
    cell = 50
    ox, oy = 150, 50
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 350" style="background:#0d1117;border-radius:8px;">
  <text x="250" y="25" text-anchor="middle" fill="#8b949e" font-size="14">Attention 权重矩阵 ({n}×{n})</text>
  <text x="{ox-20}" y="{oy+n*cell/2}" text-anchor="middle" fill="#666" font-size="12" transform="rotate(-90 {ox-20} {oy+n*cell/2})">Query</text>
  <text x="{ox+n*cell/2}" y="{oy+n*cell+30}" text-anchor="middle" fill="#666" font-size="12">Key</text>"""

    for i in range(n):
        for j in range(n):
            x = ox + j * cell
            y = oy + i * cell
            w = (weights[i * n + j] if weights and i * n + j < len(weights) else (0.25 if i == j else 0.1))
            intensity = min(1, w * 3)
            r = int(88 + (255 - 88) * intensity)
            g = int(166 - 166 * intensity)
            b = int(255 - 255 * intensity)
            delay = (i * n + j) * 0.15
            svg += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="rgb({r},{g},{b})" stroke="#333" opacity="0">'
            svg += f'<animate attributeName="opacity" values="0;1" dur="0.3s" begin="{delay}s" fill="freeze"/></rect>'
            svg += f'<text x="{x+cell/2}" y="{y+cell/2+5}" text-anchor="middle" fill="#fff" font-size="11" opacity="0">'
            svg += f'{w:.2f}<animate attributeName="opacity" values="0;1" dur="0.3s" begin="{delay+0.2}s" fill="freeze"/></text>'

    svg += '<text x="250" y="330" text-anchor="middle" fill="#666" font-size="12">softmax(QK^T/√d) — 权重逐格出现</text></svg>'
    return svg


# ---------- 模板注册 ----------

TEMPLATES = {
    "convolution": {
        "render": lambda params: _convolution_svg(
            params.get("signal", [1, 2, 3, 1]),
            params.get("kernel", [1, 0, -1]),
            params.get("mode", "full"),
        ),
        "duration": 4.0,
    },
    "ownership_move": {
        "render": lambda params: _ownership_move_svg(
            params.get("vars"),
            params.get("move_from", "s"),
            params.get("move_to", "t"),
        ),
        "duration": 3.0,
    },
    "ofdm_subcarriers": {
        "render": lambda params: _ofdm_svg(
            params.get("n_subcarriers", 4),
            params.get("symbols"),
            params.get("show_fft", True),
        ),
        "duration": 3.0,
    },
    "attention_flow": {
        "render": lambda params: _attention_flow_svg(
            params.get("seq_len", 4),
            params.get("heads", 1),
            params.get("weights"),
        ),
        "duration": 3.0,
    },
}


# ---------- 生成 + 渲染 ----------

def generate(scene_ref: str, params: dict | None = None) -> AnimResult:
    """从模板生成 SVG 动画。找不到模板时返回 fallback。"""
    params = params or {}
    template = TEMPLATES.get(scene_ref)
    if not template:
        return AnimResult(
            scene_ref=scene_ref,
            content=_fallback_svg(scene_ref),
            content_type="image/svg+xml",
            duration_s=2.0,
        )
    svg = template["render"](params)
    return AnimResult(
        scene_ref=scene_ref,
        content=svg,
        content_type="image/svg+xml",
        duration_s=template["duration"],
    )


def scene_hash(scene_ref: str, params: dict) -> str:
    """对 scene + params 算 hash，用于缓存。"""
    raw = f"{scene_ref}:{json.dumps(params, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def save_svg(result: AnimResult, output_dir: Path) -> Path:
    """把渲染结果保存为 SVG 文件，返回文件路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    h = scene_hash(result.scene_ref, {})
    path = output_dir / f"{result.scene_ref}_{h}.svg"
    path.write_text(result.content, encoding="utf-8")
    return path


def _fallback_svg(scene_ref: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200" style="background:#0d1117;border-radius:8px;">
  <text x="200" y="100" text-anchor="middle" fill="#666" font-size="14">动画模板 "{scene_ref}" 未找到</text>
  <text x="200" y="130" text-anchor="middle" fill="#444" font-size="12">显示静态降级图</text>
</svg>"""
