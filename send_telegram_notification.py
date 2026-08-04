#!/usr/bin/env python3
"""
Helper script to send Telegram notifications from Claude Code hooks.
Called by notify_telegram.sh when Claude finishes responding.
"""

import json
import os
import sys
import time
import logging
import requests
from datetime import datetime
from requests.exceptions import RequestException, Timeout, ConnectionError as ReqConnectionError
from dotenv import load_dotenv
from config import config as app_config, patterns, redact_token, truncate_utf16_smart
from i18n import t
from status_store import (
    mark_session_busy as _mark_session_busy,
    clear_session_busy as _clear_session_busy,
)
from tmux_bridge import send_keys_to_session

# 設置日誌
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 配置常數
# 重試預算必須低於最短的 hook timeout（Claude/Codex 為 30 秒），
# 否則 hook 被 CLI 強制終止後，後續 chat 的通知會靜默丟失
MAX_MESSAGE_LENGTH = app_config.telegram.MAX_SEND_LENGTH
API_TIMEOUT = app_config.telegram.API_TIMEOUT
MAX_RETRIES = 2
RETRY_DELAY = 1.0
RETRY_BACKOFF = 2.0
MAX_RETRY_AFTER = 5  # 429 retry_after 上限（秒），避免 API 回傳大值時 sleep 超過 hook timeout


def send_telegram_message(session_name: str, message: str) -> bool:
    """
    Send a message to Telegram via Bot API

    Args:
        session_name: 會話名稱
        message: 要發送的訊息

    Returns:
        bool: 是否成功
    """
    # Load environment variables
    # hook 的 cwd 是目標專案目錄，必須指定 bridge 自己的 .env 絕對路徑，
    # 否則會誤讀目標專案的 .env（或完全讀不到）
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    allowed_users = os.getenv('ALLOWED_USER_IDS', '')

    if not bot_token:
        logger.error(t('notification.token_not_found'))
        return False

    # Get the first allowed user ID as the default chat ID
    chat_ids = [uid.strip() for uid in allowed_users.split(',') if uid.strip()]

    if not chat_ids:
        logger.error(t('notification.no_user_ids'))
        return False

    # 超長時語意安全截斷（UTF-16 units 計，回退到段落/句末邊界並閉合 Markdown 圍欄）
    truncated_message = truncate_utf16_smart(
        message, MAX_MESSAGE_LENGTH,
        "\n\n" + t('notification.message_truncated'))

    # Send to all allowed users
    success = True
    for chat_id in chat_ids:
        if not send_to_chat(bot_token, chat_id, truncated_message):
            success = False

    return success


def send_to_chat(bot_token: str, chat_id: str, message: str) -> bool:
    """
    發送訊息到指定 chat

    Args:
        bot_token: Bot token
        chat_id: Chat ID
        message: 訊息內容

    Returns:
        bool: 是否成功
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        numeric_chat_id = int(chat_id)
    except ValueError:
        logger.error(t('notification.invalid_chat_id', chat_id=chat_id))
        return False

    payload = {
        'chat_id': numeric_chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }

    # 重試機制
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=API_TIMEOUT)

            if response.ok:
                logger.info(f"Successfully sent message to chat {chat_id}")
                return True

            # API 返回錯誤
            error_data = response.json() if response.text else {}
            error_code = error_data.get('error_code', response.status_code)
            error_description = error_data.get('description', response.text)

            # 處理特定錯誤
            if error_code == 429:  # Too Many Requests
                retry_after = error_data.get('parameters', {}).get('retry_after', 5)
                retry_after = min(retry_after, MAX_RETRY_AFTER)
                logger.warning(f"Rate limited, waiting {retry_after}s before retry")
                time.sleep(retry_after)
                continue

            if error_code == 400 and 'parse entities' in error_description.lower():
                # Markdown 解析失敗，fallback 為純文字重發
                logger.warning(t('notification.markdown_fallback'))
                payload_plain = dict(payload)
                del payload_plain['parse_mode']
                try:
                    resp = requests.post(url, json=payload_plain, timeout=API_TIMEOUT)
                    if resp.ok:
                        logger.info(f"Successfully sent plain text message to chat {chat_id}")
                        return True
                    logger.error(f"Plain text fallback also failed: {resp.status_code}")
                except Exception as e:
                    logger.error(f"Plain text fallback error: {redact_token(e)}")
                return False

            if error_code in [400, 401, 403, 404]:
                # 不可重試的錯誤
                logger.error(f"Non-retryable error ({error_code}): {error_description}")
                return False

            # 其他錯誤，可重試
            last_error = f"API error ({error_code}): {error_description}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {last_error}")

        except Timeout:
            last_error = "Request timeout"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        except ReqConnectionError as e:
            # 例外訊息可能含 API URL（內嵌 token），記錄前遮罩
            last_error = f"Connection error: {redact_token(e)}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        except RequestException as e:
            last_error = f"Request error: {redact_token(e)}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        except Exception as e:
            last_error = f"Unexpected error: {redact_token(e)}"
            logger.error(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        # 計算退避延遲
        if attempt < MAX_RETRIES - 1:
            delay = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
            logger.info(f"Retrying in {delay:.1f}s...")
            time.sleep(delay)

    # 所有重試都失敗
    logger.error(f"All {MAX_RETRIES} attempts failed for chat {chat_id}. Last error: {last_error}")
    return False


def process_chain(session_name: str, raw_response: str) -> bool:
    """檢查 chain 檔並轉發回應到下一個會話"""
    # 驗證 session 名稱安全性（防 path traversal）
    if not patterns.is_safe_session_name(session_name):
        logger.error(f"Unsafe session name rejected: {session_name}")
        return False

    chain_dir = app_config.chain.CHAIN_DIR

    # 清理孤兒 .claimed.* 檔案（進程 crash 後遺留，超過 TTL 視為過期）
    CLAIMED_TTL = app_config.chain.CLAIMED_TTL_SECONDS
    try:
        if os.path.isdir(chain_dir):
            now = time.time()
            for fname in os.listdir(chain_dir):
                if '.claimed.' not in fname:
                    continue
                fpath = os.path.join(chain_dir, fname)
                try:
                    if now - os.path.getmtime(fpath) > CLAIMED_TTL:
                        os.remove(fpath)
                        logger.info(f"Cleaned orphaned claimed file: {fname}")
                except OSError:
                    pass
    except OSError as e:
        logger.debug(f"Error cleaning claimed files: {e}")

    # 檢查是否為串接最終節點完成（.done 標記檔）
    done_file = os.path.join(chain_dir, f"{session_name}.done")
    try:
        if os.path.exists(done_file):
            with open(done_file, 'r', encoding='utf-8') as f:
                done_info = json.load(f)
            os.remove(done_file)
            chain_path_list = done_info.get("chain_path", [])
            chain_path = " >> ".join([f"#{s}" for s in chain_path_list])
            step_count = done_info.get("step_count", 0)
            completed_msg = t('chain.completed', path=chain_path, steps=step_count)
            send_telegram_message(session_name, completed_msg)
            # 清理暫存 .md 檔案
            for result_file in done_info.get("result_files", []):
                try:
                    os.remove(result_file)
                    logger.info(f"Cleaned chain result file: {result_file}")
                except FileNotFoundError:
                    pass
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"Error processing done file: {e}")

    # 檢查 chain 檔（用原子 rename 防競態條件）
    chain_file = os.path.join(chain_dir, f"{session_name}.json")
    claimed_file = chain_file + f".claimed.{os.getpid()}"
    try:
        os.replace(chain_file, claimed_file)
    except FileNotFoundError:
        # 不存在或已被另一個 hook 消費
        return False
    except OSError as e:
        logger.error(f"Error claiming chain file: {e}")
        return False

    try:
        with open(claimed_file, 'r', encoding='utf-8') as f:
            chain = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error reading chain file: {e}")
        return False
    finally:
        try:
            os.remove(claimed_file)
        except OSError:
            pass

    # 檢查 TTL
    created_at = chain.get('created_at', '')
    try:
        created_time = datetime.fromisoformat(created_at)
        if (datetime.now() - created_time).total_seconds() > app_config.chain.CHAIN_TTL_SECONDS:
            expired_msg = t('chain.expired', source=session_name)
            send_telegram_message(session_name, expired_msg)
            logger.warning(f"Chain for {session_name} expired")
            return False
    except (ValueError, TypeError):
        logger.warning(f"Chain for {session_name} has invalid created_at: {created_at!r}, rejecting")
        return False

    # 驗證必要欄位
    required_fields = ['target_session', 'target_tmux', 'target_path', 'created_at']
    missing = [f for f in required_fields if not chain.get(f)]
    if missing:
        logger.error(f"Chain file missing required fields: {missing}")
        return False

    target_session = chain['target_session']
    target_tmux = chain['target_tmux']
    target_cli_type = chain.get('target_cli_type', 'claude')
    target_path = chain['target_path']
    prompt_prefix = chain.get('prompt_prefix', '')
    next_chain = chain.get('next_chain')
    chain_path = chain.get('chain_path', [])

    # 1. 發送交接通知到 Telegram
    handoff_msg = t('chain.handoff_notification',
                    source=session_name, target=target_session)
    send_telegram_message(session_name, handoff_msg)

    # 2. 將 A 的回應寫入暫存 .md 檔案（放在 B 的工作目錄內，確保可讀取）
    chain_result_file = os.path.join(target_path, f".ai_bridge_chain_{session_name}.md")
    try:
        # O_NOFOLLOW：目標目錄內若被植入同名 symlink，拒絕跟隨截斷任意檔案
        fd = os.open(chain_result_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(raw_response)
    except OSError as e:
        logger.error(f"Error writing chain result file: {e}")
        fail_msg = t('chain.forward_failed', source=session_name, target=target_session)
        send_telegram_message(session_name, fail_msg)
        return False

    # 3. 組合轉發訊息：任務指令 + 讀取檔案提示
    parts = []

    # B 的回應最終會回到 TG，統一用 TG 字元限制
    parts.append(t('session.length_hint',
                   max_chars=app_config.telegram.MAX_SEND_LENGTH).strip())

    if prompt_prefix:
        parts.append(prompt_prefix)

    parts.append(t('chain.read_file_hint', file_path=chain_result_file))

    forwarded_message = "\n\n".join(parts)

    # 4. 若有 next_chain，寫入目標 session 的 chain 檔（含累積 result_files）
    if next_chain:
        # 累積追蹤所有中間暫存檔，供最終 .done 清理
        prev_files = next_chain.get('_result_files', [])
        next_chain['_result_files'] = prev_files + [chain_result_file]
        try:
            os.makedirs(chain_dir, mode=0o700, exist_ok=True)
            next_file = os.path.join(chain_dir, f"{target_session}.json")
            fd = os.open(next_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(next_chain, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"Error writing next chain file: {e}")
    else:
        # 最終節點：寫入 .done 標記檔（含所有暫存檔路徑）
        if len(chain_path) >= 2:
            all_result_files = chain.get('_result_files', []) + [chain_result_file]
            try:
                os.makedirs(chain_dir, mode=0o700, exist_ok=True)
                done_data = {
                    "chain_path": chain_path,
                    "step_count": len(chain_path),
                    "result_files": all_result_files
                }
                done_path = os.path.join(chain_dir, f"{target_session}.done")
                fd = os.open(done_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(done_data, f, ensure_ascii=False)
            except OSError as e:
                logger.error(f"Error writing done file: {e}")

    # 5. 轉發到目標 tmux
    if not send_keys_to_session(target_tmux, target_cli_type, forwarded_message):
        fail_msg = t('chain.forward_failed', source=session_name, target=target_session)
        send_telegram_message(session_name, fail_msg)
        return False

    # 標記目標 session 為 busy
    _mark_session_busy(target_session)

    logger.info(f"Chain forwarded: {session_name} -> {target_session}")
    return True


def _has_pending_chain(session_name: str) -> bool:
    """檢查 session 是否有待處理的串接"""
    chain_file = os.path.join(app_config.chain.CHAIN_DIR,
                              f"{session_name}.json")
    return os.path.exists(chain_file)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: send_telegram_notification.py <session_name> <message> [--raw-file <path>]",
              file=sys.stderr)
        sys.exit(1)

    session_name = sys.argv[1]
    message = sys.argv[2]

    # 從暫存檔讀取原始回應（避免 shell ARG_MAX 限制）
    raw_response = ""
    if len(sys.argv) >= 5 and sys.argv[3] == '--raw-file':
        raw_file_path = sys.argv[4]
        try:
            with open(raw_file_path, 'r', encoding='utf-8') as f:
                raw_response = f.read()
        except OSError as e:
            logger.error(f"Failed to read raw response file: {e}")

    success = True

    # 有串接時：不發 A 的完整回應到 TG，只走串接流程（含交接通知）
    # 無串接時：正常發送到 TG
    if raw_response and _has_pending_chain(session_name):
        success = process_chain(session_name, raw_response)
    else:
        success = send_telegram_message(session_name, message)
        # 處理 .done 完成通知（最終節點）
        if raw_response:
            process_chain(session_name, raw_response)

    # 清除忙碌標記（session 已完成工作）
    _clear_session_busy(session_name)

    sys.exit(0 if success else 1)
