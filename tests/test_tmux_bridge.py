#!/usr/bin/env python3
"""TmuxBridge 單元測試"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from tmux_bridge import TmuxBridge
from cli_provider import ClaudeProvider, GeminiProvider


def make_run_result(returncode=0, stdout="", stderr=""):
    """建立 subprocess.run 的模擬返回值"""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestCheckTmuxInstalled:
    """check_tmux_installed 測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_installed(self, mock_run):
        mock_run.return_value = make_run_result(returncode=0)
        bridge = TmuxBridge("test")
        assert bridge.check_tmux_installed() is True
        mock_run.assert_called_once_with(
            ['which', 'tmux'], capture_output=True, text=True, timeout=10
        )

    @patch('tmux_bridge.subprocess.run')
    def test_not_installed(self, mock_run):
        mock_run.return_value = make_run_result(returncode=1)
        bridge = TmuxBridge("test")
        assert bridge.check_tmux_installed() is False

    @patch('tmux_bridge.subprocess.run', side_effect=Exception("error"))
    def test_exception(self, mock_run):
        bridge = TmuxBridge("test")
        assert bridge.check_tmux_installed() is False


class TestSessionExists:
    """session_exists 測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_exists(self, mock_run):
        mock_run.return_value = make_run_result(returncode=0)
        bridge = TmuxBridge("my-session")
        assert bridge.session_exists() is True
        mock_run.assert_called_once_with(
            ['tmux', 'has-session', '-t', 'my-session'],
            capture_output=True, text=True, timeout=10
        )

    @patch('tmux_bridge.subprocess.run')
    def test_not_exists(self, mock_run):
        mock_run.return_value = make_run_result(returncode=1)
        bridge = TmuxBridge("my-session")
        assert bridge.session_exists() is False

    @patch('tmux_bridge.subprocess.run', side_effect=Exception("error"))
    def test_exception(self, mock_run):
        bridge = TmuxBridge("my-session")
        assert bridge.session_exists() is False


class TestCreateLogFile:
    """_create_log_file 測試"""

    def test_creates_file_with_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            bridge = TmuxBridge("test", log_file=log_path)
            assert bridge._create_log_file() is True
            assert os.path.exists(log_path)
            # 檢查權限 0o600
            mode = oct(os.stat(log_path).st_mode)[-3:]
            assert mode == '600'

    def test_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "subdir", "test.log")
            bridge = TmuxBridge("test", log_file=log_path)
            assert bridge._create_log_file() is True
            assert os.path.exists(log_path)

    def test_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            with open(log_path, 'w') as f:
                f.write("old content")
            bridge = TmuxBridge("test", log_file=log_path)
            assert bridge._create_log_file() is True
            with open(log_path, 'r') as f:
                assert f.read() == ""


class TestCreateSession:
    """create_session 測試"""

    @patch('tmux_bridge.time.sleep')
    @patch('tmux_bridge.subprocess.run')
    def test_tmux_not_installed_raises(self, mock_run, mock_sleep):
        mock_run.return_value = make_run_result(returncode=1)  # which tmux fails
        bridge = TmuxBridge("test")
        with pytest.raises(Exception, match="tmux 未安裝"):
            bridge.create_session()

    @patch('tmux_bridge.subprocess.run')
    def test_session_already_exists(self, mock_run):
        """會話已存在時返回 True"""
        # which tmux → ok, has-session → ok
        mock_run.side_effect = [
            make_run_result(returncode=0),  # which tmux
            make_run_result(returncode=0),  # has-session
        ]
        bridge = TmuxBridge("test")
        assert bridge.create_session() is True

    @patch('tmux_bridge.time.sleep')
    @patch('tmux_bridge.subprocess.run')
    def test_tmux_new_session_fails(self, mock_run, mock_sleep):
        """tmux new-session 失敗時返回 False"""
        mock_run.side_effect = [
            make_run_result(returncode=0),  # which tmux
            make_run_result(returncode=1),  # has-session (不存在)
            make_run_result(returncode=1, stderr="error"),  # new-session 失敗
        ]
        bridge = TmuxBridge("test")
        bridge._create_log_file = MagicMock(return_value=True)
        assert bridge.create_session() is False

    @patch('tmux_bridge.time.sleep')
    @patch('tmux_bridge.subprocess.run')
    def test_successful_creation(self, mock_run, mock_sleep):
        """正常創建流程"""
        mock_run.side_effect = [
            make_run_result(returncode=0),  # which tmux
            make_run_result(returncode=1),  # has-session (不存在)
            make_run_result(returncode=0),  # new-session
            make_run_result(returncode=0),  # pipe-pane
            # send_command 呼叫 session_exists + 2x _run_tmux
            make_run_result(returncode=0),  # has-session (send_command)
            make_run_result(returncode=0),  # send-keys -l
            make_run_result(returncode=0),  # send-keys Enter
        ]
        provider = MagicMock()
        provider.configure_hooks = MagicMock(return_value=True)
        provider.build_launch_command = MagicMock(return_value="claude")
        provider.pre_enter_delay = 0

        bridge = TmuxBridge("test", cli_provider=provider)
        bridge._create_log_file = MagicMock(return_value=True)

        assert bridge.create_session(work_dir="/tmp/test", session_alias="myalias") is True
        provider.configure_hooks.assert_called_once()
        provider.build_launch_command.assert_called_once_with("")

    @patch('tmux_bridge.time.sleep')
    @patch('tmux_bridge.subprocess.run')
    def test_passes_cli_args(self, mock_run, mock_sleep):
        """驗證 cli_args 傳遞給 provider"""
        mock_run.side_effect = [
            make_run_result(returncode=0),  # which tmux
            make_run_result(returncode=1),  # has-session
            make_run_result(returncode=0),  # new-session
            make_run_result(returncode=0),  # pipe-pane
            make_run_result(returncode=0),  # has-session (send_command)
            make_run_result(returncode=0),  # send-keys -l
            make_run_result(returncode=0),  # send-keys Enter
        ]
        provider = MagicMock()
        provider.configure_hooks = MagicMock(return_value=True)
        provider.build_launch_command = MagicMock(return_value="claude --model sonnet")
        provider.pre_enter_delay = 0

        bridge = TmuxBridge("test", cli_provider=provider)
        bridge._create_log_file = MagicMock(return_value=True)

        bridge.create_session(cli_args="--model sonnet")
        provider.build_launch_command.assert_called_once_with("--model sonnet")


class TestSendCommand:
    """send_command 測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_session_not_exists(self, mock_run):
        mock_run.return_value = make_run_result(returncode=1)  # has-session fails
        bridge = TmuxBridge("test")
        assert bridge.send_command("hello") is False

    @patch('tmux_bridge.subprocess.run')
    def test_successful_send(self, mock_run):
        mock_run.side_effect = [
            make_run_result(returncode=0),  # has-session
            make_run_result(returncode=0),  # send-keys -l
            make_run_result(returncode=0),  # send-keys Enter
        ]
        bridge = TmuxBridge("test")
        assert bridge.send_command("hello") is True

    @patch('tmux_bridge.subprocess.run')
    def test_send_keys_fails(self, mock_run):
        mock_run.side_effect = [
            make_run_result(returncode=0),  # has-session
            make_run_result(returncode=1, stderr="error"),  # send-keys -l 失敗
        ]
        bridge = TmuxBridge("test")
        assert bridge.send_command("hello") is False


class TestSendText:
    """send_text 測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_session_not_exists(self, mock_run):
        mock_run.return_value = make_run_result(returncode=1)
        bridge = TmuxBridge("test")
        assert bridge.send_text("hello") is False

    @patch('tmux_bridge.subprocess.run')
    def test_successful_send(self, mock_run):
        mock_run.side_effect = [
            make_run_result(returncode=0),  # has-session
            make_run_result(returncode=0),  # send-keys -l (無 Enter)
        ]
        bridge = TmuxBridge("test")
        assert bridge.send_text("hello") is True


class TestReadOutput:
    """read_new_output / get_full_output 測試"""

    def test_read_new_output_no_file(self):
        bridge = TmuxBridge("test", log_file="/nonexistent/path.log")
        assert bridge.read_new_output() == ""

    def test_read_new_output_incremental(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            f.write("line1\n")
            f.flush()
            log_path = f.name

        try:
            bridge = TmuxBridge("test", log_file=log_path)
            assert bridge.read_new_output() == "line1\n"
            assert bridge.read_new_output() == ""  # 沒有新內容

            # 追加新內容
            with open(log_path, 'a') as f:
                f.write("line2\n")
            assert bridge.read_new_output() == "line2\n"
        finally:
            os.unlink(log_path)

    def test_get_full_output_no_file(self):
        bridge = TmuxBridge("test", log_file="/nonexistent/path.log")
        assert bridge.get_full_output() == ""

    def test_get_full_output(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            f.write("full content\n")
            log_path = f.name

        try:
            bridge = TmuxBridge("test", log_file=log_path)
            assert bridge.get_full_output() == "full content\n"
        finally:
            os.unlink(log_path)


class TestKillSession:
    """kill_session 測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_session_not_exists(self, mock_run):
        mock_run.return_value = make_run_result(returncode=1)  # has-session
        bridge = TmuxBridge("test")
        assert bridge.kill_session() is True  # 不存在時返回 True

    @patch('tmux_bridge.subprocess.run')
    def test_successful_kill(self, mock_run):
        mock_run.side_effect = [
            make_run_result(returncode=0),  # has-session
            make_run_result(returncode=0),  # kill-session
        ]
        bridge = TmuxBridge("test", log_file="/nonexistent.log")
        assert bridge.kill_session() is True

    @patch('tmux_bridge.subprocess.run')
    def test_kill_cleans_log(self, mock_run):
        mock_run.side_effect = [
            make_run_result(returncode=0),  # has-session
            make_run_result(returncode=0),  # kill-session
        ]
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_path = f.name

        bridge = TmuxBridge("test", log_file=log_path)
        assert bridge.kill_session() is True
        assert not os.path.exists(log_path)


class TestGetStatus:
    """get_status 測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_status_with_log(self, mock_run):
        mock_run.return_value = make_run_result(returncode=0)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            f.write("some content")
            log_path = f.name

        try:
            bridge = TmuxBridge("test-session", log_file=log_path)
            status = bridge.get_status()
            assert status['session_name'] == 'test-session'
            assert status['log_exists'] is True
            assert status['log_size'] > 0
            assert status['tmux_installed'] is True
            assert status['session_exists'] is True
        finally:
            os.unlink(log_path)

    @patch('tmux_bridge.subprocess.run')
    def test_status_no_log(self, mock_run):
        mock_run.return_value = make_run_result(returncode=1)
        bridge = TmuxBridge("test", log_file="/nonexistent.log")
        status = bridge.get_status()
        assert status['log_exists'] is False
        assert status['log_size'] == 0
        assert status['log_permissions'] is None


class TestCliProviderIntegration:
    """驗證 TmuxBridge 正確使用注入的 CliProvider"""

    def test_default_provider_is_claude(self):
        bridge = TmuxBridge("test")
        assert isinstance(bridge.cli_provider, ClaudeProvider)

    def test_custom_provider(self):
        provider = GeminiProvider()
        bridge = TmuxBridge("test", cli_provider=provider)
        assert isinstance(bridge.cli_provider, GeminiProvider)
