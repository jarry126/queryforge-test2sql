"""语言识别单测（按字符脚本判断，修复中文被误判为 ko/ja）。"""

import pytest

from app.core.langgraph.nodes.detect_language import detect_lang


@pytest.mark.parametrize(
    "text,expected",
    [
        ("学生学哪门课程最多", "zh"),       # 之前被 langdetect 误判成 ko
        ("我们有多少歌手？", "zh"),
        ("How many singers are there?", "en"),
        ("학생", "ko"),                      # 谚文 → 韩语
        ("こんにちは", "ja"),                # 假名 → 日语
    ],
)
def test_detect_lang(text, expected):
    assert detect_lang(text) == expected
