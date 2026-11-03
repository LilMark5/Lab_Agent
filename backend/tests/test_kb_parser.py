"""文档解析与动态切块的单元测试。"""

import pytest

from app.services import kb_chunking, kb_parser


def test_parse_text_file():
    assert kb_parser.parse_bytes("说明.txt", "hello".encode("utf-8")) == "hello"


def test_parse_unsupported_extension():
    with pytest.raises(ValueError):
        kb_parser.parse_bytes("恶意.exe", b"x")


def test_chunk_document_text_carries_document_id():
    text = "这是第一句。" * 50
    chunks = kb_chunking.chunk_document_text("doc1", "说明.md", text)
    assert chunks
    assert chunks[0]["id"].startswith("doc1#")
    assert chunks[0]["meta"]["document_id"] == "doc1"
