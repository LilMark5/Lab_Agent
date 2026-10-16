"""知识库切块：零依赖的递归字符切分器。

思路对齐 LangChain 的 RecursiveCharacterTextSplitter：
1. 优先在更“粗”的分隔符处切（段落 > 换行 > 句子标点 > 空格 > 单字符）。
2. 切不动的长片段递归地换下一级分隔符继续切。
3. 合并片段时保留 overlap，避免语义刚好卡在边界时丢失上下文。

用 len() 计长度，按字符切，对中文更直接，不引入 langchain-text-splitters 依赖。
"""

import re

from app.config import KB_DIR, settings

SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def _split_with_regex(text: str, separator: str) -> list[str]:
    """按分隔符切分，分隔符本身丢弃；空串过滤掉。"""
    if separator == "":
        return list(text)
    parts = re.split(re.escape(separator), text)
    return [part for part in parts if part]


def _merge_splits(splits: list[str], separator: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """把切出来的小片段合并成不超过 chunk_size、且带 overlap 的块。"""
    separator_len = len(separator)
    docs: list[str] = []
    current: list[str] = []
    total = 0

    for part in splits:
        part_len = len(part)
        # 当前块已经装不下这一片时，先落盘，再按 overlap 从头部裁剪。
        if current and total + part_len + (separator_len if current else 0) > chunk_size:
            docs.append(separator.join(current))
            while current and total > chunk_overlap:
                removed = len(current[0]) + (separator_len if len(current) > 1 else 0)
                total -= removed
                current.pop(0)

        current.append(part)
        total += part_len + (separator_len if len(current) > 1 else 0)

    if current:
        docs.append(separator.join(current))
    return docs


def _split_recursive(
    text: str, separators: list[str], chunk_size: int, chunk_overlap: int
) -> list[str]:
    """递归切分：先找第一个能命中的分隔符，再处理切不动的长片段。"""
    final: list[str] = []
    separator = separators[-1]
    new_separators: list[str] = []

    for index, candidate in enumerate(separators):
        if candidate == "":
            separator = candidate
            break
        if candidate in text:
            separator = candidate
            new_separators = separators[index + 1 :]
            break

    splits = _split_with_regex(text, separator)
    good_splits: list[str] = []

    for part in splits:
        if len(part) < chunk_size:
            good_splits.append(part)
        else:
            if good_splits:
                final.extend(_merge_splits(good_splits, separator, chunk_size, chunk_overlap))
                good_splits = []
            if not new_separators:
                # 已经没有更细的分隔符，按字符硬切，保证不会丢超长内容。
                final.append(part)
            else:
                final.extend(
                    _split_recursive(part, new_separators, chunk_size, chunk_overlap)
                )

    if good_splits:
        final.extend(_merge_splits(good_splits, separator, chunk_size, chunk_overlap))
    return [chunk for chunk in final if chunk.strip()]


def split_text(
    text: str, chunk_size: int | None = None, chunk_overlap: int | None = None
) -> list[str]:
    """把一个长文本切成带 overlap 的块。"""
    size = chunk_size or settings.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP
    if overlap >= size:
        overlap = max(0, size // 4)

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    return _split_recursive(text, SEPARATORS, size, overlap)


def load_kb_chunks() -> list[dict]:
    """读取知识库目录下的所有 Markdown，切成带元数据的块。"""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    chunks: list[dict] = []
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        for index, chunk_text in enumerate(split_text(text)):
            chunks.append(
                {
                    "id": f"{path.stem}#{index}",
                    "doc": chunk_text,
                    "meta": {
                        "source": path.name,
                        "chunk_index": index,
                        "document_id": "static",
                    },
                }
            )
    return chunks


def chunk_document_text(document_id: str, filename: str, text: str) -> list[dict]:
    """把一份上传文档的纯文本切成带 document_id 的块。"""
    chunks: list[dict] = []
    for index, chunk_text in enumerate(split_text((text or "").strip())):
        chunks.append(
            {
                "id": f"{document_id}#{index}",
                "doc": chunk_text,
                "meta": {
                    "source": filename,
                    "chunk_index": index,
                    "document_id": document_id,
                },
            }
        )
    return chunks


def load_source_text(source_name: str) -> str | None:
    """按文件名读取知识库源文档全文，用于父上下文扩展。"""
    path = KB_DIR / source_name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
