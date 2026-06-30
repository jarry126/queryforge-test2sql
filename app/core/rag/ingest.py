"""业务文档上传与切块（对应手绘图②）.

本轮提供可用骨架，实现按标题切分 + 超长兜底切割 + summary 汇总：
- text 类型：按 Markdown 标题切分，标题下内容为一个 chunk；超过 max_chars 先按段落（语义）切，
  仍超长再按字符切。
- table 类型：与 text 同构，type 标记为 table，metadata 存所属标题。
- summary 类型：按页/小节汇总，metadata 存所覆盖的 chunk_id 集合。
- image：当前不处理（与手绘图一致），预留入口。

Phase 2 再接入 PDF/真实分页解析与并发检索时的 summary 特殊处理。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_CHARS = 1000


@dataclass
class Chunk:
    chunk_type: str  # table | text | image | summary
    content: str
    page: int | None = None
    metadata: dict = field(default_factory=dict)


def _split_long(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """超长切割：先按段落（空行）语义切，仍超长再按字符硬切。"""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n\s*\n", text):
        if len(buf) + len(para) <= max_chars:
            buf += ("\n\n" if buf else "") + para
        else:
            if buf:
                parts.append(buf)
            if len(para) <= max_chars:
                buf = para
            else:  # 单段仍超长 -> 字符切
                for i in range(0, len(para), max_chars):
                    parts.append(para[i : i + max_chars])
                buf = ""
    if buf:
        parts.append(buf)
    return parts


def chunk_markdown(text: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """按 Markdown 标题切分为 text/table chunk（图②的 text 分支）。"""
    chunks: list[Chunk] = []
    current_title = ""
    blocks = re.split(r"(?m)^(#{1,6}\s.*)$", text)
    # re.split 会把标题与正文交替分出
    i = 0
    segments: list[tuple[str, str]] = []
    if blocks and not blocks[0].startswith("#"):
        segments.append(("", blocks[0]))
        blocks = blocks[1:]
    for j in range(0, len(blocks) - 1, 2):
        segments.append((blocks[j].strip(), blocks[j + 1]))
    for title, body in segments:
        current_title = title or current_title
        body = body.strip()
        if not body:
            continue
        is_table = "|" in body and re.search(r"\|.*\|", body) is not None
        ctype = "table" if is_table else "text"
        for piece in _split_long(body, max_chars):
            chunks.append(
                Chunk(chunk_type=ctype, content=piece, metadata={"title": current_title})
            )
    return chunks


def paginate(n: int, size: int) -> list[list[int]]:
    """把 n 个 chunk 的下标按每页 size 个分组（无物理分页时的分页策略，图②「按页数总结」）。"""
    return [list(range(i, min(i + size, n))) for i in range(0, n, size)]


def build_summary(chunks: list[Chunk], page: int | None = None) -> Chunk:
    """按一组 chunk 生成 summary 类型，metadata 存所覆盖的内容标题集合（图②）。

    注：真实 summary 文本由 LLM 生成；此处先拼接标题占位，Phase 2 接 LLM。
    chunk_id 集合在写库后回填（见 ingest 落库逻辑）。
    """
    titles = [c.metadata.get("title", "") for c in chunks]
    content = "本页要点：" + "；".join(t for t in titles if t)
    return Chunk(chunk_type="summary", content=content, page=page, metadata={"covered_titles": titles})
