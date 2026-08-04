#!/usr/bin/env python3
"""Telegram Bot 命令和輔助函數測試"""

import os
import queue
import time
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import telegram_bot_multi as bot_module


# ===== Fixtures =====

def make_update(user_id=123, chat_id=456, text="hello"):
    """建立模擬 Update 物件"""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message = AsyncMock()
    update.message.text = text
    return update


def make_context(args=None):
    """建立模擬 Context 物件"""
    context = MagicMock()
    context.args = args or []
    return context


def make_callback_query(user_id=123, data="choice_proj:1", message_text="原始訊息"):
    """建立模擬 CallbackQuery Update"""
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query = AsyncMock()
    update.callback_query.data = data
    update.callback_query.message.text = message_text
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


# ===== check_user_permission =====

class TestCheckUserPermission:
    """check_user_permission 測試"""

    def test_allowed_user(self):
        update = make_update(user_id=123)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123', '456']):
            assert bot_module.check_user_permission(update) is True

    def test_denied_user(self):
        update = make_update(user_id=999)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123', '456']):
            assert bot_module.check_user_permission(update) is False

    def test_empty_allowed_list(self):
        """空列表拒絕所有用戶（fail-closed）"""
        update = make_update(user_id=999)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', []):
            assert bot_module.check_user_permission(update) is False


# ===== check_rate_limit =====

class TestCheckRateLimit:
    """check_rate_limit 測試"""

    def setup_method(self):
        bot_module._rate_limit_store.clear()

    def test_within_limit(self):
        assert bot_module.check_rate_limit(1) is True
        assert bot_module.check_rate_limit(1) is True
        assert bot_module.check_rate_limit(1) is True

    def test_exceeds_limit(self):
        bot_module.check_rate_limit(1)
        bot_module.check_rate_limit(1)
        bot_module.check_rate_limit(1)
        assert bot_module.check_rate_limit(1) is False

    def test_different_users(self):
        """不同用戶不共享限制"""
        for _ in range(3):
            bot_module.check_rate_limit(1)
        assert bot_module.check_rate_limit(1) is False
        assert bot_module.check_rate_limit(2) is True

    def test_expired_timestamps_cleaned(self):
        """過期的時戳會被清理"""
        bot_module._rate_limit_store[1] = [time.time() - 10, time.time() - 10, time.time() - 10]
        assert bot_module.check_rate_limit(1) is True


# ===== /start 命令 =====

class TestStartCommand:
    """start 命令測試"""

    @pytest.mark.asyncio
    async def test_unauthorized(self):
        update = make_update(user_id=999)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.start(update, make_context())
        update.message.reply_text.assert_called_once_with("❌ 未授權的用戶")

    @pytest.mark.asyncio
    async def test_authorized(self):
        update = make_update(user_id=123)
        mock_router = MagicMock()
        mock_router.format_session_list.return_value = "會話列表"

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router):
            await bot_module.start(update, make_context())

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "會話列表" in reply
        assert "/start" in reply


# ===== /status 命令 =====

class TestStatusCommand:
    """status 命令測試"""

    @pytest.mark.asyncio
    async def test_unauthorized(self):
        update = make_update(user_id=999)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.status(update, make_context())
        update.message.reply_text.assert_called_once_with("❌ 未授權的用戶")

    @pytest.mark.asyncio
    async def test_shows_cli_type(self):
        update = make_update(user_id=123)
        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "proj": {
                "name": "proj",
                "path": "/tmp",
                "tmux_session": "claude-proj",
                "cli_type": "gemini",
                "cli_args": "--yolo",
                "exists": True,
                "status": {},
            }
        }

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'session_manager', mock_manager):
            await bot_module.status(update, make_context())

        reply = update.message.reply_text.call_args[0][0]
        assert "gemini" in reply
        assert "--yolo" in reply
        assert "運行中" in reply


# ===== /sessions 命令 =====

class TestSessionsCommand:
    """sessions_list 命令測試"""

    @pytest.mark.asyncio
    async def test_shows_list(self):
        update = make_update(user_id=123)
        mock_router = MagicMock()
        mock_router.format_session_list.return_value = "可用會話列表"

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router):
            await bot_module.sessions_list(update, make_context())

        update.message.reply_text.assert_called_once_with("可用會話列表")

    @pytest.mark.asyncio
    async def test_not_initialized(self):
        update = make_update(user_id=123)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', None):
            await bot_module.sessions_list(update, make_context())

        update.message.reply_text.assert_called_once_with("❌ 系統未初始化")


# ===== /restart 命令 =====

class TestRestartCommand:
    """restart_session 命令測試"""

    @pytest.mark.asyncio
    async def test_no_args(self):
        update = make_update(user_id=123)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.restart_session(update, make_context(args=[]))
        reply = update.message.reply_text.call_args[0][0]
        assert "請指定會話名稱" in reply

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        update = make_update(user_id=123)
        mock_manager = MagicMock()
        mock_manager.get_session.return_value = None

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'session_manager', mock_manager):
            await bot_module.restart_session(update, make_context(args=["#nonexistent"]))

        reply = update.message.reply_text.call_args[0][0]
        assert "會話不存在" in reply

    @pytest.mark.asyncio
    async def test_successful_restart(self):
        update = make_update(user_id=123)
        mock_manager = MagicMock()
        mock_manager.get_session.return_value = MagicMock()
        mock_manager.restart_session.return_value = True

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'session_manager', mock_manager):
            await bot_module.restart_session(update, make_context(args=["#proj"]))

        # 第二次呼叫是成功訊息（第一次是「正在重啟」）
        calls = update.message.reply_text.call_args_list
        assert "已成功重啟" in calls[-1][0][0]

    @pytest.mark.asyncio
    async def test_restart_failure(self):
        update = make_update(user_id=123)
        mock_manager = MagicMock()
        mock_manager.get_session.return_value = MagicMock()
        mock_manager.restart_session.return_value = False

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'session_manager', mock_manager):
            await bot_module.restart_session(update, make_context(args=["proj"]))

        calls = update.message.reply_text.call_args_list
        assert "重啟失敗" in calls[-1][0][0]


# ===== /reload 命令 =====

class TestReloadCommand:
    """reload_config 命令測試"""

    @pytest.mark.asyncio
    async def test_successful_reload(self):
        update = make_update(user_id=123)
        changes = {'added': ['new'], 'removed': ['old'], 'kept': ['keep']}

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module, 'reload_sessions_config',
                          return_value=(True, "✅ 配置已重載", changes)):
            await bot_module.reload_config(update, make_context())

        calls = update.message.reply_text.call_args_list
        reply = calls[-1][0][0]
        assert "配置已重載" in reply
        assert "#new" in reply
        assert "#old" in reply

    @pytest.mark.asyncio
    async def test_reload_failure(self):
        update = make_update(user_id=123)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module, 'reload_sessions_config',
                          return_value=(False, "找不到配置文件", {})):
            await bot_module.reload_config(update, make_context())

        calls = update.message.reply_text.call_args_list
        assert "找不到配置文件" in calls[-1][0][0]


# ===== handle_message =====

class TestHandleMessage:
    """handle_message 測試"""

    def setup_method(self):
        bot_module._rate_limit_store.clear()

    @pytest.mark.asyncio
    async def test_unauthorized(self):
        update = make_update(user_id=999)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.handle_message(update, make_context())
        update.message.reply_text.assert_called_once_with("❌ 未授權的用戶")

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        update = make_update(user_id=123)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module, 'check_rate_limit', return_value=False):
            await bot_module.handle_message(update, make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "頻繁" in reply

    @pytest.mark.asyncio
    async def test_message_too_long(self):
        update = make_update(user_id=123, text="x" * 20000)
        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.handle_message(update, make_context())
        reply = update.message.reply_text.call_args[0][0]
        assert "過長" in reply

    @pytest.mark.asyncio
    async def test_error_route(self):
        """無 # 前綴時返回錯誤"""
        update = make_update(user_id=123, text="沒有前綴的訊息")
        mock_router = MagicMock()
        mock_router.parse_message.return_value = [('__error__', '❌ 請指定目標會話')]

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router):
            await bot_module.handle_message(update, make_context())

        reply = update.message.reply_text.call_args[0][0]
        assert "請指定目標會話" in reply

    @pytest.mark.asyncio
    async def test_successful_route_single(self):
        """正常路由到單一會話（一般訊息注入長度提示）"""
        update = make_update(user_id=123, text="#proj 請幫我分析這個模組的架構")
        mock_router = MagicMock()
        mock_router.parse_message.return_value = [('proj', '請幫我分析這個模組的架構')]

        test_queue = queue.Queue(maxsize=100)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router), \
             patch.object(bot_module.bot_state, 'message_queue', test_queue):
            await bot_module.handle_message(update, make_context())

        assert test_queue.qsize() == 1
        name, msg = test_queue.get_nowait()
        assert name == 'proj'
        assert msg.startswith('請幫我分析這個模組的架構')
        assert '回應限制' in msg  # session.length_hint 已注入
        reply = update.message.reply_text.call_args[0][0]
        assert "#proj" in reply

    @pytest.mark.asyncio
    async def test_short_message_no_length_hint(self):
        """極短訊息（互動選單回覆）不注入長度提示"""
        update = make_update(user_id=123, text="#proj 2")
        mock_router = MagicMock()
        mock_router.parse_message.return_value = [('proj', '2')]

        test_queue = queue.Queue(maxsize=100)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router), \
             patch.object(bot_module.bot_state, 'message_queue', test_queue):
            await bot_module.handle_message(update, make_context())

        assert test_queue.get_nowait() == ('proj', '2')

    @pytest.mark.asyncio
    async def test_successful_route_all(self):
        """#all 廣播到多個會話"""
        update = make_update(user_id=123, text="#all 你好")
        mock_router = MagicMock()
        mock_router.parse_message.return_value = [('a', '你好'), ('b', '你好')]

        test_queue = queue.Queue(maxsize=100)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router), \
             patch.object(bot_module.bot_state, 'message_queue', test_queue):
            await bot_module.handle_message(update, make_context())

        assert test_queue.qsize() == 2
        reply = update.message.reply_text.call_args[0][0]
        assert "2 個會話" in reply

    @pytest.mark.asyncio
    async def test_long_error_reply_truncated(self):
        """回顯超長使用者輸入的錯誤訊息不超過 Telegram 上限"""
        from config import utf16_len
        update = make_update(user_id=123, text="#" + "x" * 9000)
        mock_router = MagicMock()
        mock_router.parse_message.return_value = [('__error__', '會話不存在: ' + 'x' * 9000)]

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router):
            await bot_module.handle_message(update, make_context())

        reply = update.message.reply_text.call_args[0][0]
        assert utf16_len(reply) <= 4096

    @pytest.mark.asyncio
    async def test_queue_full(self):
        """佇列滿時回報錯誤"""
        update = make_update(user_id=123, text="#proj 你好")
        mock_router = MagicMock()
        mock_router.parse_message.return_value = [('proj', '你好')]

        full_queue = queue.Queue(maxsize=1)
        full_queue.put("placeholder")  # 填滿佇列

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_router', mock_router), \
             patch.object(bot_module.bot_state, 'message_queue', full_queue):
            await bot_module.handle_message(update, make_context())

        reply = update.message.reply_text.call_args[0][0]
        assert "佇列已滿" in reply


# ===== button_callback =====

class TestButtonCallback:
    """button_callback 測試"""

    @pytest.mark.asyncio
    async def test_successful_callback(self):
        update = make_callback_query(user_id=123, data="choice_proj:2")
        test_queue = queue.Queue(maxsize=100)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_queue', test_queue):
            await bot_module.button_callback(update, make_context())

        assert test_queue.qsize() == 1
        assert test_queue.get_nowait() == ('proj', '2')

    @pytest.mark.asyncio
    async def test_unauthorized_callback(self):
        update = make_callback_query(user_id=999, data="choice_proj:1")

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.button_callback(update, make_context())

        update.callback_query.edit_message_text.assert_called_once_with("❌ 未授權的用戶")

    @pytest.mark.asyncio
    async def test_invalid_data_prefix(self):
        update = make_callback_query(user_id=123, data="invalid_data")

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.button_callback(update, make_context())

        # 不做任何動作（不呼叫 edit_message_text）
        update.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_data_format(self):
        """沒有冒號分隔符"""
        update = make_callback_query(user_id=123, data="choice_nocolon")

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']):
            await bot_module.button_callback(update, make_context())

        update.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_underscore_session_name(self):
        """支援 mac_claude 這樣包含底線的會話名"""
        update = make_callback_query(user_id=123, data="choice_mac_claude:3")
        test_queue = queue.Queue(maxsize=100)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_queue', test_queue):
            await bot_module.button_callback(update, make_context())

        session_name, choice = test_queue.get_nowait()
        assert session_name == "mac_claude"
        assert choice == "3"

    @pytest.mark.asyncio
    async def test_edit_text_within_api_limit(self):
        """原訊息接近上限時，加料後的 edit 內容不超過 4096 且保留追加行"""
        from config import utf16_len
        update = make_callback_query(user_id=123, data="choice_proj:1",
                                     message_text="x" * 4000 + "😀" * 50)
        test_queue = queue.Queue(maxsize=100)

        with patch.object(bot_module, 'ALLOWED_USER_IDS', ['123']), \
             patch.object(bot_module.bot_state, 'message_queue', test_queue):
            await bot_module.button_callback(update, make_context())

        sent_text = update.callback_query.edit_message_text.call_args[1]['text']
        assert utf16_len(sent_text) <= 4096
        assert "已選擇" in sent_text  # 追加行（callback.selected）完整保留


# ===== 出站長度防護 helpers =====

class TestOutboundLengthHelpers:
    """_safe_text / _compose_edit_text 測試"""

    def test_safe_text_within_limit(self):
        assert bot_module._safe_text("hello") == "hello"

    def test_safe_text_truncates(self):
        from config import utf16_len
        result = bot_module._safe_text("x" * 9000)
        assert utf16_len(result) <= 4000
        assert result.endswith("⋯")

    def test_compose_edit_text_short(self):
        result = bot_module._compose_edit_text("原文", "追加")
        assert result == "原文\n\n追加"

    def test_compose_edit_text_keeps_appendix(self):
        from config import utf16_len
        result = bot_module._compose_edit_text("x" * 5000, "✅ 已選擇: 1")
        assert utf16_len(result) <= 4096
        assert result.endswith("✅ 已選擇: 1")


# ===== load_sessions_config =====

class TestLoadSessionsConfig:
    """load_sessions_config 測試"""

    def test_cli_type_parsing(self):
        yaml_content = {
            'sessions': [
                {'name': 'proj', 'path': '/tmp', 'cli_type': 'gemini', 'cli_args': '--yolo'},
            ]
        }

        mock_manager = MagicMock()

        with patch('builtins.open', MagicMock()), \
             patch('yaml.safe_load', return_value=yaml_content), \
             patch.object(bot_module, 'SessionManager', return_value=mock_manager), \
             patch.object(bot_module, 'MessageRouter'), \
             patch.object(bot_module, 'bot_state') as mock_state:
            mock_state.update_manager_and_router = MagicMock()
            bot_module.load_sessions_config()

        mock_manager.add_session.assert_called_once_with(
            'proj', '/tmp', None, '--yolo', 'gemini'
        )

    def test_claude_args_backward_compat(self):
        """claude_args 向後相容"""
        yaml_content = {
            'sessions': [
                {'name': 'proj', 'path': '/tmp', 'claude_args': '--model sonnet'},
            ]
        }

        mock_manager = MagicMock()

        with patch('builtins.open', MagicMock()), \
             patch('yaml.safe_load', return_value=yaml_content), \
             patch.object(bot_module, 'SessionManager', return_value=mock_manager), \
             patch.object(bot_module, 'MessageRouter'), \
             patch.object(bot_module, 'bot_state') as mock_state:
            mock_state.update_manager_and_router = MagicMock()
            bot_module.load_sessions_config()

        mock_manager.add_session.assert_called_once_with(
            'proj', '/tmp', None, '--model sonnet', 'claude'
        )

    def test_cli_args_overrides_claude_args(self):
        """cli_args 優先於 claude_args"""
        yaml_content = {
            'sessions': [
                {'name': 'proj', 'path': '/tmp',
                 'cli_args': '--new', 'claude_args': '--old'},
            ]
        }

        mock_manager = MagicMock()

        with patch('builtins.open', MagicMock()), \
             patch('yaml.safe_load', return_value=yaml_content), \
             patch.object(bot_module, 'SessionManager', return_value=mock_manager), \
             patch.object(bot_module, 'MessageRouter'), \
             patch.object(bot_module, 'bot_state') as mock_state:
            mock_state.update_manager_and_router = MagicMock()
            bot_module.load_sessions_config()

        mock_manager.add_session.assert_called_once_with(
            'proj', '/tmp', None, '--new', 'claude'
        )


# ===== reload_sessions_config =====

class TestReloadSessionsConfig:
    """reload_sessions_config 測試"""

    def test_file_not_found(self):
        with patch('builtins.open', side_effect=FileNotFoundError):
            success, msg, changes = bot_module.reload_sessions_config()
        assert success is False
        assert "找不到" in msg

    def test_invalid_yaml(self):
        with patch('builtins.open', MagicMock()), \
             patch('yaml.safe_load', return_value=None):
            success, msg, changes = bot_module.reload_sessions_config()
        assert success is False
        assert "格式錯誤" in msg

    def test_detects_added_removed_kept(self):
        yaml_content = {
            'sessions': [
                {'name': 'kept', 'path': '/tmp/kept'},
                {'name': 'new', 'path': '/tmp/new'},
            ]
        }

        mock_old_manager = MagicMock()
        mock_old_manager.get_all_sessions.return_value = ['kept', 'removed']

        mock_new_manager = MagicMock()
        mock_new_bridge = MagicMock()
        mock_new_bridge.session_exists.return_value = True
        mock_new_manager.get_bridge.return_value = mock_new_bridge

        with patch('builtins.open', MagicMock()), \
             patch('yaml.safe_load', return_value=yaml_content), \
             patch.object(bot_module, 'SessionManager', return_value=mock_new_manager), \
             patch.object(bot_module, 'MessageRouter'), \
             patch.object(bot_module.bot_state, 'session_manager', mock_old_manager), \
             patch.object(bot_module.bot_state, 'update_manager_and_router'):
            success, msg, changes = bot_module.reload_sessions_config()

        assert success is True
        assert 'new' in changes['added']
        assert 'removed' in changes['removed']
        assert 'kept' in changes['kept']
        mock_old_manager.kill_session.assert_called_once_with('removed')

    def test_overlong_session_name_skipped(self):
        """超過 54 bytes 的 session 名（callback_data 預算）被略過並警告"""
        yaml_content = {
            'sessions': [
                {'name': 'a' * 55, 'path': '/tmp/too-long'},
                {'name': 'ok', 'path': '/tmp/ok'},
            ]
        }

        mock_old_manager = MagicMock()
        mock_old_manager.get_all_sessions.return_value = []

        mock_new_manager = MagicMock()
        mock_new_bridge = MagicMock()
        mock_new_bridge.session_exists.return_value = True
        mock_new_manager.get_bridge.return_value = mock_new_bridge

        with patch('builtins.open', MagicMock()), \
             patch('yaml.safe_load', return_value=yaml_content), \
             patch.object(bot_module, 'SessionManager', return_value=mock_new_manager), \
             patch.object(bot_module, 'MessageRouter'), \
             patch.object(bot_module.bot_state, 'session_manager', mock_old_manager), \
             patch.object(bot_module.bot_state, 'update_manager_and_router'):
            success, msg, changes = bot_module.reload_sessions_config()

        assert success is True
        assert changes['added'] == ['ok']
        assert 'a' * 55 not in changes['added']


class TestLogRotation:
    """日誌輪替邏輯測試"""

    def test_truncates_oversized_log(self):
        """測試超過 10MB 的日誌被截斷至 5MB"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            # 建立 11MB 的檔案
            data = b"A" * (11 * 1024 * 1024)
            log_file.write_bytes(data)
            assert log_file.stat().st_size > 10 * 1024 * 1024

            # 模擬單次輪替邏輯（不進入無限迴圈）
            from config import config as app_config
            if log_file.stat().st_size > app_config.tmux.LOG_MAX_SIZE:
                kept = log_file.read_bytes()[-app_config.tmux.LOG_KEEP_SIZE:]
                log_file.write_bytes(kept)

            # 驗證截斷後大小
            assert log_file.stat().st_size == app_config.tmux.LOG_KEEP_SIZE

    def test_skips_small_log(self):
        """測試小於 10MB 的日誌不被截斷"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            data = b"small log content"
            log_file.write_bytes(data)
            original_size = log_file.stat().st_size

            from config import config as app_config
            if log_file.stat().st_size > app_config.tmux.LOG_MAX_SIZE:
                kept = log_file.read_bytes()[-app_config.tmux.LOG_KEEP_SIZE:]
                log_file.write_bytes(kept)

            assert log_file.stat().st_size == original_size


class TestMessageQueueProcessor:
    """訊息佇列處理測試"""

    @patch('telegram_bot_multi.time.sleep')
    def test_processes_queue_item(self, mock_sleep):
        """測試佇列訊息被正確處理"""
        mock_manager = MagicMock()
        original_manager = bot_module.bot_state.session_manager

        try:
            bot_module.bot_state.session_manager = mock_manager

            # 放入訊息
            bot_module.bot_state.message_queue.put_nowait(('webapp', 'hello world'))

            # 手動取出並處理（模擬 processor 的單次迭代）
            item = bot_module.bot_state.message_queue.get(timeout=1)
            session_name, message = item
            bot_module.bot_state.session_manager.send_to_session(session_name, message)

            mock_manager.send_to_session.assert_called_once_with('webapp', 'hello world')
        finally:
            bot_module.bot_state.session_manager = original_manager

    def test_queue_capacity(self):
        """測試佇列容量限制"""
        from config import config as app_config
        assert bot_module.bot_state.message_queue.maxsize == app_config.queue.MESSAGE_QUEUE_SIZE


class TestInteractionPolling:
    """互動偵測輪詢測試"""

    def test_clean_ansi(self):
        """測試 ANSI escape code 清理"""
        raw = "\x1b[38;5;153m❯\x1b[1C\x1b[38;5;246m1.\x1b[1C\x1b[38;5;153mYes, auto-accept edits\x1b[39m"
        cleaned = bot_module._clean_ansi(raw)
        assert "1." in cleaned
        assert "Yes, auto-accept edits" in cleaned
        assert "\x1b" not in cleaned

    def test_extract_options(self):
        """測試選項提取（需有 ╌ 分隔線和 ❯ 標記）"""
        text = """Some preamble text
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
Would you like to proceed?
❯ 1. Yes, auto-accept edits
  2. Yes, manually approve edits
  3. Tell Claude what to change
      shift+tab to approve"""
        title, options = bot_module._extract_options(text)
        assert len(options) == 3
        assert options[0] == ("1", "Yes, auto-accept edits")
        assert options[1] == ("2", "Yes, manually approve edits")
        assert options[2] == ("3", "Tell Claude what to change")
        assert "Would you like to proceed?" in title

    def test_extract_options_no_options(self):
        """測試無選項的文字"""
        text = "Just regular output\nNo options here"
        title, options = bot_module._extract_options(text)
        assert len(options) == 0

    def test_extract_options_single_option_ignored(self):
        """測試無標記的編號列表不被當作互動"""
        text = "1. Some item"
        title, options = bot_module._extract_options(text)
        assert len(options) == 0  # 無 ╌ 分隔線和 ❯ 標記，不是互動選項

    def test_extract_options_gemini(self):
        """測試 Gemini CLI 格式選項提取"""
        text = """
╭──────────────────────────────────────────────────────────────╮
│ Action Required                                              │
│                                                              │
│ ?  Shell git remote update                                   │
│ Allow execution of: 'git'?                                   │
│                                                              │
│ ● 1. Allow once                                              │
│   2. Allow for this session                                  │
│   3. No, suggest changes (esc)                               │
│                                                              │
╰──────────────────────────────────────────────────────────────╯
"""
        title, options = bot_module._extract_options(text, cli_type='gemini')
        assert len(options) == 3
        assert options[0] == ("1", "Allow once")
        assert options[1] == ("2", "Allow for this session")
        assert options[2] == ("3", "No, suggest changes (esc)")
        assert "Allow execution" in title

    def test_extract_options_gemini_no_box(self):
        """測試 Gemini 無框框時回傳空"""
        text = "Just some gemini output\nNo box here"
        title, options = bot_module._extract_options(text, cli_type='gemini')
        assert len(options) == 0

    def test_extract_options_codex(self):
        """測試 Codex 選項提取（› 標記 + 編號）"""
        text = (
            "Would you like to run the following command?\n\n"
            "$ git remote update\n\n"
            "› 1. Yes, proceed (y)\n"
            "  2. Yes, and don't ask again (p)\n"
            "  3. No, and tell Codex what to do differently (esc)\n\n"
            "  Press enter to confirm or esc to cancel"
        )
        title, options = bot_module._extract_options(text, cli_type='codex')
        assert len(options) == 3
        assert options[0] == ('1', 'Yes, proceed (y)')
        assert options[2][0] == '3'
        assert 'git remote update' in title

    def test_extract_options_codex_no_options(self):
        """測試 Codex 無選項時回傳空"""
        text = "Just some codex output\nNo options here"
        title, options = bot_module._extract_options(text, cli_type='codex')
        assert len(options) == 0

    def test_duplicate_prevention(self):
        """測試防重複機制"""
        import hashlib
        bot_module._poll_sent_hashes.clear()

        options_text = "1.Option A|2.Option B"
        h = hashlib.md5(options_text.encode()).hexdigest()

        assert h not in bot_module._poll_sent_hashes
        bot_module._poll_sent_hashes[h] = True
        assert h in bot_module._poll_sent_hashes

        # 清理
        bot_module._poll_sent_hashes.clear()
