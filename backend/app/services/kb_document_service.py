"""知识库文档服务：注册、解析、切块入库、删除。"""

import hashlib
import uuid

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.kb_document import KbDocument
from app.services import kb_chunking, kb_parser, kb_service, vector_store


def ingest_document(
    db: Session, filename: str, content_type: str | None, data: bytes
) -> KbDocument:
    """解析并入库一份文档；内容完全相同时直接复用已有记录。"""
    sha256 = hashlib.sha256(data).hexdigest()
    existing = (
        db.query(KbDocument)
        .filter(KbDocument.sha256 == sha256, KbDocument.status == "ready")
        .first()
    )
    if existing:
        return existing

    try:
        text = kb_parser.parse_bytes(filename, data)
    except ValueError as exc:
        raise BusinessException(message=str(exc)) from exc
    if not text.strip():
        raise BusinessException(message="文档解析后没有可用文本")

    document = KbDocument(
        id=uuid.uuid4().hex,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256,
        status="ready",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        store = vector_store.get_vector_store()
        if store is None:
            raise BusinessException(message="向量库不可用")
        chunks = kb_chunking.chunk_document_text(document.id, filename, text)
        store.add_chunks(chunks)
        kb_service.invalidate_cache()
    except Exception as exc:
        document.status = "failed"
        document.error = str(exc)[:500]
        db.commit()
        raise BusinessException(message=f"文档入库失败：{exc}") from exc

    return document


def delete_document(db: Session, document_id: str) -> None:
    document = db.get(KbDocument, document_id)
    if not document:
        raise BusinessException(message="文档不存在")
    store = vector_store.get_vector_store()
    if store is not None:
        store.delete_chunks(document_id)
    kb_service.invalidate_cache()
    db.delete(document)
    db.commit()


def list_documents(db: Session) -> list[KbDocument]:
    return (
        db.query(KbDocument)
        .order_by(KbDocument.create_time.desc())
        .all()
    )
