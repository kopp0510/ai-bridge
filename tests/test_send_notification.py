#!/usr/bin/env python3
"""
Telegram 通知發送模組測試
"""

import pytest
from unittest.mock import patch, MagicMock
from send_telegram_notification import send_telegram_message, send_to_chat


class TestSendTelegramNotification:
    """通知發送測試"""

    @patch('send_telegram_notification.load_dotenv')
    @patch('send_telegram_notification.os.getenv')
    def test_missing_token(self, mock_getenv, mock_load_dotenv):
        """測試缺少 Token"""
        mock_getenv.return_value = None
        result = send_telegram_message("test", "message")
        assert result is False

    @patch('send_telegram_notification.load_dotenv')
    @patch('send_telegram_notification.os.getenv')
    def test_missing_user_ids(self, mock_getenv, mock_load_dotenv):
        """測試缺少用戶 ID"""
        def getenv_side_effect(key, default=''):
            if key == 'TELEGRAM_BOT_TOKEN':
                return 'test_token'
            return default

        mock_getenv.side_effect = getenv_side_effect
        result = send_telegram_message("test", "message")
        assert result is False

    @patch('send_telegram_notification.requests.post')
    def test_send_to_chat_success(self, mock_post):
        """測試成功發送"""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_post.return_value = mock_response

        result = send_to_chat("token", "123456", "Hello")
        assert result is True
        mock_post.assert_called_once()

    @patch('send_telegram_notification.requests.post')
    def test_send_to_chat_retry_on_failure(self, mock_post):
        """測試失敗重試（MAX_RETRIES=2，重試預算須低於 hook timeout）"""
        # 第一次失敗，第二次成功
        mock_fail = MagicMock()
        mock_fail.ok = False
        mock_fail.json.return_value = {'error_code': 500, 'description': 'Server Error'}
        mock_fail.status_code = 500
        mock_fail.text = 'Server Error'

        mock_success = MagicMock()
        mock_success.ok = True

        mock_post.side_effect = [mock_fail, mock_success]

        result = send_to_chat("token", "123456", "Hello")
        assert result is True
        assert mock_post.call_count == 2

    @patch('send_telegram_notification.requests.post')
    def test_send_to_chat_non_retryable_error(self, mock_post):
        """測試不可重試的錯誤"""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.json.return_value = {'error_code': 401, 'description': 'Unauthorized'}
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'
        mock_post.return_value = mock_response

        result = send_to_chat("token", "123456", "Hello")
        assert result is False
        assert mock_post.call_count == 1  # 不重試

    def test_send_to_chat_invalid_chat_id(self):
        """測試無效的 chat_id"""
        result = send_to_chat("token", "invalid", "Hello")
        assert result is False

    @patch('send_telegram_notification.send_to_chat')
    @patch('send_telegram_notification.load_dotenv')
    @patch('send_telegram_notification.os.getenv')
    def test_message_truncation(self, mock_getenv, mock_load_dotenv, mock_send):
        """測試超過 4000 字元的訊息被截斷"""
        def getenv_side_effect(key, default=''):
            if key == 'TELEGRAM_BOT_TOKEN':
                return 'test_token'
            if key == 'ALLOWED_USER_IDS':
                return '123'
            return default

        mock_getenv.side_effect = getenv_side_effect
        mock_send.return_value = True

        long_message = "x" * 5000
        send_telegram_message("test", long_message)

        # 驗證 send_to_chat 收到截斷後的訊息
        actual_message = mock_send.call_args[0][2]
        assert len(actual_message) < 5000
        assert actual_message.startswith("x" * 4000)
        assert "訊息已截斷" in actual_message

    @patch('send_telegram_notification.time.sleep')
    @patch('send_telegram_notification.requests.post')
    def test_markdown_fallback(self, mock_post, mock_sleep):
        """測試 Markdown 解析失敗自動降級為純文字"""
        # 第一次：Markdown 解析失敗
        mock_fail = MagicMock()
        mock_fail.ok = False
        mock_fail.json.return_value = {
            'error_code': 400,
            'description': "Bad Request: can't parse entities"
        }
        mock_fail.status_code = 400
        mock_fail.text = "can't parse entities"

        # 第二次（純文字重發）：成功
        mock_success = MagicMock()
        mock_success.ok = True

        mock_post.side_effect = [mock_fail, mock_success]

        result = send_to_chat("token", "123", "**bad markdown")
        assert result is True
        assert mock_post.call_count == 2

        # 驗證第二次呼叫沒有 parse_mode
        second_call_payload = mock_post.call_args_list[1][1]['json']
        assert 'parse_mode' not in second_call_payload

    @patch('send_telegram_notification.time.sleep')
    @patch('send_telegram_notification.requests.post')
    def test_markdown_fallback_error_redacts_token(self, mock_post, mock_sleep, caplog):
        """回歸：fallback 例外訊息含 API URL 時，日誌不得出現明文 token"""
        token = '12345:AAbbCCdd-test'

        # 第一次：Markdown 解析失敗，觸發純文字 fallback
        mock_fail = MagicMock()
        mock_fail.ok = False
        mock_fail.json.return_value = {
            'error_code': 400,
            'description': "Bad Request: can't parse entities"
        }
        mock_fail.status_code = 400
        mock_fail.text = "can't parse entities"

        # 第二次（fallback）：連線例外，訊息內嵌含 token 的 URL
        mock_post.side_effect = [
            mock_fail,
            Exception(f"Max retries exceeded with url: /bot{token}/sendMessage"),
        ]

        with caplog.at_level('ERROR', logger='send_telegram_notification'):
            result = send_to_chat(token, "123", "**bad markdown")

        assert result is False
        assert token not in caplog.text
        assert 'bot***' in caplog.text

    @patch('send_telegram_notification.time.sleep')
    @patch('send_telegram_notification.requests.post')
    def test_rate_limit_429(self, mock_post, mock_sleep):
        """測試 429 速率限制處理"""
        # 第一次：429 Too Many Requests
        mock_429 = MagicMock()
        mock_429.ok = False
        mock_429.json.return_value = {
            'error_code': 429,
            'description': 'Too Many Requests',
            'parameters': {'retry_after': 2}
        }
        mock_429.status_code = 429
        mock_429.text = 'Too Many Requests'

        # 第二次：成功
        mock_success = MagicMock()
        mock_success.ok = True

        mock_post.side_effect = [mock_429, mock_success]

        result = send_to_chat("token", "123", "Hello")
        assert result is True

        # 驗證等待了 retry_after 秒
        mock_sleep.assert_any_call(2)
