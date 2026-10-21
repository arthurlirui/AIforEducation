"""Composer: 从原始文档章节生成 frames.json。

规则模板保证离线可跑；LLM 可用时增强大纲与帧内容（compose_with_llm）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Section:
    """原始文档的一个语义小节。"""
    title: str
    body_md: str = ""
    code_blocks: list[dict] = field(default_factory=list)  # [{lang, src}]
    formula: str = ""
    anim_kind: str = ""  # "convolution"|"ofdm_subcarriers"|... 留给 AnimGen


@dataclass
class FrameSpec:
    index: int
    title: str
    layout: str
    blocks: list[dict]
    notes: str = ""

    def to_payload(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "layout": self.layout,
            "blocks_json": json.dumps(self.blocks, ensure_ascii=False),
            "notes": self.notes,
        }


# ---------- 学习路径模板 ----------
def outline(section: Section) -> list[str]:
    """从一节内容推断学习路径章节标题（动机→概念→示例→陷阱→进阶）。"""
    steps = ["为什么需要 " + section.title]
    if section.formula:
        steps.append(f"{section.title} 的数学表达")
    if section.code_blocks:
        steps.append(f"{section.title} 的最小示例")
    steps.append(f"{section.title} 的常见陷阱")
    steps.append(f"{section.title} 进阶")
    return steps


# ---------- 帧构造 ----------
def build_frames(section: Section) -> list[FrameSpec]:
    """把一节内容展开成帧序列。"""
    frames: list[FrameSpec] = []
    idx = 0

    # 封面帧
    frames.append(FrameSpec(
        index=idx, title=section.title, layout="title",
        blocks=[{"type": "text", "md": f"# {section.title}", "fragment": 0}],
        notes=f"本节讲解 {section.title}。",
    ))
    idx += 1

    # 动机帧
    motivation = section.body_md.split("\n")[0] if section.body_md else "（待补充动机）"
    frames.append(FrameSpec(
        index=idx, title=f"为什么需要 {section.title}", layout="two-col",
        blocks=[
            {"type": "text", "md": "## 问题\n" + motivation, "fragment": 0},
            {"type": "callout", "kind": "warn", "md": "如果不理解这个，后面会踩坑。", "fragment": 1},
        ],
    ))
    idx += 1

    # 公式帧
    if section.formula:
        frames.append(FrameSpec(
            index=idx, title=f"{section.title} 的数学表达", layout="formula",
            blocks=[
                {"type": "formula", "tex": section.formula, "explain": "关键定义。", "fragment": 0},
            ],
        ))
        idx += 1

    # 代码示例帧
    if section.code_blocks:
        cb = section.code_blocks[0]
        frames.append(FrameSpec(
            index=idx, title=f"{section.title} 的最小示例", layout="code-focus",
            blocks=[
                {"type": "code", "lang": cb.get("lang", "python"),
                 "src": cb.get("src", ""), "runnable": True, "fragment": 0},
                {"type": "callout", "kind": "tip", "md": "点击运行按钮试试。", "fragment": 1},
            ],
        ))
        idx += 1

    # 动画帧（Motion Canvas SVG 动画）
    if section.anim_kind:
        try:
            from anim_gen import generate as gen_anim
            anim_result = gen_anim(section.anim_kind, {})
            fallback_svg = anim_result.content
        except Exception:
            fallback_svg = "<svg/>"
        frames.append(FrameSpec(
            index=idx, title=f"{section.title} 可视化", layout="diagram",
            blocks=[
                {"type": "motionCanvas", "sceneRef": section.anim_kind,
                 "params": {}, "renderMode": "video",
                 "fallbackSvg": fallback_svg, "fragment": 0},
                {"type": "text", "md": "看动画理解原理。", "fragment": 1},
            ],
        ))
        idx += 1

    # 陷阱帧
    frames.append(FrameSpec(
        index=idx, title=f"{section.title} 的常见陷阱", layout="two-col",
        blocks=[
            {"type": "callout", "kind": "pitfall", "md": "新手常犯错误：忽略边界条件。", "fragment": 0},
            {"type": "text", "md": "记住：先想清楚再写代码。", "fragment": 1},
        ],
    ))
    idx += 1

    # 小结帧
    frames.append(FrameSpec(
        index=idx, title=f"{section.title} 小结", layout="summary",
        blocks=[
            {"type": "text", "md": "## 要点\n- 动机\n- 公式\n- 示例\n- 陷阱", "fragment": 0},
        ],
        notes="回顾本节要点。",
    ))
    return frames


def compose(section: Section) -> list[dict]:
    """完整流水线（规则模板）：返回帧 payload 列表（可直接推给 backend admin API）。"""
    frames = build_frames(section)
    return [f.to_payload() for f in frames]


# ---------- LLM 增强（M3） ----------

_OUTLINE_SYSTEM = """你是技术教学设计师。根据给定的技术主题和原始材料，生成一份学习路径大纲。
输出 JSON：{"steps": ["步骤1标题", "步骤2标题", ...]}
步骤应覆盖：动机→核心概念→数学/原理表达→最小示例→常见陷阱→进阶，5-7 步。"""

_FRAME_SYSTEM = """你是技术课件作者。根据给定的帧标题和上下文，生成该帧的内容块。
输出 JSON：{"blocks": [...], "notes": "演讲者备注"}
block 类型：
- {"type":"text","md":"markdown 文本","fragment":0}
- {"type":"code","lang":"python","src":"代码","runnable":true,"fragment":1}
- {"type":"formula","tex":"LaTeX 公式","explain":"解释","fragment":2}
- {"type":"callout","kind":"tip|warn|pitfall","md":"提示","fragment":3}
fragment 从 0 递增。代码必须可运行。"""


def compose_with_llm(section: Section, llm=None) -> list[dict]:
    """LLM 增强合成。llm 不可用时降级到规则模板 compose()。"""
    if llm is None:
        from ..llm import get_llm
        llm = get_llm()

    if not llm.available:
        return compose(section)

    # 1. LLM 生成大纲
    outline_resp = llm.chat_json(
        _OUTLINE_SYSTEM,
        f"主题：{section.title}\n原始材料：{section.body_md}",
    )
    if not outline_resp or "steps" not in outline_resp:
        return compose(section)

    steps = outline_resp["steps"][:7]  # 最多 7 步
    frames: list[FrameSpec] = []
    idx = 0

    # 封面帧（规则）
    frames.append(FrameSpec(
        index=idx, title=section.title, layout="title",
        blocks=[{"type": "text", "md": f"# {section.title}", "fragment": 0}],
        notes=f"本节讲解 {section.title}。",
    ))
    idx += 1

    # 2. 逐帧 LLM 生成内容
    for step_title in steps:
        layout = "two-col"
        if any(kw in step_title.lower() for kw in ["示例", "代码", "example", "code"]):
            layout = "code-focus"
        elif any(kw in step_title for kw in ["数学", "公式", "表达", "原理"]):
            layout = "formula"
        elif any(kw in step_title for kw in ["陷阱", "pitfall", "注意"]):
            layout = "two-col"
        elif any(kw in step_title for kw in ["小结", "总结", "要点"]):
            layout = "summary"

        frame_resp = llm.chat_json(
            _FRAME_SYSTEM,
            f"帧标题：{step_title}\n主题：{section.title}\n原始材料：{section.body_md}\n"
            f"公式：{section.formula or '无'}\n代码示例：{section.code_blocks[0]['src'] if section.code_blocks else '无'}",
        )

        if frame_resp and "blocks" in frame_resp:
            blocks = frame_resp["blocks"]
            notes = frame_resp.get("notes", "")
        else:
            # LLM 对单帧失败时用规则块降级
            blocks = [{"type": "text", "md": f"## {step_title}\n{section.body_md}", "fragment": 0}]
            notes = ""

        frames.append(FrameSpec(
            index=idx, title=step_title, layout=layout,
            blocks=blocks, notes=notes,
        ))
        idx += 1

    # 确保至少有代码帧（如果原始 section 有代码但 LLM 没生成）
    has_code = any(f.layout == "code-focus" for f in frames)
    if not has_code and section.code_blocks:
        cb = section.code_blocks[0]
        frames.append(FrameSpec(
            index=idx, title=f"{section.title} 代码示例", layout="code-focus",
            blocks=[
                {"type": "code", "lang": cb.get("lang", "python"),
                 "src": cb.get("src", ""), "runnable": True, "fragment": 0},
            ],
        ))
        idx += 1

    return [f.to_payload() for f in frames]

