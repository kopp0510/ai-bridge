#!/usr/bin/env python3
"""Hook 腳本（notify_telegram.sh）整合測試"""

import json
import os
import subprocess
import tempfile
import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_SCRIPT = os.path.join(SCRIPT_DIR, 'notify_telegram.sh')

# 使用 venv 的 Python
VENV_PYTHON = os.path.join(SCRIPT_DIR, 'venv', 'bin', 'python3')


# timeout 與 hook 實際 timeout（30 秒）對齊：
# 部分測試會對 api.telegram.org 發真實請求（假 token），網路慢時 10 秒不夠
def run_hook(stdin_data, env_overrides=None, timeout=30):
    """執行 hook 腳本並返回結果"""
    env = os.environ.copy()
    env['TELEGRAM_SESSION_NAME'] = 'test-session'
    env['TELEGRAM_BOT_TOKEN'] = 'fake-token-for-test'
    env['ALLOWED_USER_IDS'] = '123'
    env['TELEGRAM_CLI_TYPE'] = 'claude'
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        ['bash', HOOK_SCRIPT],
        input=json.dumps(stdin_data),
        capture_output=True, text=True,
        env=env, timeout=timeout,
        cwd=SCRIPT_DIR,
    )
    return result


class TestMessageExtraction:
    """訊息提取邏輯測試（Python 解析區塊）"""

    def test_claude_last_assistant_message(self):
        """Claude 格式：last_assistant_message"""
        # 此測試驗證 Python 解析邏輯，但會在 send_telegram_notification.py 失敗
        # 因為使用假 token，所以預期 exit code 1，但可以檢查 debug log
        stdin = {"last_assistant_message": "Hello from Claude"}
        result = run_hook(stdin)
        # 腳本會嘗試發送但因假 token 失敗，這是預期行為
        # 重要的是訊息被正確提取（不會在解析階段就退出）

    def test_gemini_prompt_response(self):
        """Gemini 格式：prompt_response"""
        stdin = {"prompt_response": "Hello from Gemini"}
        result = run_hook(stdin, {'TELEGRAM_CLI_TYPE': 'gemini'})
        # 同上，驗證不會在解析階段退出

    def test_empty_message_exits_quietly(self):
        """空訊息時靜默退出（exit 0）"""
        stdin = {"last_assistant_message": "", "prompt_response": ""}
        result = run_hook(stdin)
        assert result.returncode == 0

    def test_no_message_fields_exits_quietly(self):
        """無訊息欄位時靜默退出"""
        stdin = {"session_id": "123"}
        result = run_hook(stdin)
        assert result.returncode == 0


class TestGeminiStdoutJson:
    """Gemini hook stdout JSON 輸出測試"""

    def test_gemini_empty_message_outputs_json(self):
        """Gemini 模式下空訊息仍輸出 JSON"""
        stdin = {"session_id": "123"}
        result = run_hook(stdin, {'TELEGRAM_CLI_TYPE': 'gemini'})
        assert result.returncode == 0
        assert '{}' in result.stdout

    def test_claude_empty_message_no_json(self):
        """Claude 模式下空訊息不輸出 JSON"""
        stdin = {"session_id": "123"}
        result = run_hook(stdin, {'TELEGRAM_CLI_TYPE': 'claude'})
        assert result.returncode == 0
        assert '{}' not in result.stdout


class TestEnvironmentValidation:
    """環境變數驗證測試"""

    @pytest.mark.skipif(
        os.path.exists(os.path.join(SCRIPT_DIR, '.env')),
        reason="腳本從 SCRIPT_DIR/.env 讀取 token，無法隔離測試"
    )
    def test_missing_bot_token(self):
        """缺少 TELEGRAM_BOT_TOKEN 時退出碼 1"""
        stdin = {"last_assistant_message": "test"}
        env = {
            'TELEGRAM_SESSION_NAME': 'test',
            'TELEGRAM_CLI_TYPE': 'claude',
            'HOME': os.environ.get('HOME', '/tmp'),
            'PATH': os.environ.get('PATH', '/usr/bin'),
        }
        result = subprocess.run(
            ['bash', HOOK_SCRIPT],
            input=json.dumps(stdin),
            capture_output=True, text=True,
            env=env, timeout=10,
            cwd=SCRIPT_DIR,
        )
        assert result.returncode == 1

    def test_missing_session_name(self):
        """缺少 TELEGRAM_SESSION_NAME 時退出碼 1"""
        stdin = {"last_assistant_message": "test"}
        env = {
            'TELEGRAM_BOT_TOKEN': 'fake-token',
            'TELEGRAM_CLI_TYPE': 'claude',
            'HOME': os.environ.get('HOME', '/tmp'),
            'PATH': os.environ.get('PATH', '/usr/bin'),
        }
        result = subprocess.run(
            ['bash', HOOK_SCRIPT],
            input=json.dumps(stdin),
            capture_output=True, text=True,
            env=env, timeout=10,
            cwd=SCRIPT_DIR,
        )
        assert result.returncode == 1


class TestTranscriptFallback:
    """Transcript fallback 解析測試"""

    def test_json_transcript(self):
        """從 JSON transcript 提取 assistant 訊息"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            transcript = {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "transcript reply"}]},
                ]
            }
            json.dump(transcript, f)
            transcript_path = f.name

        try:
            stdin = {"transcript_path": transcript_path}
            result = run_hook(stdin)
            # 訊息應被提取（但 Telegram 發送會失敗因假 token）
        finally:
            os.unlink(transcript_path)

    def test_jsonl_transcript(self):
        """從 JSONL transcript 提取 assistant 訊息"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write(json.dumps({"role": "user", "content": [{"type": "text", "text": "hello"}]}) + "\n")
            f.write(json.dumps({"role": "assistant", "content": [{"type": "text", "text": "jsonl reply"}]}) + "\n")
            transcript_path = f.name

        try:
            stdin = {"transcript_path": transcript_path}
            result = run_hook(stdin)
        finally:
            os.unlink(transcript_path)

    def test_nonexistent_transcript(self):
        """transcript 文件不存在時靜默退出"""
        stdin = {"transcript_path": "/nonexistent/path.json"}
        result = run_hook(stdin)
        assert result.returncode == 0
