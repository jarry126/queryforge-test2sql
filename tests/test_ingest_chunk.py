"""文档切块单测（图②逻辑）。"""

from app.core.rag.ingest import chunk_markdown


def test_split_by_heading():
    text = "# 标题A\n内容A\n\n## 标题B\n内容B"
    chunks = chunk_markdown(text)
    assert len(chunks) >= 2
    assert all(c.chunk_type in ("text", "table") for c in chunks)


def test_long_text_is_split():
    long_body = "段落。" * 800  # > 1000 字符
    text = f"# 长标题\n{long_body}"
    chunks = chunk_markdown(text, max_chars=1000)
    assert all(len(c.content) <= 1000 for c in chunks)
    assert len(chunks) >= 2


def test_table_detected():
    text = "# 表\n| a | b |\n| - | - |\n| 1 | 2 |"
    chunks = chunk_markdown(text)
    assert any(c.chunk_type == "table" for c in chunks)
