#!/usr/bin/env python3
"""
CLI 提供者抽象層
支援 Claude Code、Gemini CLI 和 OpenAI Codex CLI 的差異化配置
"""

import json
import logging
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Protocol, Optional

from config import config as app_config
from i18n import t

logger = logging.getLogger(__name__)


class CliProvider(Protocol):
    """CLI 工具提供者介面"""

    @property
    def name(self) -> str:
        """CLI 名稱，如 'claude' 或 'gemini'"""
        ...

    @property
    def command(self) -> str:
        """CLI 執行檔名稱"""
        ...

    @property
    def default_tmux_prefix(self) -> str:
        """tmux 會話名稱預設前綴"""
        ...

    def build_launch_command(self, cli_args: str) -> str:
        """組合啟動命令"""
        ...

    def configure_hooks(self, work_dir: str, session_name: str,
                        hook_script: str) -> bool:
        """在專案目錄中配置 hook"""
        ...

    @property
    def extra_enter(self) -> bool:
        """送出訊息時是否需要額外一次 Enter（Gemini CLI 需要）"""
        ...

    @property
    def pre_enter_delay(self) -> float:
        """送出文字後、按 Enter 前的延遲秒數（Codex ink/React TUI 需要）"""
        ...

    def remove_hooks(self, work_dir: str) -> bool:
        """從專案目錄移除 hook 配置"""
        ...

    def is_installed(self) -> bool:
        """檢查 CLI 是否已安裝"""
        ...


# === 共用 helper ===

# bridge 建立的 hook entry 識別標記（_build_hook_command 產生的 command 一定含此前綴）
_BRIDGE_HOOK_MARKER = 'TELEGRAM_SESSION_NAME='


def _backup_file(path: Path) -> None:
    """修改使用者全域設定檔前備份一份 .bak"""
    try:
        if path.exists():
            shutil.copy2(path, Path(str(path) + '.bak'))
    except OSError as e:
        logger.warning(f"Backup failed for {path}: {e}")


def _is_bridge_hook_entry(entry) -> bool:
    """判斷 hook entry 是否由本 bridge 建立（不動使用者自己的 hooks）"""
    if not isinstance(entry, dict):
        return False
    return any(
        _BRIDGE_HOOK_MARKER in h.get('command', '')
        for h in entry.get('hooks', []) if isinstance(h, dict)
    )


def _remove_hook_key(settings_file: Path, hook_key: str, log_label: str) -> bool:
    """從設定檔移除 bridge 建立的 hook entry（保留使用者自己的 hooks 與其他設定）"""
    if not settings_file.exists():
        return True

    with open(settings_file, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    entries = settings.get('hooks', {}).get(hook_key) if isinstance(settings.get('hooks'), dict) else None
    if isinstance(entries, list):
        remaining = [e for e in entries if not _is_bridge_hook_entry(e)]
        if len(remaining) != len(entries):
            if remaining:
                settings['hooks'][hook_key] = remaining
            else:
                del settings['hooks'][hook_key]
                if not settings['hooks']:
                    del settings['hooks']

            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

    logger.info(t(log_label, name=str(settings_file.parent.parent)))
    return True


def _configure_hooks_json(work_dir: str, config_subpath: str, hook_key: str,
                          hook_data: list, log_label: str) -> bool:
    """共用的 JSON hook 配置邏輯（讀取 → 合併 → 寫回）

    合併而非覆蓋：保留使用者自己的同名 hooks，只取代 bridge 先前建立的 entry。
    既有設定檔無法解析時中止配置，避免以空設定覆寫使用者檔案。

    Args:
        work_dir: 專案目錄
        config_subpath: 設定檔相對路徑（如 '.claude/settings.local.json'）
        hook_key: hook 事件名稱（如 'Stop' 或 'AfterAgent'）
        hook_data: hook 配置資料
        log_label: 成功日誌的 i18n key
    """
    settings_file = Path(work_dir) / config_subpath
    settings_file.parent.mkdir(exist_ok=True)

    existing_settings = {}
    if settings_file.exists():
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                existing_settings = json.load(f)
        except Exception as e:
            logger.error(t('provider.hooks_read_failed', error=e))
            return False

    if not isinstance(existing_settings.get('hooks'), dict):
        existing_settings['hooks'] = {}

    entries = existing_settings['hooks'].get(hook_key)
    if not isinstance(entries, list):
        entries = []
    entries = [e for e in entries if not _is_bridge_hook_entry(e)]
    entries.extend(hook_data)
    existing_settings['hooks'][hook_key] = entries

    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(existing_settings, f, indent=2, ensure_ascii=False)

    return True


def _build_hook_command(session_name: str, cli_type: str, hook_script: str) -> str:
    """組合 hook 命令字串"""
    return (
        f"TELEGRAM_SESSION_NAME={shlex.quote(session_name)} "
        f"TELEGRAM_CLI_TYPE={cli_type} "
        f"{shlex.quote(hook_script)}"
    )


# === 基底類別 ===

class BaseProvider:
    """Provider 共用邏輯基底類別

    子類別需定義：
        _name, _command, _config_subpath, _hook_key, _hook_timeout,
        _hook_needs_matcher, _extra_enter, _pre_enter_delay
    """
    _name: str
    _command: str
    _config_subpath: str  # 如 '.claude/settings.local.json'
    _hook_key: str        # 如 'Stop' 或 'AfterAgent'
    _hook_timeout: int    # 秒或毫秒（依 CLI 而定）
    _hook_needs_matcher: bool = False  # Gemini 需要 matcher: "*"
    _extra_enter: bool = False
    _pre_enter_delay: float = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def command(self) -> str:
        return self._command

    @property
    def default_tmux_prefix(self) -> str:
        return f"{self._name}-"

    @property
    def extra_enter(self) -> bool:
        return self._extra_enter

    @property
    def pre_enter_delay(self) -> float:
        return self._pre_enter_delay

    def build_launch_command(self, cli_args: str) -> str:
        return f"{self._command} {cli_args}".strip() if cli_args else self._command

    def is_installed(self) -> bool:
        try:
            return subprocess.run(
                ['which', self._command], capture_output=True, text=True,
                timeout=app_config.tmux.TMUX_CMD_TIMEOUT
            ).returncode == 0
        except Exception:
            return False

    def configure_hooks(self, work_dir: str, session_name: str,
                        hook_script: str) -> bool:
        if not work_dir:
            return False

        try:
            hook_command = _build_hook_command(session_name, self._name, hook_script)
            inner_hook = {
                "type": "command",
                "command": hook_command,
                "timeout": self._hook_timeout
            }
            hook_entry = {"hooks": [inner_hook]}
            if self._hook_needs_matcher:
                hook_entry["matcher"] = "*"

            if not _configure_hooks_json(
                work_dir, self._config_subpath, self._hook_key,
                [hook_entry], f'provider.hooks_configured_{self._name}'
            ):
                return False

            logger.info(t(f'provider.hooks_configured_{self._name}', name=session_name))
            self._post_configure_hooks(work_dir)
            return True

        except Exception as e:
            logger.warning(t('provider.hooks_config_failed', error=e))
            return False

    def _post_configure_hooks(self, work_dir: str) -> None:
        """hook 配置後的額外動作（子類別覆寫）"""
        pass

    def remove_hooks(self, work_dir: str) -> bool:
        if not work_dir:
            return False
        try:
            settings_file = Path(work_dir) / self._config_subpath
            return _remove_hook_key(settings_file, self._hook_key,
                                    f'provider.hooks_removed_{self._name}')
        except Exception as e:
            logger.warning(t('provider.hooks_remove_failed', error=e))
            return False


# === 具體 Provider ===

class ClaudeProvider(BaseProvider):
    """Claude Code CLI 提供者"""
    _name = "claude"
    _command = "claude"
    _config_subpath = '.claude/settings.local.json'
    _hook_key = "Stop"
    _hook_timeout = 30


class GeminiProvider(BaseProvider):
    """Gemini CLI 提供者"""
    _name = "gemini"
    _command = "gemini"
    _config_subpath = '.gemini/settings.json'
    _hook_key = "AfterAgent"
    _hook_timeout = 30000  # 毫秒
    _hook_needs_matcher = True
    _extra_enter = True

    def _post_configure_hooks(self, work_dir: str) -> None:
        self._trust_folder(work_dir)

    @staticmethod
    def _trust_folder(work_dir: str) -> None:
        """將目錄加入 ~/.gemini/trustedFolders.json"""
        try:
            trusted_file = Path.home() / '.gemini' / 'trustedFolders.json'
            trusted = {}
            if trusted_file.exists():
                with open(trusted_file, 'r', encoding='utf-8') as f:
                    trusted = json.load(f)

            abs_path = str(Path(work_dir).resolve())
            if trusted.get(abs_path) == "TRUST_FOLDER":
                return

            _backup_file(trusted_file)
            trusted[abs_path] = "TRUST_FOLDER"
            with open(trusted_file, 'w', encoding='utf-8') as f:
                json.dump(trusted, f, indent=2, ensure_ascii=False)

            logger.info(t('provider.folder_trusted', path=abs_path))
        except Exception as e:
            logger.warning(t('provider.folder_trust_failed', error=e))


class CodexProvider(BaseProvider):
    """OpenAI Codex CLI 提供者"""
    _name = "codex"
    _command = "codex"
    _config_subpath = '.codex/hooks.json'
    _hook_key = "Stop"
    _hook_timeout = 30
    _pre_enter_delay = 0.15  # ink/React TUI 需要延遲，避免 Enter 被當成換行

    def _post_configure_hooks(self, work_dir: str) -> None:
        self._enable_hooks_feature_flag()
        self._trust_folder(work_dir)

    # 精確匹配 codex_hooks 賦值行（不會誤命中註解或含此字串的其他行）
    _HOOK_FLAG_LINE = re.compile(r'^\s*codex_hooks\s*=')

    @classmethod
    def _enable_hooks_feature_flag(cls) -> None:
        """在 ~/.codex/config.toml 中啟用 codex_hooks = true"""
        try:
            config_dir = Path.home() / '.codex'
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / 'config.toml'

            content = ''
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()

            # 先用 TOML parser 確認現況：已啟用就不動使用者檔案；
            # 檔案無法解析時中止，避免行操作把損壞的檔案改得更糟
            try:
                parsed = tomllib.loads(content)
                if parsed.get('features', {}).get('codex_hooks') is True:
                    return
            except tomllib.TOMLDecodeError as e:
                logger.warning(t('provider.hooks_feature_enable_failed', error=e))
                return

            _backup_file(config_file)

            lines = content.splitlines(keepends=True)
            feature_section_idx = None
            hook_line_idx = None
            current_section = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('['):
                    current_section = stripped
                    if stripped == '[features]':
                        feature_section_idx = i
                elif cls._HOOK_FLAG_LINE.match(line) and current_section == '[features]':
                    hook_line_idx = i

            if hook_line_idx is not None:
                lines[hook_line_idx] = 'codex_hooks = true\n'
            elif feature_section_idx is not None:
                lines.insert(feature_section_idx + 1, 'codex_hooks = true\n')
            else:
                if lines and not lines[-1].endswith('\n'):
                    lines.append('\n')
                lines.append('\n[features]\n')
                lines.append('codex_hooks = true\n')

            with open(config_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.info(t('provider.hooks_feature_enabled', path=str(config_file)))
        except Exception as e:
            logger.warning(t('provider.hooks_feature_enable_failed', error=e))

    @staticmethod
    def _trust_folder(work_dir: str) -> None:
        """在 ~/.codex/config.toml 中將目錄標記為信任"""
        try:
            abs_path = str(Path(work_dir).resolve())
            config_dir = Path.home() / '.codex'
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / 'config.toml'

            content = ''
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()

            # 用 TOML parser 確認現況（比子字串比對可靠）；無法解析時中止
            try:
                parsed = tomllib.loads(content)
                projects = parsed.get('projects', {})
                if isinstance(projects.get(abs_path), dict) and \
                        projects[abs_path].get('trust_level') == 'trusted':
                    return
            except tomllib.TOMLDecodeError as e:
                logger.warning(t('provider.folder_trust_failed', error=e))
                return

            _backup_file(config_file)

            # TOML basic string 跳脫（路徑含 " 或 \ 時仍產生合法 TOML）
            escaped = abs_path.replace('\\', '\\\\').replace('"', '\\"')
            section_header = f'[projects."{escaped}"]'

            if content and not content.endswith('\n'):
                content += '\n'
            content += f'\n{section_header}\ntrust_level = "trusted"\n'

            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(t('provider.folder_trusted_codex', path=abs_path))
        except Exception as e:
            logger.warning(t('provider.folder_trust_failed', error=e))


# === Provider 註冊 ===

_PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "codex": CodexProvider,
}


def create_provider(cli_type: str) -> CliProvider:
    """根據 cli_type 建立對應的 Provider"""
    provider_class = _PROVIDERS.get(cli_type)
    if provider_class is None:
        supported = ', '.join(_PROVIDERS.keys())
        raise ValueError(t('provider.unsupported_cli', cli_type=cli_type, supported=supported))
    return provider_class()
