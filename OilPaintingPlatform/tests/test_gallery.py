"""generate_service._append_gallery 并发与截断测试（2.1）."""
from __future__ import annotations

import json
import threading

from app.schemas import GeneratedImage, StylePreset
from app.services import generate_service


def _img(i: int) -> GeneratedImage:
    return GeneratedImage(url=f"/files/img_{i}.png", provider="mock")


def _style() -> StylePreset:
    return StylePreset(id="t", name="T", name_en="T", era="T", description="")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_concurrent_appends_lose_nothing(tmp_path, monkeypatch):
    """并发读-改-写必须由锁串行化：8 线程各追加 1 条 → 8 条全在."""
    index = tmp_path / "gallery.json"
    monkeypatch.setattr(generate_service, "GALLERY_INDEX", index)

    threads = [
        threading.Thread(
            target=generate_service._append_gallery,
            args=([_img(i)], "prompt", _style(), "mock"),
        )
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = _read(index)
    assert len(entries) == 8
    urls = {e["url"] for e in entries}
    assert urls == {f"/files/img_{i}.png" for i in range(8)}


def test_gallery_capped_at_200_keeps_newest(tmp_path, monkeypatch):
    index = tmp_path / "gallery.json"
    monkeypatch.setattr(generate_service, "GALLERY_INDEX", index)

    prefill = [
        {"id": f"old{i}", "url": f"/files/old_{i}.png", "prompt": "p",
         "style_id": "t", "style_name": "T", "provider": "mock",
         "created_at": "2026-01-01T00:00:00"}
        for i in range(200)
    ]
    index.write_text(json.dumps(prefill), encoding="utf-8")

    generate_service._append_gallery([_img(1), _img(2), _img(3)], "new", _style(), "mock")

    entries = _read(index)
    assert len(entries) == 200
    # 旧记录被截断，新记录保留在末尾
    urls = [e["url"] for e in entries[-3:]]
    assert urls == ["/files/img_1.png", "/files/img_2.png", "/files/img_3.png"]
    assert "/files/old_0.png" not in {e["url"] for e in entries}


def test_corrupted_gallery_file_recovers(tmp_path, monkeypatch):
    index = tmp_path / "gallery.json"
    monkeypatch.setattr(generate_service, "GALLERY_INDEX", index)
    index.write_text("not valid json {{{", encoding="utf-8")

    generate_service._append_gallery([_img(9)], "p", _style(), "mock")

    entries = _read(index)
    assert len(entries) == 1
    assert entries[0]["url"] == "/files/img_9.png"


def test_empty_images_no_write(tmp_path, monkeypatch):
    index = tmp_path / "gallery.json"
    monkeypatch.setattr(generate_service, "GALLERY_INDEX", index)
    generate_service._append_gallery([], "p", _style(), "mock")
    assert not index.exists()


def test_creates_file_when_missing(tmp_path, monkeypatch):
    index = tmp_path / "gallery.json"
    monkeypatch.setattr(generate_service, "GALLERY_INDEX", index)
    generate_service._append_gallery([_img(0)], "p", _style(), "mock")
    assert index.exists()
    assert len(_read(index)) == 1
