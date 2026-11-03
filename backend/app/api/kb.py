"""知识库文档管理接口：上传、列表、删除、单文档检索。"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User
from app.services import kb_document_service, kb_parser, kb_service

router = APIRouter(prefix="/kb", tags=["知识库"])

MAX_DOC_SIZE = 20 * 1024 * 1024  # 20MB


def _doc_dict(document) -> dict:
    return {
        "id": document.id,
        "filename": document.filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "status": document.status,
        "error": document.error,
        "create_time": document.create_time.isoformat() if document.create_time else None,
    }


@router.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise BusinessException(message="文件名不能为空")

    ext = f".{file.filename.rsplit('.', 1)[-1].lower()}"
    if ext not in kb_parser.SUPPORTED_EXTENSIONS:
        raise BusinessException(message=f"不支持的文件类型：{ext}")

    data = await file.read()
    if len(data) > MAX_DOC_SIZE:
        raise BusinessException(message="文档不能超过 20MB")

    document = kb_document_service.ingest_document(
        db, file.filename, file.content_type, data
    )
    return Response.success(data=_doc_dict(document))


@router.get("/documents")
def list_documents(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    documents = kb_document_service.list_documents(db)
    return Response.success(data=[_doc_dict(d) for d in documents])


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    kb_document_service.delete_document(db, document_id)
    return Response.success()


@router.get("/documents/{document_id}/search")
def search_document(
    document_id: str,
    query: str,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    text = kb_service.search_document(document_id, query)
    return Response.success(data={"answer": text})
