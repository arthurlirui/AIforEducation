"""工作流模板加载与参数注入。

模板以 ComfyUI 导出的 **API 格式 JSON** 为基础（节点为 dict，key 为节点 id）。
运行时按节点 id 与字段名注入参数；用户可在 workflows/ 放同名文件覆盖内置模板。
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def load_template(name: str, workflows_dir: Path | None = None) -> dict[str, Any]:
    """加载工作流模板。workflows_dir 下的同名文件优先于内置 templates。"""
    fname = name if name.endswith(".json") else f"{name}.json"
    if workflows_dir is not None:
        override = workflows_dir / fname
        if override.exists():
            logger.info("使用自定义工作流: %s", override)
            return json.loads(override.read_text(encoding="utf-8"))
    builtin = TEMPLATES_DIR / fname
    if not builtin.exists():
        raise FileNotFoundError(f"工作流模板不存在: {name}（查找路径: {builtin}）")
    return json.loads(builtin.read_text(encoding="utf-8"))


def apply_params(template: dict[str, Any], params: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """按 {node_id: {field: value}} 注入参数到工作流副本。

    支持注入 inputs 子字段；若 field 含 '.'，按路径深入（如 'inputs.text'）。
    """
    wf = copy.deepcopy(template)
    for node_id, fields in params.items():
        if node_id not in wf:
            logger.warning("节点 %s 不在模板中，跳过", node_id)
            continue
        node = wf[node_id]
        for field, value in fields.items():
            if "." in field:
                # 路径注入：inputs.text
                obj = node
                keys = field.split(".")
                for k in keys[:-1]:
                    obj = obj.setdefault(k, {})
                obj[keys[-1]] = value
            else:
                node.setdefault("inputs", {})[field] = value
    return wf


def set_seed(wf: dict[str, Any], node_id: str, seed: int | None = None) -> None:
    """给 KSampler / sampler 节点设置 seed（None 随机）。"""
    import random
    s = seed if seed is not None else random.randint(0, 2**63 - 1)
    wf[node_id]["inputs"]["seed"] = s


def list_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.json"))
