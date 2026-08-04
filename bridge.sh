#!/bin/bash
# AI CLI Telegram Bridge - 統一管理工具
# 用法: ./bridge.sh {start|stop|restart|status|logs|validate}

set -euo pipefail

# === 路徑常數 ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export _BRIDGE_SCRIPT_DIR="$SCRIPT_DIR"
BRIDGE_DIR="${HOME}/.ai_bridge"
LOG_DIR="${BRIDGE_DIR}/logs"
PID_FILE="${BRIDGE_DIR}/bridge.pid"
BOT_LOG="${LOG_DIR}/bot.log"
VENV_DIR="${SCRIPT_DIR}/venv"

# === 語言載入 ===
load_language() {
    local lang="zh-TW"
    if [ -f "$SCRIPT_DIR/.env" ]; then
        local env_lang
        # 暫時關閉 pipefail，避免 grep 找不到時退出
        # 優先讀 AI_BRIDGE_LANGUAGE，舊鍵 LANGUAGE 向後相容
        set +o pipefail
        env_lang=$(grep -E '^AI_BRIDGE_LANGUAGE=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
        [ -z "$env_lang" ] && env_lang=$(grep -E '^LANGUAGE=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
        set -o pipefail
        [ -n "$env_lang" ] && lang="$env_lang"
    fi

    local lang_file="$SCRIPT_DIR/locales/${lang}.sh"
    if [ -f "$lang_file" ]; then
        source "$lang_file"
    else
        source "$SCRIPT_DIR/locales/zh-TW.sh"
    fi
}

load_language

# === 顏色輸出 ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; }
step()  { echo -e "${BLUE}▶${NC} $1"; }

# === 初始化目錄 ===
init_dirs() {
    mkdir -p "$LOG_DIR"
}

# === PID 管理 ===
get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    fi
}

is_running() {
    local pid
    pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

# === 配置驗證 ===
do_validate() {
    echo "$MSG_VALIDATING"
    echo ""

    local errors=0

    # 優先使用 venv 的 Python（有依賴）
    local PYTHON="python3"
    if [ -x "$VENV_DIR/bin/python3" ]; then
        PYTHON="$VENV_DIR/bin/python3"
    fi

    # 0. Python 版本（cli_provider.py 使用 tomllib，需 ≥ 3.11）
    local py_version
    py_version=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")
    if [ -z "$py_version" ]; then
        error "$MSG_PYTHON_NOT_FOUND"
        errors=$((errors + 1))
    elif ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        error "$(printf "$MSG_PYTHON_TOO_OLD" "$py_version")"
        errors=$((errors + 1))
    else
        info "$(printf "$MSG_PYTHON_OK" "$py_version")"
    fi

    # 1. .env 存在
    if [ -f "$SCRIPT_DIR/.env" ]; then
        info "$MSG_ENV_EXISTS"

        # 收緊 .env 權限（含 Bot Token，避免同機其他使用者可讀）
        local env_perms
        env_perms=$(stat -f "%Lp" "$SCRIPT_DIR/.env" 2>/dev/null || stat -c "%a" "$SCRIPT_DIR/.env" 2>/dev/null || echo "")
        if [ -n "$env_perms" ] && [ "$env_perms" != "600" ]; then
            chmod 600 "$SCRIPT_DIR/.env" 2>/dev/null || true
            warn "$MSG_ENV_PERMS_TIGHTENED"
        fi

        # 檢查 TELEGRAM_BOT_TOKEN
        local token
        set +o pipefail
        token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
        set -o pipefail
        if [ -z "$token" ] || [ "$token" = "your_bot_token_here" ]; then
            error "$MSG_TOKEN_NOT_SET"
            errors=$((errors + 1))
        else
            info "$MSG_TOKEN_SET"
        fi

        # 檢查 ALLOWED_USER_IDS（必填，bot 啟動時空白會直接退出）
        local user_ids
        set +o pipefail
        user_ids=$(grep -E '^ALLOWED_USER_IDS=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
        set -o pipefail
        if [ -z "$user_ids" ]; then
            error "$MSG_USER_IDS_NOT_SET"
            errors=$((errors + 1))
        elif ! echo "$user_ids" | grep -Eq '^[0-9]+( *, *[0-9]+)*$'; then
            warn "$(printf "$MSG_USER_IDS_INVALID" "$user_ids")"
        else
            info "$MSG_USER_IDS_SET"
        fi

        # 檢查語言設定（AI_BRIDGE_LANGUAGE 優先，舊鍵 LANGUAGE 向後相容）
        set +o pipefail
        local lang_val
        lang_val=$(grep -E '^AI_BRIDGE_LANGUAGE=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
        [ -z "$lang_val" ] && lang_val=$(grep -E '^LANGUAGE=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
        set -o pipefail
        if [ -z "$lang_val" ]; then
            warn "$MSG_LANGUAGE_NOT_SET"
        elif [ "$lang_val" != "zh-TW" ] && [ "$lang_val" != "en" ]; then
            warn "$(printf "$MSG_LANGUAGE_INVALID" "$lang_val")"
        else
            info "$(printf "$MSG_LANGUAGE_SET" "$lang_val")"
        fi
    else
        error "$MSG_ENV_NOT_EXISTS"
        errors=$((errors + 1))
    fi

    # 2. sessions.yaml 存在且有效
    if [ -f "$SCRIPT_DIR/sessions.yaml" ]; then
        info "$MSG_SESSIONS_EXISTS"

        # 檢查是否有配置的會話
        local session_count
        session_count=$($PYTHON -c "
import yaml, sys, os
try:
    with open(os.environ['_BRIDGE_SCRIPT_DIR'] + '/sessions.yaml') as f:
        c = yaml.safe_load(f)
    sessions = c.get('sessions', []) if c else []
    print(len(sessions))
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    print(0)
" 2>/dev/null)

        if [ "$session_count" -gt 0 ] 2>/dev/null; then
            info "$(printf "$MSG_SESSIONS_FOUND" "$session_count")"
        else
            error "$MSG_SESSIONS_EMPTY"
            errors=$((errors + 1))
        fi

        # 檢查每個會話路徑是否存在
        local path_results
        path_results=$($PYTHON -c "
import yaml, os
with open(os.environ['_BRIDGE_SCRIPT_DIR'] + '/sessions.yaml') as f:
    c = yaml.safe_load(f)
for s in (c.get('sessions', []) if c else []):
    name = s.get('name', '?')
    path = s.get('path', '')
    if os.path.isdir(path):
        print(f'OK:{name}:{path}')
    else:
        print(f'FAIL:{name}:{path}')
" 2>/dev/null)

        while IFS=: read -r status name path; do
            if [ "$status" = "OK" ]; then
                info "$(printf "$MSG_SESSION_PATH_OK" "$name" "$path")"
            else
                error "$(printf "$MSG_SESSION_PATH_FAIL" "$name" "$path")"
                errors=$((errors + 1))
            fi
        done <<< "$path_results"
    else
        error "$MSG_SESSIONS_NOT_EXISTS"
        errors=$((errors + 1))
    fi

    # 3. tmux 已安裝
    if command -v tmux &>/dev/null; then
        info "$(printf "$MSG_TMUX_INSTALLED" "$(tmux -V)")"
    else
        error "$MSG_TMUX_NOT_INSTALLED"
        errors=$((errors + 1))
    fi

    # 4. CLI 已安裝（根據 sessions.yaml 中配置的 cli_type 動態檢查）
    local cli_types
    cli_types=$($PYTHON -c "
import yaml, sys, os
try:
    with open(os.environ['_BRIDGE_SCRIPT_DIR'] + '/sessions.yaml') as f:
        c = yaml.safe_load(f)
    types = set()
    for s in (c.get('sessions', []) if c else []):
        types.add(s.get('cli_type', 'claude'))
    for t in sorted(types):
        print(t)
except Exception:
    print('claude')
" 2>/dev/null)

    while IFS= read -r cli_type; do
        [ -z "$cli_type" ] && continue
        if command -v "$cli_type" &>/dev/null; then
            info "$(printf "$MSG_CLI_INSTALLED" "$cli_type")"
            # 版本檢查確認 CLI 可正常執行
            # || true 避免直接執行 ./bridge.sh validate 時 errexit 導致腳本靜默中止
            cli_version=$("$cli_type" --version 2>/dev/null) || true
            if [ -n "$cli_version" ]; then
                info "$(printf "$MSG_CLI_VERSION" "$cli_type" "$cli_version")"
            else
                warn "$(printf "$MSG_CLI_NO_VERSION" "$cli_type")"
            fi
            echo ""
            echo -e "  ${YELLOW}┌─────────────────────────────────────────────────────┐${NC}"
            echo -e "  ${YELLOW}│${NC} $(printf "$MSG_CLI_LOGIN_NOTICE_LINE1" "$cli_type")               ${YELLOW}│${NC}"
            echo -e "  ${YELLOW}│${NC}    $(printf "$MSG_CLI_LOGIN_NOTICE_LINE2" "$cli_type")            ${YELLOW}│${NC}"
            echo -e "  ${YELLOW}│${NC}    $MSG_CLI_LOGIN_NOTICE_LINE3                           ${YELLOW}│${NC}"
            echo -e "  ${YELLOW}└─────────────────────────────────────────────────────┘${NC}"
            echo ""
        else
            error "$(printf "$MSG_CLI_NOT_INSTALLED" "$cli_type")"
            errors=$((errors + 1))
        fi
    done <<< "$cli_types"

    # 5. 腳本權限
    if [ -x "$SCRIPT_DIR/notify_telegram.sh" ]; then
        info "$MSG_NOTIFY_EXECUTABLE"
    else
        warn "$MSG_NOTIFY_NOT_EXECUTABLE"
    fi

    if [ -x "$SCRIPT_DIR/send_telegram_notification.py" ]; then
        info "$MSG_SEND_EXECUTABLE"
    else
        warn "$MSG_SEND_NOT_EXECUTABLE"
    fi

    # 6. Python 依賴
    if [ -d "$VENV_DIR" ]; then
        info "$MSG_VENV_EXISTS"
        if "$VENV_DIR/bin/python3" -c "import telegram; import yaml; import requests; import dotenv" 2>/dev/null; then
            info "$MSG_DEPS_INSTALLED"
        else
            warn "$MSG_DEPS_INCOMPLETE"
        fi
    else
        warn "$MSG_VENV_NOT_EXISTS"
    fi

    # 7. 日誌目錄
    if [ -d "$LOG_DIR" ]; then
        info "$(printf "$MSG_LOG_DIR_EXISTS" "$LOG_DIR")"
    else
        info "$(printf "$MSG_LOG_DIR_WILL_CREATE" "$LOG_DIR")"
    fi

    echo ""
    if [ "$errors" -gt 0 ]; then
        error "$(printf "$MSG_VALIDATE_ERRORS" "$errors")"
        return 1
    else
        info "$MSG_VALIDATE_OK"
        return 0
    fi
}

# === 啟動 ===
do_start() {
    if is_running; then
        local pid
        pid=$(get_pid)
        warn "$(printf "$MSG_ALREADY_RUNNING" "$pid")"
        return 1
    fi

    step "$MSG_STEP_VALIDATE"
    if ! do_validate; then
        return 1
    fi

    echo ""
    step "$MSG_STEP_INIT"

    # 遷移舊目錄（一次性）
    if [ -d "$HOME/.claude_bridge" ] && [ ! -d "$HOME/.ai_bridge" ]; then
        mv "$HOME/.claude_bridge" "$HOME/.ai_bridge"
        info "$MSG_MIGRATED"
    fi

    init_dirs

    # 確保虛擬環境存在
    if [ ! -d "$VENV_DIR" ]; then
        step "$MSG_STEP_CREATE_VENV"
        python3 -m venv "$VENV_DIR"
    fi

    # 啟動虛擬環境並安裝依賴
    source "$VENV_DIR/bin/activate"
    if ! python3 -c "import telegram; import yaml; import requests; import dotenv" 2>/dev/null; then
        step "$MSG_STEP_INSTALL_DEPS"
        pip3 install -q -r "$SCRIPT_DIR/requirements.txt"
    fi

    # 確保腳本有執行權限
    chmod +x "$SCRIPT_DIR/notify_telegram.sh" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/send_telegram_notification.py" 2>/dev/null || true

    # 收緊 .env 權限（含 Bot Token）
    chmod 600 "$SCRIPT_DIR/.env" 2>/dev/null || true

    # 載入環境變數
    set -a
    source "$SCRIPT_DIR/.env"
    set +a

    # 後台啟動 bot（umask 077 讓 bot.log 與 bot 建立的檔案僅擁有者可讀）
    step "$MSG_STEP_START_BOT"
    cd "$SCRIPT_DIR"
    umask 077
    touch "$BOT_LOG" && chmod 600 "$BOT_LOG" 2>/dev/null || true
    nohup "$VENV_DIR/bin/python3" telegram_bot_multi.py >> "$BOT_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    # 等待確認啟動
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        echo ""
        info "$(printf "$MSG_BOT_STARTED" "$pid")"
        info "$(printf "$MSG_BOT_LOG" "$BOT_LOG")"
        info "$MSG_BOT_STATUS_HINT"
        info "$MSG_BOT_STOP_HINT"
    else
        error "$(printf "$MSG_BOT_START_FAILED" "$BOT_LOG")"
        rm -f "$PID_FILE"
        tail -20 "$BOT_LOG" 2>/dev/null
        return 1
    fi
}

# === 清理執行期殘留檔案（日誌、chain、status）===
cleanup_runtime_files() {
    # 清理日誌
    step "$MSG_STEP_CLEANUP_LOGS"
    find "$LOG_DIR" -name "*_*.log" -delete 2>/dev/null || true
    find "$LOG_DIR" -name "hook_debug_*.log" -delete 2>/dev/null || true

    # 清理 chain 和 status 殘留檔案（避免重啟後意外觸發轉發）
    rm -f "${HOME}/.ai_bridge/chains/"*.json 2>/dev/null || true
    rm -f "${HOME}/.ai_bridge/chains/"*.done 2>/dev/null || true
    rm -f "${HOME}/.ai_bridge/chains/"*.claimed.* 2>/dev/null || true
    rm -f "${HOME}/.ai_bridge/status/"*.busy 2>/dev/null || true
}

# === 停止 ===
do_stop() {
    if ! is_running; then
        warn "$MSG_NOT_RUNNING"
        # 清理可能殘留的 PID 檔案
        rm -f "$PID_FILE"
        # 仍然清理 hooks、tmux 會話與殘留檔案（bot 崩潰後 chain 檔可能觸發非預期轉發）
        cleanup_hooks
        cleanup_tmux
        cleanup_runtime_files
        return 0
    fi

    local pid
    pid=$(get_pid)

    step "$(printf "$MSG_STEP_STOP" "$pid")"

    # 發送 SIGTERM（|| true 避免進程剛好退出時 errexit 中斷後續清理）
    kill "$pid" 2>/dev/null || true

    # 等待進程退出（最多 10 秒）
    local count=0
    while [ $count -lt 10 ] && kill -0 "$pid" 2>/dev/null; do
        sleep 1
        count=$((count + 1))
    done

    # 如果還沒退出，強制終止
    if kill -0 "$pid" 2>/dev/null; then
        warn "$MSG_FORCE_KILL"
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi

    # 清理 PID 檔案
    rm -f "$PID_FILE"

    # 清理 hooks
    cleanup_hooks

    # 清理 tmux 會話
    cleanup_tmux

    # 清理日誌與 chain/status 殘留檔案
    cleanup_runtime_files

    info "$MSG_BOT_STOPPED"
}

# === 獲取配置的 tmux 會話名稱列表 ===
get_configured_tmux_sessions() {
    local PYTHON="python3"
    if [ -x "$VENV_DIR/bin/python3" ]; then
        PYTHON="$VENV_DIR/bin/python3"
    fi

    if [ -f "$SCRIPT_DIR/sessions.yaml" ]; then
        $PYTHON -c "
import yaml, os
with open(os.environ['_BRIDGE_SCRIPT_DIR'] + '/sessions.yaml') as f:
    c = yaml.safe_load(f)
for s in (c.get('sessions', []) if c else []):
    name = s.get('name', '')
    cli_type = s.get('cli_type', 'claude')
    prefix = f'{cli_type}-'
    tmux = s.get('tmux', f'{prefix}{name}')
    print(tmux)
" 2>/dev/null
    fi
}

# === 清理 hooks ===
cleanup_hooks() {
    local PYTHON="python3"
    if [ -x "$VENV_DIR/bin/python3" ]; then
        PYTHON="$VENV_DIR/bin/python3"
    fi

    if [ -f "$SCRIPT_DIR/sessions.yaml" ]; then
        step "$MSG_STEP_CLEANUP_HOOKS"
        $PYTHON -c "
import yaml, json, os
from pathlib import Path

with open(os.environ['_BRIDGE_SCRIPT_DIR'] + '/sessions.yaml') as f:
    c = yaml.safe_load(f)

for s in (c.get('sessions', []) if c else []):
    path = s.get('path', '')
    cli_type = s.get('cli_type', 'claude')
    if not path:
        continue

    hook_map = {
        'gemini': ('.gemini/settings.json', 'AfterAgent'),
        'codex': ('.codex/hooks.json', 'Stop'),
    }
    if cli_type in hook_map:
        rel_path, hook_key = hook_map[cli_type]
        sf = Path(path) / rel_path
    else:
        sf = Path(path) / '.claude' / 'settings.local.json'
        hook_key = 'Stop'

    if not sf.exists():
        continue

    try:
        with open(sf, 'r') as f:
            settings = json.load(f)
        # 只移除 bridge 建立的 entry（command 含 TELEGRAM_SESSION_NAME=），
        # 保留使用者自己的同名 hooks
        hooks = settings.get('hooks')
        entries = hooks.get(hook_key) if isinstance(hooks, dict) else None
        if isinstance(entries, list):
            remaining = [
                e for e in entries
                if not (isinstance(e, dict) and any(
                    'TELEGRAM_SESSION_NAME=' in h.get('command', '')
                    for h in e.get('hooks', []) if isinstance(h, dict)))
            ]
            if len(remaining) != len(entries):
                if remaining:
                    settings['hooks'][hook_key] = remaining
                else:
                    del settings['hooks'][hook_key]
                    if not settings['hooks']:
                        del settings['hooks']
                with open(sf, 'w') as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                print(f'  removed {hook_key} hook: {path}')
    except Exception as e:
        print(f'  warning: {e}')
" 2>/dev/null
    fi
}

# === 清理 tmux 會話 ===
cleanup_tmux() {
    local configured
    configured=$(get_configured_tmux_sessions)

    if [ -z "$configured" ]; then
        return
    fi

    step "$MSG_STEP_CLEANUP_TMUX"
    while IFS= read -r session; do
        if tmux has-session -t "$session" 2>/dev/null; then
            tmux kill-session -t "$session" 2>/dev/null && \
                info "$(printf "$MSG_TMUX_KILLED" "$session")" || true
        fi
    done <<< "$configured"
}

# === 重啟 ===
do_restart() {
    step "$MSG_STEP_RESTART"
    do_stop
    echo ""
    sleep 1
    do_start
}

# === 狀態 ===
do_status() {
    echo "$MSG_STATUS_TITLE"
    echo ""

    # Bot 進程狀態
    if is_running; then
        local pid
        pid=$(get_pid)
        info "$(printf "$MSG_BOT_RUNNING" "$pid")"

        # 顯示運行時間
        local uptime
        uptime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
        if [ -n "$uptime" ]; then
            printf "$MSG_UPTIME\n" "$uptime"
        fi
    else
        error "$MSG_BOT_NOT_RUNNING"
    fi

    echo ""

    # tmux 會話狀態
    echo "$MSG_TMUX_SESSIONS_TITLE"
    local session_info has_active=false
    local PYTHON="python3"
    [ -x "$VENV_DIR/bin/python3" ] && PYTHON="$VENV_DIR/bin/python3"

    session_info=$($PYTHON -c "
import yaml, os
try:
    with open(os.environ['_BRIDGE_SCRIPT_DIR'] + '/sessions.yaml') as f:
        c = yaml.safe_load(f)
    for s in (c.get('sessions', []) if c else []):
        name = s.get('name', '')
        cli_type = s.get('cli_type', 'claude')
        prefix = f'{cli_type}-'
        tmux = s.get('tmux', f'{prefix}{name}')
        print(f'{tmux}:{name}')
except Exception:
    pass
" 2>/dev/null)

    if [ -n "$session_info" ]; then
        while IFS=: read -r tmux_name session_name; do
            if tmux has-session -t "$tmux_name" 2>/dev/null; then
                printf "$MSG_TMUX_SESSION_ACTIVE\n" "$tmux_name" "$session_name"
                has_active=true
            else
                printf "$MSG_TMUX_SESSION_INACTIVE\n" "$tmux_name" "$session_name"
            fi
        done <<< "$session_info"
    fi
    if [ "$has_active" = false ]; then
        echo "$MSG_NO_ACTIVE_SESSIONS"
    fi

    echo ""

    # 日誌文件
    echo "$MSG_LOG_FILES_TITLE"
    if [ -d "$LOG_DIR" ]; then
        local log_files
        log_files=$(ls -la "$LOG_DIR"/*.log 2>/dev/null || true)
        if [ -n "$log_files" ]; then
            while IFS= read -r line; do
                echo "   ${line}"
            done <<< "$log_files"
        else
            echo "$MSG_NO_LOG_FILES"
        fi
    else
        echo "$MSG_NO_LOG_DIR"
    fi
}

# === 日誌 ===
do_logs() {
    local session="${1:-}"

    if [ -z "$session" ]; then
        # 查看 bot 主日誌
        if [ -f "$BOT_LOG" ]; then
            step "$(printf "$MSG_VIEWING_BOT_LOG" "$BOT_LOG")"
            tail -f "$BOT_LOG"
        else
            error "$(printf "$MSG_BOT_LOG_NOT_EXISTS" "$BOT_LOG")"
        fi
    else
        # 查看指定會話日誌
        session="${session#\#}" # 移除可能的 # 前綴
        # 動態查找會話日誌（支援不同 cli_type 前綴）
        local session_log
        session_log=$(ls "$LOG_DIR"/*_"${session}".log 2>/dev/null | head -1)
        if [ -n "$session_log" ] && [ -f "$session_log" ]; then
            step "$(printf "$MSG_VIEWING_SESSION_LOG" "$session_log")"
            tail -f "$session_log"
        else
            error "$(printf "$MSG_SESSION_LOG_NOT_EXISTS" "$session")"
            echo "$MSG_AVAILABLE_LOGS"
            ls "$LOG_DIR"/*_*.log 2>/dev/null || echo "$MSG_NO_LOGS"
        fi
    fi
}

# === 使用說明 ===
usage() {
    echo "$MSG_USAGE_TITLE"
    echo ""
    printf "$MSG_USAGE_LINE\n" "$(basename "$0")"
    echo ""
    echo "$MSG_USAGE_COMMANDS"
    echo "$MSG_USAGE_START"
    echo "$MSG_USAGE_STOP"
    echo "$MSG_USAGE_RESTART"
    echo "$MSG_USAGE_STATUS"
    echo "$MSG_USAGE_LOGS"
    echo "$MSG_USAGE_VALIDATE"
    echo ""
    echo "$MSG_USAGE_EXAMPLES"
    printf "$MSG_USAGE_EXAMPLE_START\n" "$(basename "$0")"
    printf "$MSG_USAGE_EXAMPLE_LOGS\n" "$(basename "$0")"
    printf "$MSG_USAGE_EXAMPLE_STATUS\n" "$(basename "$0")"
}

# === 主程式 ===
main() {
    local command="${1:-}"
    shift || true

    case "$command" in
        start)    do_start ;;
        stop)     do_stop ;;
        restart)  do_restart ;;
        status)   do_status ;;
        logs)     do_logs "$@" ;;
        validate) do_validate ;;
        *)        usage ;;
    esac
}

main "$@"
