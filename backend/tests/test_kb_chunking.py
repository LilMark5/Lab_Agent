"""递归切分器的单元测试。"""

from app.services import kb_chunking


def test_short_text_is_single_chunk():
    assert kb_chunking.split_text("实验室开放时间", 200, 40) == ["实验室开放时间"]


def test_split_respects_chunk_size():
    text = "。".join(["字" * 30 for _ in range(10)])
    chunks = kb_chunking.split_text(text, 200, 40)
    assert chunks
    assert all(len(c) <= 200 for c in chunks)


def test_merge_splits_keeps_overlap():
    splits = [c * 10 for c in "abcdefgh"]
    chunks = kb_chunking._merge_splits(splits, "\n", chunk_size=45, chunk_overlap=15)
    assert chunks == [
        "a" * 10 + "\n" + "b" * 10 + "\n" + "c" * 10 + "\n" + "d" * 10,
        "d" * 10 + "\n" + "e" * 10 + "\n" + "f" * 10 + "\n" + "g" * 10,
        "g" * 10 + "\n" + "h" * 10,
    ]


def test_load_kb_chunks_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(kb_chunking, "KB_DIR", tmp_path)
    (tmp_path / "开放时间.md").write_text(
        "实验室开放时间：周一至周五 8:00 到 22:00。", encoding="utf-8"
    )
    chunks = kb_chunking.load_kb_chunks()
    assert chunks
    assert chunks[0]["id"].startswith("开放时间#")
    assert chunks[0]["meta"]["source"] == "开放时间.md"
    assert chunks[0]["meta"]["chunk_index"] == 0
