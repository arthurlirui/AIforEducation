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
            # backdrops must stay fully opaque
            if r["role"] in ("sky", "background", "sea") and r["role"] != "sea":
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
