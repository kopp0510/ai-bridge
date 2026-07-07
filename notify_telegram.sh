#!/bin/bash

# Hook script for Claude Code to send notifications to Telegram
# Called by Claude Code's Stop hook when Claude finishes responding
#
# stdin JSON 包含：session_id, transcript_path, last_assistant_message 等
# 環境變數：TELEGRAM_SESSION_NAME（由 command 前綴傳入）

set -euo pipefail

# 收緊本腳本建立的檔案權限（debug log、暫存檔可能含 AI 回應內容）
umask 077

# 讀取 hook 輸入（JSON）
INPUT=$(cat)

# 獲取腳本目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 優先使用 venv 的 Python（含 dotenv、requests 依賴）
PYTHON="python3"
if [ -x "$SCRIPT_DIR/venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python3"
fi

# 日誌目錄
LOG_DIR="${HOME}/.ai_bridge/logs"
mkdir -p "$LOG_DIR"

# Debug logging
DEBUG_LOG="${LOG_DIR}/hook_debug_${TELEGRAM_SESSION_NAME:-unknown}.log"

log_debug() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$DEBUG_LOG"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >> "$DEBUG_LOG"
    echo "Error: $1" >&2
}

log_debug "Hook triggered"
log_debug "Input length: ${#INPUT}"

# 載入 .env 環境變數（使用 grep + cut 正確處理值中的 = 號）
if [ -f "$SCRIPT_DIR/.env" ]; then
    _token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$SCRIPT_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")
    [ -n "$_token" ] && export TELEGRAM_BOT_TOKEN="$_token"

    _user_ids=$(grep -E '^ALLOWED_USER_IDS=' "$SCRIPT_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")
    [ -n "$_user_ids" ] && export ALLOWED_USER_IDS="$_user_ids"
    unset _token _user_ids
fi

# 驗證必要變數
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    log_error "Missing TELEGRAM_BOT_TOKEN"
    exit 1
fi

if [ -z "${TELEGRAM_SESSION_NAME:-}" ]; then
    log_error "Missing TELEGRAM_SESSION_NAME"
    exit 1
fi

# 從 stdin JSON 提取訊息
# Claude: 使用 last_assistant_message
# Gemini: 使用 prompt_response
# Fallback: transcript 解析
LAST_MESSAGE=$(echo "$INPUT" | $PYTHON -c "
import sys, json

try:
    data = json.load(sys.stdin)

    # 方法 1：Claude — last_assistant_message
    msg = data.get('last_assistant_message', '')
    if msg and msg.strip():
        print(msg.strip())
        sys.exit(0)

    # 方法 2：Gemini — prompt_response
    msg = data.get('prompt_response', '')
    if msg and msg.strip():
        print(msg.strip())
        sys.exit(0)

    # 方法 3：Fallback — 從 transcript 解析
    transcript_path = data.get('transcript_path', '')
    if not transcript_path:
        sys.exit(0)

    import os
    # 支援 .json 和 .jsonl 格式
    if not os.path.isfile(transcript_path):
        sys.exit(0)

    with open(transcript_path, 'r', encoding='utf-8') as f:
        if transcript_path.endswith('.jsonl'):
            # JSONL 格式：每行一個 JSON
            lines = f.readlines()
            messages = []
            for line in lines:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
        else:
            # JSON 格式
            tdata = json.load(f)
            messages = tdata.get('messages', [])

    # 找最後的 assistant 訊息
    for m in reversed(messages):
        if m.get('role') == 'assistant':
            content = m.get('content', [])
            texts = []
            for c in content:
                if c.get('type') == 'text':
                    t = c.get('text', '').strip()
                    if t:
                        texts.append(t)
            if texts:
                print('\n\n'.join(texts))
                sys.exit(0)

except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>>"$DEBUG_LOG")

log_debug "Extracted message length: ${#LAST_MESSAGE}"

if [ -z "$LAST_MESSAGE" ]; then
    log_debug "No message to send, exiting quietly"
    # Gemini hooks 仍需要 stdout JSON
    if [ "${TELEGRAM_CLI_TYPE:-}" = "gemini" ]; then
        echo '{}'
    fi
    exit 0
fi

# 格式化並發送到 Telegram
FORMATTED_MESSAGE="📍 *${TELEGRAM_SESSION_NAME}*

${LAST_MESSAGE}"

log_debug "Sending to Telegram..."

# 將原始回應寫入暫存檔（避免 shell ARG_MAX 限制）
# 注意：X 必須在模板結尾，否則 macOS mktemp 不會隨機化，併發 hook 會共用同一檔案
RAW_RESPONSE_FILE=$(mktemp "${TMPDIR:-/tmp}/ai_bridge_raw_XXXXXX")
printf '%s' "$LAST_MESSAGE" > "$RAW_RESPONSE_FILE"
trap 'rm -f "$RAW_RESPONSE_FILE"' EXIT

if $PYTHON "$SCRIPT_DIR/send_telegram_notification.py" "$TELEGRAM_SESSION_NAME" "$FORMATTED_MESSAGE" --raw-file "$RAW_RESPONSE_FILE"; then
    log_debug "Successfully sent to Telegram"
else
    log_error "Failed to send to Telegram"
    # Gemini hooks 仍需要 stdout JSON，即使發送失敗
    if [ "${TELEGRAM_CLI_TYPE:-}" = "gemini" ]; then
        echo '{}'
    fi
    exit 1
fi

# Gemini hooks 要求 stdout 必須是有效 JSON，否則會破壞解析
if [ "${TELEGRAM_CLI_TYPE:-}" = "gemini" ]; then
    echo '{}'
fi
