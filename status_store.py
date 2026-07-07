#!/usr/bin/env python3
"""
Session 忙碌狀態追蹤
bot 進程與 hook 進程（send_telegram_notification.py）共用，避免邏輯重複
"""

import logging
import os
from datetime import datetime

from config import config as app_config, patterns

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_SECONDS = app_config.status.BUSY_TIMEOUT_SECONDS


def mark_session_busy(session_name: str) -> None:
    """標記 session 為忙碌狀態"""
    if not patterns.is_safe_session_name(session_name):
        return
    status_dir = app_config.status.STATUS_DIR
    os.makedirs(status_dir, mode=0o700, exist_ok=True)
    busy_file = os.path.join(status_dir, f"{session_name}.busy")
    try:
        fd = os.open(busy_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(datetime.now().isoformat())
    except OSError as e:
        logger.warning(f"Failed to mark session busy: {e}")


def clear_session_busy(session_name: str) -> None:
    """清除 session 的忙碌標記"""
    if not patterns.is_safe_session_name(session_name):
        return
    busy_file = os.path.join(app_config.status.STATUS_DIR,
                             f"{session_name}.busy")
    try:
        os.remove(busy_file)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Failed to clear busy file: {e}")


def get_session_busy_seconds(session_name: str) -> int:
    """取得 session 忙碌秒數，未忙碌返回 -1。超過 BUSY_TIMEOUT_SECONDS 自動清除。"""
    busy_file = os.path.join(app_config.status.STATUS_DIR,
                             f"{session_name}.busy")
    try:
        with open(busy_file, 'r', encoding='utf-8') as f:
            start_time = datetime.fromisoformat(f.read().strip())
        seconds = int((datetime.now() - start_time).total_seconds())
        if seconds > BUSY_TIMEOUT_SECONDS:
            try:
                os.remove(busy_file)
            except OSError:
                pass
            return -1
        return seconds
    except (FileNotFoundError, ValueError, OSError):
        return -1
