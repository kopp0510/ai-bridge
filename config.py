#!/usr/bin/env python3
"""
配置管理模組
集中管理所有配置參數，消除魔數
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TmuxConfig:
    """Tmux 相關配置"""
    # 日誌設定
    LOG_DIR: str = os.path.expanduser("~/.ai_bridge/logs")  # 日誌目錄
    LOG_FILE_MODE: int = 0o600      # 日誌文件權限（只有擁有者可讀寫）
    LOG_MAX_SIZE: int = 10 * 1024 * 1024   # 10MB 觸發截斷
    LOG_KEEP_SIZE: int = 5 * 1024 * 1024   # 截斷後保留 5MB
    LOG_CHECK_INTERVAL: int = 1800         # 檢查間隔 30 分鐘

    # 會話設定
    SESSION_INIT_DELAY: float = 2.0 # 會話初始化等待時間（秒）
    COMMAND_DELAY: float = 1.0      # 命令間延遲（秒）

    # tmux 子進程逾時（秒），防止 tmux server 無回應時執行緒永久卡死
    TMUX_CMD_TIMEOUT: int = 10

    # 超過此長度的訊息改用 load-buffer + paste-buffer，避免 send-keys 截斷
    PASTE_BUFFER_THRESHOLD: int = 2000

    # 互動偵測輪詢
    POLL_INTERVAL: float = 2.0      # 輪詢間隔（秒）
    POLL_COOLDOWN: int = 30         # 同一 session 發送冷卻時間（秒）
    POLL_HASH_TTL: int = 600        # 選項 hash 去重有效期（秒），過期後允許重發
    POLL_HASH_MAX_SIZE: int = 1000  # hash 集合上限，防記憶體洩漏
    LOG_TAIL_BYTES: int = 5000      # 輪詢時讀取日誌尾部的位元組數（足以包含選項區塊）


@dataclass
class QueueConfig:
    """佇列相關配置"""
    MESSAGE_QUEUE_SIZE: int = 1000  # 訊息佇列大小限制
    QUEUE_TIMEOUT: float = 1.0      # 佇列讀取超時（秒）


@dataclass
class SecurityConfig:
    """安全相關配置"""
    # 輸入驗證
    MAX_MESSAGE_LENGTH: int = 10000     # 最大輸入訊息長度


@dataclass
class TelegramConfig:
    """Telegram 相關配置（長度上限以 UTF-16 code units 計，同 Telegram API）"""
    MAX_SEND_LENGTH: int = 4000      # Telegram 發送訊息長度上限（UTF-16 units）
    MAX_TITLE_LENGTH: int = 3000     # 互動選項標題截斷長度（UTF-16 units）
    MAX_HEADER_LENGTH: int = 4000    # 按鈕訊息 header 上限（UTF-16 units，API 硬上限 4096）
    API_MAX_MESSAGE_LENGTH: int = 4096   # Telegram sendMessage 硬上限（UTF-16 units）
    MAX_BUTTON_TEXT_LENGTH: int = 64     # InlineKeyboard 按鈕文字截斷長度（UTF-16 units）
    # callback_data 硬上限 64 bytes；扣最長前綴 'select_'(7) 與 ':50'(3) → 名稱預算 54 bytes(UTF-8)
    MAX_SESSION_NAME_BYTES: int = 54
    TRUNCATE_BOUNDARY_WINDOW: int = 500  # 語意截斷回看窗（UTF-16 units）
    API_TIMEOUT: int = 10            # Telegram API 請求逾時（秒）


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    WINDOW_SECONDS: int = 5          # 速率限制時間窗（秒）
    MAX_MESSAGES: int = 3            # 時間窗內最多訊息數


@dataclass
class StatusConfig:
    """會話狀態追蹤配置"""
    STATUS_DIR: str = os.path.expanduser("~/.ai_bridge/status")
    BUSY_TIMEOUT_SECONDS: int = 3600  # busy 狀態超過此秒數自動清除


@dataclass
class ChainConfig:
    """會話串接配置"""
    CHAIN_DIR: str = os.path.expanduser("~/.ai_bridge/chains")
    CHAIN_TTL_SECONDS: int = 3600    # chain 檔過期時間（1小時）
    MAX_CHAIN_DEPTH: int = 5         # 最大串接段數（含起始節點，即最多 4 次轉發）
    CLAIMED_TTL_SECONDS: int = 300   # 孤兒 .claimed 檔清理門檻（5 分鐘）


@dataclass
class AppConfig:
    """應用程式總配置"""
    tmux: TmuxConfig = field(default_factory=TmuxConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    status: StatusConfig = field(default_factory=StatusConfig)
    chain: ChainConfig = field(default_factory=ChainConfig)

    # 環境變數
    @property
    def bot_token(self) -> Optional[str]:
        return os.getenv('TELEGRAM_BOT_TOKEN')

    @property
    def allowed_user_ids(self) -> List[str]:
        ids = os.getenv('ALLOWED_USER_IDS', '')
        return [uid.strip() for uid in ids.split(',') if uid.strip()]

    @property
    def sessions_config_file(self) -> str:
        return os.getenv('SESSIONS_CONFIG_FILE', 'sessions.yaml')


# 全域配置實例
config = AppConfig()


class CompiledPatterns:
    """預編譯的正則表達式"""
    # ANSI 控制碼（含 OSC 序列如 0;⠐ 標題設置）
    ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07?)')

    # 控制字元（保留換行和 tab）
    CONTROL_CHARS = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]')

    # 多餘空行
    MULTIPLE_NEWLINES = re.compile(r'\n{3,}')

    # Claude Code 確認選項模式（❯ 1. xxx 或 1.xxx）
    CONFIRMATION_OPTION = re.compile(r'^\s*[❯]?\s*(\d+)\.\s*(.+)')

    # Gemini CLI 確認選項模式（● 1. xxx，框線已移除後）
    GEMINI_OPTION = re.compile(r'^\s*[●]?\s*(\d+)\.\s*(.*\S)')

    # Codex CLI 選項模式（可選的 › 前綴 + 編號）
    CODEX_OPTION = re.compile(r'^\s*[›]?\s*(\d+)\.\s*(.+)')

    # Telegram Bot Token 模式（用於日誌遮罩）
    BOT_TOKEN = re.compile(r'bot\d+:[\w\-]+')

    # 會話名稱模式
    SESSION_NAME = re.compile(r'^[\w\-]+$')

    # 訊息路由模式
    MESSAGE_ROUTE = re.compile(r'^#([\w\-]+)\s+(.+)$', re.DOTALL)

    # 串接偵測模式（偵測 >> #session 語法）
    CHAIN_DETECT = re.compile(r'\s+>>\s+#')

    # 串接分割模式
    CHAIN_SPLIT = re.compile(r'\s+>>\s+')

    # 串接目標解析模式（#session [可選前綴]）
    CHAIN_TARGET = re.compile(r'^#([\w\-]+)(?:\s+(.+))?$', re.DOTALL)

    # 框線字元
    BOX_CHARS = re.compile(r'^[│╭╮╰╯├─┤┼]+\s*$')


    # Session 名稱安全性驗證（檔案操作前必須呼叫）
    @staticmethod
    def is_safe_session_name(name: str) -> bool:
        """驗證 session 名稱：字元白名單 + callback_data 長度預算（64 bytes 扣前綴）"""
        return (bool(CompiledPatterns.SESSION_NAME.match(name))
                and len(name.encode('utf-8')) <= TelegramConfig.MAX_SESSION_NAME_BYTES)


def redact_token(text) -> str:
    """遮罩文字中的 Telegram Bot Token（例外訊息可能含 API URL，避免 token 寫入日誌）"""
    return CompiledPatterns.BOT_TOKEN.sub('bot***', str(text))


def utf16_len(text: str) -> int:
    """回傳 UTF-16 code units 長度（Telegram 4096 上限以此計算；astral 字元如 emoji 佔 2）"""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


def _cut_at_units(text: str, max_units: int) -> str:
    """取頭部至多 max_units（逐 code point 累計，天然不切斷 surrogate pair）"""
    units = 0
    for i, c in enumerate(text):
        units += 2 if ord(c) > 0xFFFF else 1
        if units > max_units:
            return text[:i]
    return text


def truncate_utf16(text: str, max_units: int, suffix: str = "") -> str:
    """硬截斷至 max_units（UTF-16 units，含 suffix）。上限內原樣返回（不加 suffix）。"""
    if utf16_len(text) <= max_units:
        return text
    return _cut_at_units(text, max_units - utf16_len(suffix)) + suffix


def truncate_utf16_tail(text: str, max_units: int) -> str:
    """同 truncate_utf16 但保留尾部（互動選項標題語意：提問重點在尾部）"""
    if utf16_len(text) <= max_units:
        return text
    units = 0
    for i in range(len(text) - 1, -1, -1):
        units += 2 if ord(text[i]) > 0xFFFF else 1
        if units > max_units:
            return text[i + 1:]
    return text


# 語意截斷的句末邊界：CJK 標點本身即句界；ASCII .!? 須後接空白/結尾（避免切在 3.14、URL 等）
_SENTENCE_BOUNDARY = re.compile(r'[。！？．]|[.!?](?=\s|$)', re.MULTILINE)


def truncate_utf16_smart(text: str, max_units: int, suffix: str = "") -> str:
    """語意安全截斷：截斷點回退到最近的段落/行/句末邊界（回看窗內），
    並在截斷造成 Markdown 圍欄（```）不成對時補上閉合，避免內容意思偏差。
    上限內原樣返回（不加 suffix）。"""
    if utf16_len(text) <= max_units:
        return text

    fence = '```'
    # 預留 suffix 與可能的圍欄閉合（\n``` = 4 units）
    budget = max_units - utf16_len(suffix) - 4
    head = _cut_at_units(text, budget)

    # 在回看窗內找最近的自然邊界
    window_start = len(_cut_at_units(head, max(0, budget - TelegramConfig.TRUNCATE_BOUNDARY_WINDOW)))
    window = head[window_start:]
    cut = -1
    para = window.rfind('\n\n')
    if para != -1:
        cut = window_start + para
    else:
        line = window.rfind('\n')
        if line != -1:
            cut = window_start + line
        else:
            last = None
            for m in _SENTENCE_BOUNDARY.finditer(window):
                last = m
            if last is not None:
                cut = window_start + last.end()
    if cut > 0:
        head = head[:cut]

    head = head.rstrip()
    if head.count(fence) % 2 == 1:
        head += '\n' + fence
    return head + suffix


# 預編譯模式實例
patterns = CompiledPatterns()
