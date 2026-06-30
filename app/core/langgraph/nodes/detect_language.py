"""节点：语言识别（对应图①「判断用户的语言」）。

优先按 Unicode 字符脚本判断（对中日韩短文本可靠）：
- 含谚文 → 韩语 ko；含假名 → 日语 ja；含汉字（且无谚文/假名）→ 中文 zh。
langdetect 仅用于纯拉丁等场景的兜底——它对短的 CJK 文本经常把中文误判成 ko/ja。
"""

from __future__ import annotations

import re

from app.core.langgraph.state import GraphState
from app.core.logging import logger

# 用 \uXXXX 码位区间，避免出现生僻边界字、一眼可读
_HANGUL = re.compile("[가-힯]")   # 韩文谚文音节 (Hangul Syllables)
_KANA = re.compile("[぀-ヿ]")     # 日文平假名 + 片假名 (Hiragana/Katakana)
_HAN = re.compile("[一-鿿]")      # CJK 统一表意文字（汉字）


def detect_lang(text: str) -> str:
    if _HANGUL.search(text):
        return "ko"
    if _KANA.search(text):
        return "ja"
    if _HAN.search(text):
        return "zh"
    # 纯西文等：用 langdetect 兜底
    try:
        from langdetect import detect

        code = detect(text)
        return "zh" if code.startswith("zh") else code
    except Exception:  # noqa: BLE001
        return "en"


async def detect_language(state: GraphState) -> dict:
    lang = detect_lang(state["question"])
    logger.info("query_start", question=state["question"], db_id=state.get("db_id"), language=lang)
    return {"language": lang}
