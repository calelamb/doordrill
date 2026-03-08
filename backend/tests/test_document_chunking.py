import re

from app.services.document_processing_service import DocumentProcessingService


def test_chunk_text_respects_sentence_boundaries_and_overlap():
    service = DocumentProcessingService()
    sentences = [
        f"Sentence {index} explains the sales playbook clearly for every rep on the team."
        for index in range(1, 16)
    ]
    text = " ".join(sentences)

    chunks = service.chunk_text(text, chunk_size=60, overlap=20)

    assert len(chunks) >= 3
    chunk_token_counts = [service.count_tokens(chunk) for chunk in chunks]
    assert all(50 <= token_count <= 600 for token_count in chunk_token_counts)

    original_sentences = set(sentences)
    for chunk in chunks:
        extracted = [part.strip() for part in re.split(r"(?<=[.!?])\s+", chunk) if part.strip()]
        assert extracted
        assert all(sentence in original_sentences for sentence in extracted)
        assert chunk.endswith(".")

    first_chunk_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", chunks[0]) if part.strip()]
    second_chunk_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", chunks[1]) if part.strip()]
    assert set(first_chunk_sentences[-2:]) & set(second_chunk_sentences)
