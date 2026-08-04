#!/usr/bin/env python3
"""
配置模組測試
"""

import pytest
from config import (
    config, patterns, AppConfig, TelegramConfig,
    utf16_len, truncate_utf16, truncate_utf16_tail, truncate_utf16_smart,
)


class TestConfig:
    """配置類測試"""

    def test_app_config_instance(self):
        """測試全域配置實例"""
        assert config is not None
        assert config.tmux is not None
        assert config.queue is not None
        assert config.security is not None


class TestPatterns:
    """正則表達式模式測試"""

    def test_ansi_escape_pattern(self):
        """測試 ANSI 轉義碼匹配"""
        test_text = "\x1b[32mGreen\x1b[0m"
        cleaned = patterns.ANSI_ESCAPE.sub('', test_text)
        assert cleaned == "Green"

    def test_control_chars_pattern(self):
        """測試控制字元匹配"""
        test_text = "Hello\x00World\x0BTest"
        cleaned = patterns.CONTROL_CHARS.sub('', test_text)
        assert cleaned == "HelloWorldTest"

    def test_multiple_newlines_pattern(self):
        """測試多餘空行匹配"""
        test_text = "Line1\n\n\n\nLine2"
        cleaned = patterns.MULTIPLE_NEWLINES.sub('\n\n', test_text)
        assert cleaned == "Line1\n\nLine2"

    def test_confirmation_option_pattern(self):
        """測試確認選項匹配"""
        # 測試標準選項
        match = patterns.CONFIRMATION_OPTION.match("  1. Yes")
        assert match is not None
        assert match.group(1) == "1"
        assert match.group(2) == "Yes"

        # 測試帶符號選項
        match = patterns.CONFIRMATION_OPTION.match("❯ 2. No")
        assert match is not None
        assert match.group(1) == "2"

    def test_session_name_pattern(self):
        """測試會話名稱模式"""
        assert patterns.SESSION_NAME.match("webapp") is not None
        assert patterns.SESSION_NAME.match("mac_claude") is not None
        assert patterns.SESSION_NAME.match("test-123") is not None
        assert patterns.SESSION_NAME.match("invalid name") is None

    def test_message_route_pattern(self):
        """測試訊息路由模式"""
        match = patterns.MESSAGE_ROUTE.match("#webapp hello world")
        assert match is not None
        assert match.group(1) == "webapp"
        assert match.group(2) == "hello world"

    def test_box_chars_pattern(self):
        """測試框線字元模式"""
        assert patterns.BOX_CHARS.match("│") is not None
        assert patterns.BOX_CHARS.match("╭─────╮") is not None
        assert patterns.BOX_CHARS.match("Hello") is None

    def test_session_name_length_limit(self):
        """session 名稱長度上限（UTF-8 bytes，callback_data 64 bytes 預算）"""
        limit = TelegramConfig.MAX_SESSION_NAME_BYTES
        assert patterns.is_safe_session_name("a" * limit) is True
        assert patterns.is_safe_session_name("a" * (limit + 1)) is False
        # 中文每字 3 bytes：18 字 = 54 bytes 通過、19 字拒絕
        assert patterns.is_safe_session_name("中" * 18) is True
        assert patterns.is_safe_session_name("中" * 19) is False
        # 既有語意不變
        assert patterns.is_safe_session_name("webapp") is True
        assert patterns.is_safe_session_name("../etc") is False

    def test_session_name_budget_guard(self):
        """常數守衛：名稱預算 + 最長前綴 + 序號必須裝進 callback_data 64 bytes"""
        assert TelegramConfig.MAX_SESSION_NAME_BYTES + len('select_') + len(':50') <= 64


class TestUtf16Helpers:
    """UTF-16 長度計算與截斷測試"""

    def test_utf16_len(self):
        assert utf16_len("hello") == 5
        assert utf16_len("😀") == 2
        assert utf16_len("中文") == 2
        assert utf16_len("a😀中") == 4

    def test_truncate_within_limit_returns_as_is(self):
        """上限內原樣返回，不加 suffix"""
        assert truncate_utf16("hello", 10, "...") == "hello"
        assert truncate_utf16("😀😀", 4, "...") == "😀😀"

    def test_truncate_emoji_not_split(self):
        """emoji（2 units）不被切半：奇數預算下少收一個 emoji"""
        result = truncate_utf16("😀" * 10, 5)
        assert result == "😀😀"
        result.encode('utf-16')  # 不拋錯即無孤立 surrogate

    def test_truncate_suffix_counted_in_budget(self):
        result = truncate_utf16("x" * 100, 50, "...")
        assert utf16_len(result) <= 50
        assert result.endswith("...")

    def test_truncate_tail_keeps_end(self):
        result = truncate_utf16_tail("abcdef", 3)
        assert result == "def"
        result = truncate_utf16_tail("ab" + "😀" * 5, 5)
        assert result == "😀😀"

    def test_smart_truncate_paragraph_boundary(self):
        """截斷點回退到段落邊界"""
        text = "第一段" * 100 + "\n\n" + "第二段" * 100 + "\n\n" + "第三段" * 2000
        result = truncate_utf16_smart(text, 500, "[截斷]")
        assert utf16_len(result) <= 500
        # 截斷點回退到段落邊界：完整保留第一段，不殘留半截的第二段（純硬切會殘留）
        assert result == "第一段" * 100 + "[截斷]"
        assert "第二段" not in result

    def test_smart_truncate_sentence_boundary(self):
        """無換行時回退到句末標點"""
        text = "這是一句話。" * 200
        result = truncate_utf16_smart(text, 300, "[截斷]")
        assert utf16_len(result) <= 300
        body = result[:-len("[截斷]")]
        assert body.endswith("。")

    def test_smart_truncate_no_boundary_hard_cut(self):
        """無任何邊界的長 blob：硬切，不損失超過回看窗"""
        text = "x" * 10000
        result = truncate_utf16_smart(text, 4000, "[截斷]")
        assert utf16_len(result) <= 4000
        assert utf16_len(result) >= 4000 - TelegramConfig.TRUNCATE_BOUNDARY_WINDOW - len("[截斷]") - 4

    def test_smart_truncate_closes_code_fence(self):
        """截斷造成 ``` 不成對時補閉合"""
        text = "說明文字\n```python\n" + "code_line()\n" * 1000
        result = truncate_utf16_smart(text, 500, "[截斷]")
        assert utf16_len(result) <= 500
        assert result.count("```") % 2 == 0

    def test_smart_truncate_within_limit_returns_as_is(self):
        text = "短訊息\n```\ncode\n```"
        assert truncate_utf16_smart(text, 4000, "[截斷]") == text
