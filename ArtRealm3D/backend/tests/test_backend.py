"""ArtRealm3D backend test suite."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.data.masterpieces import MASTERPIECES, get_masterpiece, list_masterpieces
from app.main import create_app
from app.services.renderer import RENDERERS, render_layer, render_layers_sorted


# --------------------------------------------------------------------------
# data layer
# --------------------------------------------------------------------------
class TestKnowledgeBase:
    def test_catalog_has_masterpieces(self):
        cats = list_masterpieces()
        assert len(cats) >= 3
        ids = {c["id"] for c in cats}
        assert {"starry-night", "great-wave", "girl-with-pearl"} <= ids

    @pytest.mark.parametrize("m", MASTERPIECES, ids=lambda m: m["id"])
    def test_entry_integrity(self, m):
        assert m["title"] and m["artist"] and m["year"]
        assert len(m["layers"]) >= 3
        assert len(m["chapters"]) >= 5
        assert len(m["quiz"]) >= 3
        # layers: unique roles, depths numeric, zdraw ordered set
        roles = [l["role"] for l in m["layers"]]
        assert len(roles) == len(set(roles))
        for l in m["layers"]:
            assert l["style"] in RENDERERS, f"unknown style {l['style']}"
            assert 3 <= len(l["palette"]) <= 4
        # chapters: narrative arc
        types = [c["type"] for c in m["chapters"]]
        assert types[0] == "intro" and types[-1] == "epilogue"
        assert "spirit" in types
        for c in m["chapters"]:
            assert c["text"] and len(c["text"]) >= 30
            assert c["focus"]["camera"] in {
                "overview", "close-up", "medium", "extreme-close-up", "pull-back",
            }
        # quiz: answer indexes valid, >=3 options
        for q in m["quiz"]:
            assert 0 <= q["answer"] < len(q["options"])
            assert len(q["options"]) >= 3

    def test_get_masterpiece_miss(self):
        assert get_masterpiece("nope") is None


# --------------------------------------------------------------------------
# renderer
# --------------------------------------------------------------------------
class TestRenderer:
    @pytest.mark.parametrize("m", MASTERPIECES, ids=lambda m: m["id"])
    def test_all_layers_render_valid_png(self, m):
        rendered = render_layers_sorted(m["layers"])
        assert len(rendered) == len(m["layers"])
        for r in rendered:
            img = Image.open(io.BytesIO(r["png"]))
            assert img.format == "PNG"
            assert img.size == (1024, 768)
            rgba = np.asarray(img.convert("RGBA"))
            # layer must contribute some visible (alpha>0) pixels
            assert rgba[..., 3].max() > 200, f"layer {r['role']} fully transparent"
            # foreground layers need real alpha transparency for compositing
            if r["role"] in ("boats", "pearl", "figure", "cypress"):
                assert rgba[..., 3].min() == 0, f"layer {r['role']} should be partially transparent"
            # backdrops must stay fully opaque（sea 例外：great-wave 的海浪
            # 需要透明镂空让天空层透出，故不在此列）
            if r["role"] in ("sky", "background"):
                assert (rgba[..., 3] == 255).all(), f"backdrop {r['role']} must be opaque"
            # visible content must not be pitch black
            vis = rgba[rgba[..., 3] > 0]
            assert vis[..., :3].mean() > 5.0, f"layer {r['role']} visible pixels too dark"

    def test_deterministic(self):
        m = MASTERPIECES[0]
        a = render_layers_sorted(m["layers"])
        b = render_layers_sorted(m["layers"])
        assert [x["png"] for x in a] == [x["png"] for x in b]

    def test_unknown_style_raises(self):
        with pytest.raises(ValueError):
            render_layer("no-such-style", ["#000000", "#ffffff"], {})

    def test_stroke_texture_changes_output_and_guards_empty_pixels(self):
        # 回归守卫：_stroke_texture 曾是彻底的 no-op（笔触画在临时副本上、
        # 却从原数组读回）。它必须真实改变输出……
        from app.services.renderer import H, W, _stroke_texture

        base = np.zeros((H, W, 3), dtype=np.uint8)
        base[200:300, 400:520] = (200, 180, 120)  # 黑底上一块凸形亮斑
        img = Image.fromarray(base, "RGB")
        out = _stroke_texture(img, 0.30, seed=5)
        out_arr = np.asarray(out)
        assert not np.array_equal(out_arr, base), "stroke texture must alter the image"

        # ……但只能落在基图有内容的像素上：空白区若被笔触抬亮，会超过
        # BLACK_ALPHA_THRESHOLD=12 而变不透明（"黑方块"级回归）
        empty = base.max(axis=-1) < 24
        assert (out_arr[empty] == 0).all(), "strokes must not touch empty (transparent) pixels"

    def test_stroke_texture_keeps_foreground_transparency(self, monkeypatch):
        # 完整渲染链路：带前景层的图层里，原本透明的像素在笔触生效后
        # 必须仍然透明（alpha <= BLACK_ALPHA_THRESHOLD=12）
        import app.services.renderer as renderer_module

        m = get_masterpiece("starry-night")
        cypress = [l for l in m["layers"] if l["role"] == "cypress"]
        real_stroke = renderer_module._stroke_texture
        monkeypatch.setattr(renderer_module, "_stroke_texture", lambda img, strength=0.12, seed=3: img)
        plain = render_layers_sorted(cypress)
        monkeypatch.setattr(renderer_module, "_stroke_texture", real_stroke)
        stroked = render_layers_sorted(cypress)

        assert plain[0]["png"] != stroked[0]["png"], "stroke must change the rendered layer"
        p = np.asarray(Image.open(io.BytesIO(plain[0]["png"])).convert("RGBA"))
        s = np.asarray(Image.open(io.BytesIO(stroked[0]["png"])).convert("RGBA"))
        was_transparent = p[..., 3] == 0
        assert was_transparent.any(), "cypress layer must have transparent regions"
        assert (s[was_transparent, 3] <= 12).all(), "strokes must not make empty pixels opaque"

    def test_star_layers_have_distinct_depth(self):
        m = get_masterpiece("starry-night")
        depths = sorted(l["depth"] for l in m["layers"])
        assert len(set(depths)) == len(depths)


# --------------------------------------------------------------------------
# asset pipeline
# --------------------------------------------------------------------------
class TestAssets:
    def test_ensure_assets_writes_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        from app.services import assets

        mid = "starry-night"
        out1 = assets.ensure_assets(mid)
        assert out1["layers"], "no layers produced"
        for layer in out1["layers"]:
            p = tmp_path / mid / out1["prefix"].split(f"/{mid}/")[-1] / Path(layer["url"]).name
            assert p.exists()
        # second call hits the manifest cache and returns same URLs
        out2 = assets.ensure_assets(mid)
        assert [l["url"] for l in out1["layers"]] == [l["url"] for l in out2["layers"]]

    def test_ensure_assets_unknown_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        from app.services import assets

        assert assets.ensure_assets("nope") == {}

    def test_renderer_code_sig_rotates_cache(self, tmp_path, monkeypatch):
        # 回归守卫：渲染器代码哈希必须参与缓存签名——代码一变，目录与 URL
        # 都要跟着变，否则会命中旧缓存让渲染修复静默失效（黑方块事件重演）
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        from app.services import assets

        mid = "starry-night"
        out1 = assets.ensure_assets(mid)
        url1 = out1["layers"][0]["url"]
        sig1 = out1["prefix"].rsplit("/", 1)[-1]
        assert (tmp_path / mid / sig1).exists()

        # 模拟"渲染器代码更新"：签名变化 → 新缓存目录 + 新 URL
        monkeypatch.setattr(assets, "_RENDERER_SIG", "deadbeefcafe")
        assert assets._layer_sig(mid) != sig1, "_layer_sig must depend on _RENDERER_SIG"
        out2 = assets.ensure_assets(mid)
        url2 = out2["layers"][0]["url"]
        sig2 = out2["prefix"].rsplit("/", 1)[-1]
        assert sig1 != sig2
        assert url1 != url2, "URL must change when renderer code changes (busts browser cache)"
        assert (tmp_path / mid / sig2).exists()

    def test_stale_sig_dirs_are_collected(self, tmp_path, monkeypatch):
        # 配套 GC：同 mid 下旧签名目录在 ensure_assets 时被清理，
        # 不随代码迭代无限堆积
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        from app.services import assets

        mid = "starry-night"
        out = assets.ensure_assets(mid)
        sig = out["prefix"].rsplit("/", 1)[-1]

        stale = tmp_path / mid / "00000000000old"
        stale.mkdir(parents=True)
        (stale / "sky.png").write_bytes(b"stale")

        assets.ensure_assets(mid)
        assert not stale.exists(), "old-signature cache dir must be garbage-collected"
        assert (tmp_path / mid / sig).exists(), "current-signature dir must survive"

    def test_corrupt_manifest_is_rebuilt(self, tmp_path, monkeypatch):
        # 自愈路径：manifest 写坏（如写入中途崩溃）时丢弃缓存重渲染
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        from app.services import assets

        mid = "starry-night"
        out1 = assets.ensure_assets(mid)
        sig_dir = tmp_path / mid / out1["prefix"].split(f"/{mid}/")[-1]
        (sig_dir / "manifest.json").write_text("{ this is not json", encoding="utf-8")

        out2 = assets.ensure_assets(mid)
        assert [l["url"] for l in out1["layers"]] == [l["url"] for l in out2["layers"]]
        manifest = json.loads((sig_dir / "manifest.json").read_text(encoding="utf-8"))
        assert "layers" in manifest, "corrupt manifest must be rebuilt with valid JSON"


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client(tmp_path_factory):
    out = tmp_path_factory.mktemp("static")
    settings.output_dir = out
    return TestClient(create_app())


class TestAPI:
    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["api_prefix"] == "/api"

    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_catalog(self, client):
        r = client.get("/api/masterpieces")
        assert r.status_code == 200
        body = r.json()
        assert len(body) >= 3
        for c in body:
            assert c["layer_count"] >= 3 and c["chapter_count"] >= 5

    @pytest.mark.parametrize("mid", ["starry-night", "great-wave", "girl-with-pearl"])
    def test_detail_with_layers(self, client, mid):
        r = client.get(f"/api/masterpieces/{mid}")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == mid
        assert len(d["layers"]) >= 3
        # every layer URL must be fetchable and a real PNG
        for layer in d["layers"]:
            assert layer["url"].startswith(settings.output_url_prefix)
            rr = client.get(layer["url"])
            assert rr.status_code == 200, layer["url"]
            img = Image.open(io.BytesIO(rr.content))
            assert img.format == "PNG"
        assert len(d["chapters"]) >= 5
        assert d["chapters"][0]["type"] == "intro"
        # 回归守卫：详情里的测验题绝不能携带 answer/explain（防提前泄露答案）
        for q in d["quiz"]:
            assert "answer" not in q, "detail response must not leak quiz answers"
            assert "explain" not in q, "detail response must not leak explanations"

    def test_detail_404(self, client):
        assert client.get("/api/masterpieces/nope").status_code == 404

    def test_quiz_flow(self, client):
        m = get_masterpiece("starry-night")
        good = [q["answer"] for q in m["quiz"]]
        r = client.post("/api/masterpieces/starry-night/quiz", json={"answers": good})
        assert r.status_code == 200
        body = r.json()
        assert body["correct"] == body["total"] and body["score"] == 1.0

        bad = [(a + 1) % len(m["quiz"][0]["options"]) for a in good]
        r2 = client.post("/api/masterpieces/starry-night/quiz", json={"answers": bad})
        assert r2.json()["correct"] == 0

    def test_quiz_wrong_count_400(self, client):
        r = client.post("/api/masterpieces/starry-night/quiz", json={"answers": [0]})
        assert r.status_code == 400
