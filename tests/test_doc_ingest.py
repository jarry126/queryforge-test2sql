"""文档分页/summary 纯逻辑单测（图②）。"""

from app.core.rag.ingest import chunk_markdown, paginate


def test_paginate_groups_indices():
    chunks = chunk_markdown("# A\n" + "\n\n".join(f"## H{i}\n内容{i}" for i in range(12)))
    pages = paginate(len(chunks), size=5)
    # 每页最多 5 个，且覆盖全部下标且不重叠
    flat = [i for p in pages for i in p]
    assert flat == list(range(len(chunks)))
    assert all(len(p) <= 5 for p in pages)


def test_paginate_single_page():
    chunks = chunk_markdown("# 标题\n少量内容")
    pages = paginate(len(chunks), size=5)
    assert len(pages) == 1
