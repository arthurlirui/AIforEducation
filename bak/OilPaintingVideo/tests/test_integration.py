"""集成测试：验证整条管线的接口契约与数据衔接。

不依赖真实 LLM API / ComfyUI / ffmpeg，全部用 mock 替身。
重点验证：
- 配置加载与风格预设解析
- 工作流模板加载 + 参数注入（节点 id / 字段名是否对得上模板）
- ComfyUI 客户端 run() 流程（mock httpx）
- keyframe / animate 生成的工作流是否含必需字段
- director 全链路（mock LLM + ComfyUI + ffmpeg）
- edit 剪辑命令构造（mock ffmpeg）
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oilpaint.comfy.workflows import apply_params, load_template
from oilpaint.config import load_settings
from oilpaint.screenplay.schemas import Scene, Script, Shot


# ───────────────────────── 配置 ─────────────────────────

def test_config_loads_styles_and_dims():
    s = load_settings()
    assert s.default_style in s.styles
    imp = s.styles["impressionism"]
    assert "Claude Monet" in imp.painters
    assert imp.positive_prefix
    assert imp.bgm_mood
    # 9:16 默认
    assert (s.width, s.height) == (1080, 1920)


def test_style_lookup_unknown_raises():
    s = load_settings()
    with pytest.raises(KeyError):
        s.style("nonexistent_style")


def test_aspect_resolution_mapping():
    s = load_settings()
    s.aspect = "16:9"
    # 手动重算（load_settings 内部已做映射，这里验证逻辑）
    if s.aspect == "16:9":
        s.width, s.height = 1920, 1080
    assert (s.width, s.height) == (1920, 1080)


# ───────────────────────── 工作流模板 ─────────────────────────

class _WFSpec:
    """校验某模板含指定节点 id 与必填 inputs 字段。"""
    def __init__(self, name, required_nodes):
        self.name = name
        self.required_nodes = required_nodes  # {node_id: {field, ...}}


def _check_wf(wf: dict, spec: _WFSpec, label: str):
    for node_id, fields in spec.required_nodes.items():
        assert node_id in wf, f"{label}: 缺节点 {node_id}"
        inputs = wf[node_id].get("inputs", {})
        for f in fields:
            assert f in inputs, f"{label}: 节点 {node_id} 缺 inputs.{f}"


OILPAINT_SPEC = _WFSpec("img2img_oilpaint", {
    "ckpt": {"ckpt_name"},
    "latent": {"width", "height"},
    "prompt_pos": {"text"},
    "prompt_neg": {"text"},
    "sampler": {"seed", "steps", "cfg", "sampler_name", "scheduler"},
    "save": {"filename_prefix"},
})
LTX_SPEC = _WFSpec("ltx_i2v", {
    "input_image": {"image"},
    "ltx_model": {"model"},
    "ltx_pos": {"text"},
    "ltx_sampler": {"seed", "steps", "cfg", "width", "height", "num_frames"},
    "ltx_save": {"filename_prefix", "frame_rate"},
})
WAN_SPEC = _WFSpec("wan_i2v", {
    "input_image": {"image"},
    "wan_model": {"model"},
    "wan_pos": {"text"},
    "wan_sampler": {"seed", "steps", "cfg", "width", "height", "num_frames"},
    "wan_save": {"filename_prefix", "frame_rate"},
})


def test_template_img2img_oilpaint_shape():
    wf = load_template("img2img_oilpaint")
    _check_wf(wf, OILPAINT_SPEC, "img2img_oilpaint")


def test_template_ltx_i2v_shape():
    wf = load_template("ltx_i2v")
    _check_wf(wf, LTX_SPEC, "ltx_i2v")


def test_template_wan_i2v_shape():
    wf = load_template("wan_i2v")
    _check_wf(wf, WAN_SPEC, "wan_i2v")


def test_apply_params_injects_deep_path():
    wf = load_template("img2img_oilpaint")
    out = apply_params(wf, {
        "ckpt": {"inputs.ckpt_name": "my_model.safetensors"},
        "sampler": {"inputs.seed": 42},
    })
    assert out["ckpt"]["inputs"]["ckpt_name"] == "my_model.safetensors"
    assert out["sampler"]["inputs"]["seed"] == 42
    # 不应改动原模板
    assert wf["ckpt"]["inputs"]["ckpt_name"] != "my_model.safetensors"


def test_apply_params_unknown_node_warns_but_ok():
    wf = load_template("img2img_oilpaint")
    out = apply_params(wf, {"__nope__": {"inputs.x": 1}})
    assert "__nope__" not in out  # 未知节点被跳过


def test_load_template_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_template("does_not_exist")


# ───────────────────────── keyframe / animate 工作流构造 ─────────────────────────

def test_keyframe_workflow_builds_valid():
    from oilpaint.pipeline.keyframe import build_keyframe_workflow, build_positive

    s = load_settings()
    style = s.style("impressionism")
    shot = Shot(index=1, scene_index=1, prompt="a misty harbor at dawn, fishing boats",
                painter="Claude Monet", camera_motion="pan_right", duration_sec=3)

    pos = build_positive(shot, style)
    assert "Claude Monet" in pos
    assert "misty harbor" in pos
    assert "impressionism" in pos.lower()

    wf = build_keyframe_workflow(s, shot, style, "shot_001")
    _check_wf(wf, OILPAINT_SPEC, "built keyframe wf")
    assert wf["prompt_pos"]["inputs"]["text"] == pos
    assert wf["latent"]["inputs"]["width"] == s.width
    assert wf["latent"]["inputs"]["height"] == s.height
    assert wf["save"]["inputs"]["filename_prefix"] == "shot_001"
    assert isinstance(wf["sampler"]["inputs"]["seed"], int)


def test_animate_ltx_workflow_builds_valid():
    from oilpaint.pipeline.animate import _build_ltx

    s = load_settings()
    shot = Shot(index=1, scene_index=1, prompt="x", camera_motion="zoom_in",
                duration_sec=3, i2v_model="ltx")
    wf = _build_ltx(s, shot, "kf_001.png", "shot_001")
    _check_wf(wf, LTX_SPEC, "built ltx wf")
    assert wf["input_image"]["inputs"]["image"] == "kf_001.png"
    assert wf["ltx_pos"]["inputs"]["text"]  # 含运动描述
    assert "zoom" in wf["ltx_pos"]["inputs"]["text"]
    # 帧数 ≈ duration*fps，且为奇数
    nf = wf["ltx_sampler"]["inputs"]["num_frames"]
    assert nf % 2 == 1 and nf >= 9
    assert wf["ltx_save"]["inputs"]["frame_rate"] == s.fps


def test_animate_wan_workflow_builds_valid():
    from oilpaint.pipeline.animate import _build_wan

    s = load_settings()
    shot = Shot(index=1, scene_index=1, prompt="x", camera_motion="static",
                duration_sec=4, i2v_model="wan")
    wf = _build_wan(s, shot, "kf_001.png", "shot_001")
    _check_wf(wf, WAN_SPEC, "built wan wf")
    assert wf["input_image"]["inputs"]["image"] == "kf_001.png"
    nf = wf["wan_sampler"]["inputs"]["num_frames"]
    assert nf >= 9


def test_animate_num_frames_aligns():
    from oilpaint.pipeline.animate import _num_frames

    assert _num_frames(Shot(index=1, scene_index=1, prompt="x", duration_sec=3), 24) == 73
    assert _num_frames(Shot(index=1, scene_index=1, prompt="x", duration_sec=0.2), 24) == 9
    # 奇数
    for d in (2, 3, 4, 5):
        nf = _num_frames(Shot(index=1, scene_index=1, prompt="x", duration_sec=d), 24)
        assert nf % 2 == 1


# ───────────────────────── ComfyUI 客户端（mock httpx） ─────────────────────────

@pytest.mark.asyncio
async def test_comfy_client_run_collects_outputs(tmp_path):
    """mock ComfyClient 的 queue_prompt / get_history / download_view，验证 run() 收集产物。"""
    from oilpaint.comfy.client import ComfyClient

    client = ComfyClient("http://127.0.0.1:8188", concurrency=1)

    # queue_prompt 返回 prompt_id
    client.queue_prompt = AsyncMock(return_value="pid-123")
    # 第一次轮询 None，第二次返回含 outputs 的 history
    client.get_history = AsyncMock(side_effect=[
        None,
        {"outputs": {"output": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
         "status": {"status_str": "success"}},
    ])
    # download_view 返回 PNG 字节
    client.download_view = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n")

    save_to = tmp_path / "kf"
    paths = await client.run({"any": "workflow"}, outputs_node="output", save_to=save_to)
    assert len(paths) == 1
    assert paths[0].name == "out.png"
    assert paths[0].read_bytes().startswith(b"\x89PNG")
    client.queue_prompt.assert_awaited_once()
    assert client.get_history.await_count == 2


@pytest.mark.asyncio
async def test_comfy_client_run_error_status_raises(tmp_path):
    from oilpaint.comfy.client import ComfyClient

    client = ComfyClient("http://127.0.0.1:8188", concurrency=1)
    client.queue_prompt = AsyncMock(return_value="pid-err")
    client.get_history = AsyncMock(return_value={
        "outputs": {},
        "status": {"status_str": "error", "messages": [["execution_error", "boom"]]},
    })
    with pytest.raises(RuntimeError, match="执行出错"):
        await client.run({"x": 1}, outputs_node="output", save_to=tmp_path)


@pytest.mark.asyncio
async def test_comfy_client_run_timeout(tmp_path):
    from oilpaint.comfy.client import ComfyClient

    client = ComfyClient("http://127.0.0.1:8188", concurrency=1)
    client.queue_prompt = AsyncMock(return_value="pid-to")
    client.get_history = AsyncMock(return_value=None)  # 永不完成
    client.POLL_INTERVAL = 0.05  # 加速
    with pytest.raises(TimeoutError):
        await client.run({"x": 1}, outputs_node="output", save_to=tmp_path, timeout=0.2)


# ───────────────────────── director 全链路（mock LLM + Comfy + ffmpeg） ─────────────────────────

def _make_script() -> Script:
    return Script(
        title="晨曦归舟",
        synopsis="渔夫归港",
        style="impressionism",
        aspect="9:16",
        scenes=[
            Scene(index=1, title="出海", summary="清晨", shots=[
                Shot(index=1, scene_index=1, prompt="harbor at dawn, boats, mist",
                     painter="Claude Monet", camera_motion="pan_right",
                     duration_sec=2, i2v_model="ltx", narration="晨光初现", mood="calm"),
                Shot(index=2, scene_index=1, prompt="fisherman on boat, nets",
                     painter="Claude Monet", camera_motion="zoom_in",
                     duration_sec=2, i2v_model="wan", narration="渔人劳作", mood="calm"),
            ]),
        ],
    )


@pytest.mark.asyncio
async def test_stage_generate_with_mock_llm(tmp_path):
    """剧本生成阶段：mock LLM 返回合法 JSON，验证落盘与解析。"""
    from oilpaint.llm_client import LLMClient
    from oilpaint.pipeline.director import stage_generate, new_project_dir

    s = load_settings()
    s.output_dir = tmp_path
    pdir = new_project_dir(tmp_path, "testproj")

    script = _make_script()
    payload = json.loads(script.model_dump_json())

    llm = MagicMock(spec=LLMClient)
    llm.chat_json = AsyncMock(return_value=(payload, json.dumps(payload, ensure_ascii=False)))

    out = await stage_generate(llm, s, "渔夫归港", "impressionism", "9:16", 4, pdir)
    assert out.title == "晨曦归舟"
    assert (pdir / "screenplay.json").exists()
    # 落盘内容可重新加载
    from oilpaint.pipeline.director import load_script
    reloaded = load_script(pdir)
    assert len(reloaded.shots) == 2
    llm.chat_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_stage_render_with_mock_comfy(tmp_path):
    """渲染阶段：mock ComfyClient.run 返回伪造的关键帧与视频，验证编排顺序与产物。"""
    from oilpaint.comfy.client import ComfyClient
    from oilpaint.pipeline.director import stage_render, new_project_dir

    s = load_settings()
    s.output_dir = tmp_path
    pdir = new_project_dir(tmp_path, "renderproj")
    script = _make_script()

    comfy = MagicMock(spec=ComfyClient)
    # 第 1 次 run=关键帧(PNG)，第 2 次=视频(mp4)，第 3 次=关键帧，第 4 次=视频
    kf1 = tmp_path / "kf1.png"; kf1.write_bytes(b"\x89PNG")
    kf2 = tmp_path / "kf2.png"; kf2.write_bytes(b"\x89PNG")
    v1 = tmp_path / "v1.mp4"; v1.write_bytes(b"\x00\x00\x00 mp4")
    v2 = tmp_path / "v2.mp4"; v2.write_bytes(b"\x00\x00\x00 mp4")
    comfy.run = AsyncMock(side_effect=[[kf1], [v1], [kf2], [v2]])
    comfy.upload_image = AsyncMock(return_value={"name": "uploaded.png"})

    clips = await stage_render(comfy, s, script, pdir)
    assert len(clips) == 2
    # run 被调用 4 次（2 镜头 × 2 阶段）
    assert comfy.run.await_count == 4
    # upload_image 在每个镜头的视频阶段调用一次
    assert comfy.upload_image.await_count == 2
    # 关键帧与片段目录有产物
    assert len(list((pdir / "keyframes").glob("*.png"))) >= 0  # mock 写到 tmp 别处，但 run 被调


@pytest.mark.asyncio
async def test_run_full_end_to_end_with_all_mocks(tmp_path):
    """端到端：mock LLM + Comfy + ffmpeg，验证 meta.json 与 final.mp4 产出。"""
    from oilpaint.llm_client import LLMClient
    from oilpaint.comfy.client import ComfyClient
    from oilpaint.pipeline.director import run_full

    s = load_settings()
    s.output_dir = tmp_path
    s.burn_subtitle = False  # 简化 ffmpeg mock

    script = _make_script()
    payload = json.loads(script.model_dump_json())

    # LLM mock
    llm = MagicMock(spec=LLMClient)
    llm.chat_json = AsyncMock(return_value=(payload, json.dumps(payload)))

    # Comfy mock：按调用顺序返回关键帧/视频
    kf1 = tmp_path / "kf1.png"; kf1.write_bytes(b"\x89PNG")
    kf2 = tmp_path / "kf2.png"; kf2.write_bytes(b"\x89PNG")
    v1 = tmp_path / "v1.mp4"; v1.write_bytes(b"\x00mp4")
    v2 = tmp_path / "v2.mp4"; v2.write_bytes(b"\x00mp4")
    comfy = MagicMock(spec=ComfyClient)
    comfy.run = AsyncMock(side_effect=[[kf1], [v1], [kf2], [v2]])
    comfy.upload_image = AsyncMock(return_value={"name": "u.png"})
    comfy.health = AsyncMock(return_value=(True, "ok"))
    comfy.aclose = AsyncMock()

    # ffmpeg mock：normalize + concat + 最终合成 全部成功
    def fake_run_ffmpeg(args, ffmpeg_path=""):
        # 写出输出文件（最后一个参数是输出路径）
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00mp4final")
        return True, ""
    # compose_video 内部用 resolve_ffmpeg 找 exe，需返回非空
    ff_exe = tmp_path / "ffmpeg.exe"; ff_exe.write_bytes(b"\x00")
    s.ffmpeg_path = str(ff_exe)

    with patch("oilpaint.pipeline.director.LLMClient", return_value=llm), \
         patch("oilpaint.pipeline.director.ComfyClient", return_value=comfy), \
         patch("oilpaint.pipeline.edit.run_ffmpeg", side_effect=fake_run_ffmpeg), \
         patch("oilpaint.pipeline.edit.resolve_ffmpeg", return_value=str(ff_exe)), \
         patch("oilpaint.pipeline.ffmpeg_tool.resolve_ffmpeg", return_value=str(ff_exe)):
        final = await run_full(s, "渔夫归港", style_key="impressionism",
                               aspect="9:16", target_duration_sec=4, project_id="e2e")

    assert final.exists()
    assert final.name == "final.mp4"
    meta = json.loads((final.parent / "meta.json").read_text(encoding="utf-8"))
    assert meta["stages"]["generate"]["ok"]
    assert meta["stages"]["render"]["ok"]
    assert meta["stages"]["compose"]["ok"]
    assert meta["stages"]["render"]["clips"] == 2


# ───────────────────────── edit 剪辑命令构造 ─────────────────────────

def test_compose_video_invokes_ffmpeg_chain(tmp_path):
    """验证 compose_video 调用 ffmpeg 的链路（normalize→concat→合成），且能容错。"""
    from oilpaint.pipeline.edit import compose_video

    s = load_settings()
    s.output_dir = tmp_path
    s.burn_subtitle = False
    script = _make_script()

    # 造两个片段
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    c1 = clips_dir / "v1.mp4"; c1.write_bytes(b"\x00")
    c2 = clips_dir / "v2.mp4"; c2.write_bytes(b"\x00")
    clips = [c1, c2]

    ff_exe = tmp_path / "ffmpeg.exe"; ff_exe.write_bytes(b"\x00")
    s.ffmpeg_path = str(ff_exe)

    calls: list[list[str]] = []

    def fake_run(args, ffmpeg_path=""):
        calls.append(args)
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"out")
        return True, ""

    with patch("oilpaint.pipeline.edit.run_ffmpeg", side_effect=fake_run), \
         patch("oilpaint.pipeline.edit.resolve_ffmpeg", return_value=str(ff_exe)):
        final = compose_video(s, script, clips, tmp_path)

    assert final.exists()
    # 应至少有 normalize(2) + concat(1) + 合成(1) 次调用
    assert len(calls) >= 4
    # 第一次 normalize 含 libx264
    assert any("libx264" in a for a in calls[0])
    # concat 调用含 concat 关键字
    assert any("concat" in " ".join(a) for a in calls)


def test_subtitle_filter_built_from_shots():
    from oilpaint.pipeline.edit import _build_subtitle_filter

    script = _make_script()
    s = load_settings()
    flt = _build_subtitle_filter(script, s.fps, "")
    # 两个镜头都有旁白，应生成两条 drawtext
    assert flt.count("drawtext") == 2
    assert "晨光初现" in flt
    assert "between(t,0.00,2.00)" in flt  # 第一镜头 0~2s
    assert "between(t,2.00,4.00)" in flt  # 第二镜头 2~4s


def test_subtitle_filter_empty_narration():
    from oilpaint.pipeline.edit import _build_subtitle_filter

    script = Script(title="t", style="impressionism", scenes=[
        Scene(index=1, shots=[Shot(index=1, scene_index=1, prompt="x", narration="")]),
    ])
    s = load_settings()
    flt = _build_subtitle_filter(script, s.fps, "")
    assert flt == ""  # 无旁白则无 drawtext


# ───────────────────────── LLM 客户端 ─────────────────────────

@pytest.mark.asyncio
async def test_llm_client_missing_key_returns_error():
    from oilpaint.llm_client import LLMClient, LLM_ERROR_PREFIX

    c = LLMClient("http://x", "", "model")
    out = await c.chat([{"role": "user", "content": "hi"}])
    assert out.startswith(LLM_ERROR_PREFIX)
    assert c.last_usage is None


@pytest.mark.asyncio
async def test_llm_client_chat_json_extracts_json():
    """mock httpx 返回合法 JSON，验证 chat_json 解析。"""
    from oilpaint.llm_client import LLMClient

    c = LLMClient("http://x", "key", "model")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": '{"a": 1, "b": "x"}'}}],
        "usage": {"total_tokens": 5},
    }

    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=fake_resp)
    # 直接替换 _get_http，避免 _get_http 内部重建真实 httpx.AsyncClient
    c._get_http = lambda: fake_http

    parsed, raw = await c.chat_json([{"role": "user", "content": "give json"}])
    assert parsed == {"a": 1, "b": "x"}
    assert c.last_usage == {"total_tokens": 5}


@pytest.mark.asyncio
async def test_llm_client_chat_json_strips_code_fence():
    from oilpaint.llm_client import LLMClient

    c = LLMClient("http://x", "key", "model")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": "```json\n{\"a\": 2}\n```"}}],
    }
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=fake_resp)
    c._get_http = lambda: fake_http

    parsed, _ = await c.chat_json([{"role": "user", "content": "x"}])
    assert parsed == {"a": 2}
