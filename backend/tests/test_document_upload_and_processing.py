from __future__ import annotations

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.services.document_processing_service import DocumentProcessingService


def _build_pdf_bytes(text: str) -> bytes:
    content_stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj",
        f"4 0 obj << /Length {len(content_stream)} >> stream\n".encode("latin-1")
        + content_stream
        + b"\nendstream endobj",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
        pdf.extend(b"\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))

    pdf.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
    )
    return bytes(pdf)


def test_document_upload_and_processing(client, seed_org, monkeypatch):
    captured_task: dict[str, object] = {}

    def capture_add_task(self, func, *args, **kwargs):
        captured_task["func"] = func
        captured_task["args"] = args
        captured_task["kwargs"] = kwargs

    def fake_embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        return [[0.05] * 1536 for _ in chunks]

    monkeypatch.setattr(BackgroundTasks, "add_task", capture_add_task)
    monkeypatch.setattr(DocumentProcessingService, "embed_chunks", fake_embed_chunks)

    pdf_bytes = _build_pdf_bytes(
        "Acme says to isolate the price objection. Then restate value clearly before the close."
    )
    response = client.post(
        "/manager/documents",
        data={"name": "Price Objection Playbook", "manager_id": seed_org["manager_id"]},
        files={"file": ("playbook.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    document_id = body["id"]

    db = SessionLocal()
    document = db.scalar(select(OrgDocument).where(OrgDocument.id == document_id))
    assert document is not None
    assert document.status.value == "pending"
    db.close()

    task_func = captured_task["func"]
    task_args = captured_task["args"]
    task_kwargs = captured_task["kwargs"]
    task_func(*task_args, **task_kwargs)

    db = SessionLocal()
    processed = db.scalar(select(OrgDocument).where(OrgDocument.id == document_id))
    chunks = db.scalars(
        select(OrgDocumentChunk)
        .where(OrgDocumentChunk.document_id == document_id)
        .order_by(OrgDocumentChunk.chunk_index.asc())
    ).all()
    assert processed is not None
    assert processed.status.value == "ready"
    assert processed.chunk_count == len(chunks)
    assert processed.token_count is not None and processed.token_count > 0
    assert chunks
    assert chunks[0].embedding is not None
    assert len(chunks[0].embedding) == 1536
    db.close()

    list_response = client.get("/manager/documents", params={"manager_id": seed_org["manager_id"]})
    assert list_response.status_code == 200
    assert any(item["id"] == document_id for item in list_response.json()["documents"])

    detail_response = client.get(
        f"/manager/documents/{document_id}",
        params={"manager_id": seed_org["manager_id"]},
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "ready"

    delete_response = client.delete(
        f"/manager/documents/{document_id}",
        params={"manager_id": seed_org["manager_id"]},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True, "document_id": document_id}

    db = SessionLocal()
    deleted_document = db.scalar(select(OrgDocument).where(OrgDocument.id == document_id))
    deleted_chunks = db.scalars(select(OrgDocumentChunk).where(OrgDocumentChunk.document_id == document_id)).all()
    db.close()
    assert deleted_document is None
    assert deleted_chunks == []
