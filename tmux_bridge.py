#!/usr/bin/env python3
"""
Tmux 橋接管理模組
管理 tmux 會話，處理輸入注入和輸出監控
"""

import os
import shlex
import subprocess
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from config import config
from cli_provider import CliProvider, ClaudeProvider
from i18n import t

logger = logging.getLogger(__name__)


class TmuxBridge:
    """Tmux 橋接管理器"""

    def __init__(self, session_name: str = "claude", log_file: Optional[str] = None,
                 cli_provider: Optional[CliProvider] = None):
        """
        初始化 Tmux 橋接管理器

        Args:
            session_name: tmux 會話名稱
            log_file: 日誌文件路徑
            cli_provider: CLI 提供者（預設為 ClaudeProvider）
        """
        self.session_name = session_name
        self.log_file = log_file or f"{config.tmux.LOG_DIR}/session_{session_name}.log"
        self.last_read_position = 0
        self.cli_provider = cli_provider or ClaudeProvider()

    def check_tmux_installed(self) -> bool:
        """檢查 tmux 是否已安裝"""
        try:
            return subprocess.run(
                ['which', 'tmux'], capture_output=True, text=True,
                timeout=config.tmux.TMUX_CMD_TIMEOUT
            ).returncode == 0
        except Exception:
            return False

    def session_exists(self) -> bool:
        """檢查 tmux 會話是否存在"""
        try:
            return subprocess.run(
                ['tmux', 'has-session', '-t', self.session_name],
                capture_output=True, text=True,
                timeout=config.tmux.TMUX_CMD_TIMEOUT
            ).returncode == 0
        except Exception:
            return False

    def _create_log_file(self) -> bool:
        """創建日誌文件並設置安全權限"""
        try:
            # 確保目錄存在
            log_dir = os.path.dirname(self.log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, mode=0o700)

            # 如果文件存在，先刪除
            if os.path.exists(self.log_file):
                os.remove(self.log_file)

            # 創建新文件並設置安全權限
            Path(self.log_file).touch()
            os.chmod(self.log_file, config.tmux.LOG_FILE_MODE)

            return True
        except Exception as e:
            logger.error(t('tmux.log_create_failed', error=e))
            return False

    def create_session(self, work_dir: Optional[str] = None,
                       session_alias: Optional[str] = None,
                       cli_args: str = "") -> bool:
        """
        創建 tmux 會話並啟動 CLI

        Args:
            work_dir: 工作目錄
            session_alias: 會話別名（用於 hook 通知）
            cli_args: CLI 啟動參數（如 --model sonnet）

        Returns:
            bool: 是否成功
        """
        if not self.check_tmux_installed():
            logger.error(t('tmux.not_installed'))
            raise Exception(t('tmux.not_installed'))

        if self.session_exists():
            logger.warning(t('tmux.session_exists', name=self.session_name))
            return True

        try:
            # 創建日誌文件（安全權限）
            if not self._create_log_file():
                logger.warning(t('tmux.log_create_warn'))

            # 創建 tmux 會話（detached 模式）
            cmd = ['tmux', 'new-session', '-d', '-s', self.session_name]

            if work_dir:
                cmd.extend(['-c', work_dir])

            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=config.tmux.TMUX_CMD_TIMEOUT)
            if result.returncode != 0:
                logger.error(t('tmux.create_failed', error=result.stderr))
                return False

            # 啟動日誌記錄
            result = subprocess.run([
                'tmux', 'pipe-pane', '-t', self.session_name,
                '-o', f'cat >> {shlex.quote(self.log_file)}'
            ], capture_output=True, text=True, timeout=config.tmux.TMUX_CMD_TIMEOUT)

            if result.returncode != 0:
                logger.warning(t('tmux.log_start_failed', error=result.stderr))

            # 配置 CLI hooks
            script_dir = os.path.dirname(os.path.abspath(__file__))
            hook_script = os.path.join(script_dir, 'notify_telegram.sh')
            self.cli_provider.configure_hooks(
                work_dir, session_alias or self.session_name, hook_script
            )

            # 等待會話初始化
            time.sleep(config.tmux.SESSION_INIT_DELAY)

            # 在會話中啟動 CLI
            cli_cmd = self.cli_provider.build_launch_command(cli_args)
            self.send_command(cli_cmd)

            logger.info(t('tmux.session_created', name=self.session_name))
            logger.info(t('tmux.log_file', path=self.log_file))

            return True

        except Exception as e:
            logger.error(t('tmux.create_error', error=e))
            return False

    def _run_tmux(self, args: list, error_msg: str) -> bool:
        """執行 tmux 命令的通用輔助方法"""
        return _run_tmux_command(args, error_msg)

    def send_command(self, command: str) -> bool:
        """發送命令到 tmux 會話（自動按 Enter）"""
        if not self.session_exists():
            logger.error(t('tmux.session_not_exists', name=self.session_name))
            return False

        return _send_message_keys(self.session_name, self.cli_provider, command)

    def send_text(self, text: str) -> bool:
        """發送文字到 tmux 會話（不自動按 Enter）"""
        if not self.session_exists():
            logger.error(t('tmux.session_not_exists', name=self.session_name))
            return False

        return self._run_tmux(
            ['send-keys', '-t', self.session_name, '-l', text],
            t('tmux.send_text_failed')
        )

    def read_new_output(self) -> str:
        """
        讀取新的輸出（從上次讀取位置開始）

        Returns:
            str: 新的輸出內容
        """
        if not os.path.exists(self.log_file):
            return ""

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # 移動到上次讀取的位置
                f.seek(self.last_read_position)

                # 讀取新內容
                new_content = f.read()

                # 更新讀取位置
                self.last_read_position = f.tell()

                return new_content

        except Exception as e:
            logger.error(t('tmux.read_log_failed', error=e))
            return ""

    def get_full_output(self) -> str:
        """
        獲取完整的輸出內容

        Returns:
            str: 完整輸出
        """
        if not os.path.exists(self.log_file):
            return ""

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(t('tmux.read_log_failed', error=e))
            return ""

    def attach_session(self) -> bool:
        """附加到 tmux 會話（進入互動模式）"""
        if not self.session_exists():
            logger.error(t('tmux.session_not_exists', name=self.session_name))
            return False

        try:
            subprocess.run(['tmux', 'attach-session', '-t', self.session_name])
            return True
        except Exception as e:
            logger.error(t('tmux.attach_failed', error=e))
            return False

    def kill_session(self) -> bool:
        """終止 tmux 會話"""
        if not self.session_exists():
            return True

        if not self._run_tmux(
            ['kill-session', '-t', self.session_name],
            t('tmux.kill_failed')
        ):
            return False

        logger.info(t('tmux.session_killed', name=self.session_name))

        # 安全地清理日誌文件
        if os.path.exists(self.log_file):
            try:
                os.remove(self.log_file)
            except Exception as e:
                logger.warning(t('tmux.log_cleanup_failed', error=e))

        return True

    def get_status(self) -> Dict[str, Any]:
        """
        獲取會話狀態

        Returns:
            dict: 狀態資訊
        """
        log_exists = os.path.exists(self.log_file)
        log_size = 0
        log_permissions = None

        if log_exists:
            try:
                stat_info = os.stat(self.log_file)
                log_size = stat_info.st_size
                log_permissions = oct(stat_info.st_mode)[-3:]
            except Exception:
                pass

        return {
            "tmux_installed": self.check_tmux_installed(),
            "session_exists": self.session_exists(),
            "session_name": self.session_name,
            "log_file": self.log_file,
            "log_exists": log_exists,
            "log_size": log_size,
            "log_permissions": log_permissions
        }


def _run_tmux_command(args: list, error_msg: str) -> bool:
    """執行 tmux 命令（含逾時保護），失敗時記錄日誌"""
    try:
        result = subprocess.run(
            ['tmux'] + args,
            capture_output=True, text=True,
            timeout=config.tmux.TMUX_CMD_TIMEOUT
        )
        if result.returncode != 0:
            logger.error(f"{error_msg}: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"{error_msg}: {e}")
        return False


def _send_message_keys(tmux_session: str, provider: CliProvider, message: str) -> bool:
    """共用的訊息送出邏輯（所有發送路徑統一走這裡）

    超長訊息使用 load-buffer + paste-buffer 避免 send-keys 截斷；
    之後依 provider 特性送出 Enter（pre_enter_delay / extra_enter）。
    """
    error_msg = f"tmux send failed for {tmux_session}"

    if len(message) > config.tmux.PASTE_BUFFER_THRESHOLD:
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix='.txt')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
                tmp.write(message)
            if not _run_tmux_command(['load-buffer', tmp_path], error_msg):
                return False
            if not _run_tmux_command(['paste-buffer', '-t', tmux_session], error_msg):
                return False
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    else:
        # 使用 -l 發送字面文字，避免特殊字元被解釋
        if not _run_tmux_command(['send-keys', '-t', tmux_session, '-l', message], error_msg):
            return False

    # Codex ink/React TUI 需要延遲，否則 Enter 可能被當成輸入框的換行
    if provider.pre_enter_delay > 0:
        time.sleep(provider.pre_enter_delay)

    if not _run_tmux_command(['send-keys', '-t', tmux_session, 'Enter'], error_msg):
        return False

    # Gemini CLI 的輸入框需要額外一次 Enter 才能送出
    if provider.extra_enter:
        if not _run_tmux_command(['send-keys', '-t', tmux_session, 'Enter'], error_msg):
            return False

    return True


def send_keys_to_session(tmux_session: str, cli_type: str, message: str) -> bool:
    """
    模組級輔助函式：透過 tmux send-keys 發送訊息到指定會話。
    用於不持有 TmuxBridge 實例的場景（如 hook 串接轉發）。

    Args:
        tmux_session: tmux 會話名稱
        cli_type: CLI 類型（'claude', 'gemini', 'codex'）
        message: 要發送的訊息

    Returns:
        bool: 是否成功
    """
    from cli_provider import create_provider

    try:
        provider = create_provider(cli_type)
    except ValueError:
        provider = ClaudeProvider()

    return _send_message_keys(tmux_session, provider, message)


if __name__ == '__main__':
    # 設置日誌
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # 測試代碼
    bridge = TmuxBridge()

    print("📊 狀態檢查:")
    status = bridge.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")

    if not status['tmux_installed']:
        print("\n❌ 請先安裝 tmux: brew install tmux")
    elif not status['session_exists']:
        print("\n💡 可以使用 bridge.create_session() 創建會話")
