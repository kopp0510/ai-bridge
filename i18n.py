#!/usr/bin/env python3
"""
國際化（i18n）模組
透過 .env 的 AI_BRIDGE_LANGUAGE 設定選擇語言（舊鍵 LANGUAGE 仍支援）
"""

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ['zh-TW', 'en']
DEFAULT_LANGUAGE = 'zh-TW'

_translations: dict = {}
_current_language: str = DEFAULT_LANGUAGE
_lock = threading.Lock()


def init(language: str = None):
    """初始化 i18n"""
    global _translations, _current_language

    # 優先讀專屬鍵 AI_BRIDGE_LANGUAGE；LANGUAGE 為向後相容的舊鍵，
    # 但它是 POSIX/gettext 標準環境變數（Linux shell 常有 en_US:en 這類值），可能被系統覆蓋
    lang = language or os.getenv('AI_BRIDGE_LANGUAGE') or os.getenv('LANGUAGE', DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        logger.warning(f"不支援的語言 '{lang}'，使用預設 '{DEFAULT_LANGUAGE}'")
        lang = DEFAULT_LANGUAGE

    _current_language = lang
    locales_dir = Path(__file__).parent / 'locales'
    locale_file = locales_dir / f'{lang}.json'

    with open(locale_file, 'r', encoding='utf-8') as f:
        _translations = json.load(f)


def t(key: str, **kwargs) -> str:
    """翻譯函數

    Args:
        key: 點分隔的翻譯 key，如 'bot.unauthorized'
        **kwargs: 變數替換

    Returns:
        翻譯後的字串，key 不存在時回傳 key 本身
    """
    if not _translations:
        with _lock:
            if not _translations:
                init()

    value = _translations
    for part in key.split('.'):
        if not isinstance(value, dict):
            return key
        value = value.get(part)

    if not isinstance(value, str):
        return key

    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value

    return value


def get_language() -> str:
    """取得當前語言"""
    return _current_language
