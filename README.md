**繁體中文** | [English](README.en.md)

# AI CLI Telegram 多會話橋接

通過 Telegram 與多個正在運行的 AI CLI 實例（Claude Code、Gemini CLI、OpenAI Codex CLI）進行雙向互動。

## 功能特性

- 🔄 **雙向通訊**：AI CLI 的輸出即時推送到 Telegram，Telegram 的訊息也能傳回 AI CLI
- 🔀 **多會話並行**：同時管理多個 AI CLI 實例（Claude Code、Gemini CLI、Codex CLI），並行執行任務
- 🏷️ **來源標記**：所有回覆都標記來源 `📍 project`，清楚辨識
- 📮 **智能路由**：使用 `#project` 語法指定目標，或 `#all` 廣播給所有會話
- 🔗 **會話串接**：`#A msg >> #B prefix` 讓 A 的回應自動轉發給 B，支援多段串接
- 🖥️ **同時操作**：可以同時在終端和 Telegram 與 Claude Code 互動
- 🤖 **Hook 即時通知**：AI CLI 完成回應時透過 Hook 即時推送（Claude: Stop, Gemini: AfterAgent, Codex: Stop），延遲 < 1 秒
- 🎯 **互動式按鈕**：確認提示自動轉換為 Inline Keyboard 按鈕
- 📋 **Plan Mode 互動**：Plan mode 期間的選項透過 tmux 輪詢自動推送到 Telegram，可直接點擊按鈕操作
- 📊 **訊息截斷**：超過 4000 字元自動截斷，避免訊息過長
- 🔒 **用戶驗證**：僅允許特定用戶使用
- ⚡ **訊息佇列**：避免衝突，訊息依序處理
- 🌐 **多語言支援**：透過 `.env` 的 `AI_BRIDGE_LANGUAGE` 設定切換繁體中文或英文介面

## 支援列表

### 支援的 AI CLI 工具

| CLI 工具 | Hook 類型 | 配置目錄 | 啟動命令 |
|----------|-----------|----------|---------|
| Claude Code | Stop | `.claude/settings.local.json` | `claude {args}` |
| Gemini CLI | AfterAgent | `.gemini/settings.json` | `gemini {args}` |
| Codex CLI | Stop | `.codex/hooks.json` | `codex {args}` |

### Telegram 命令

| 命令 | 說明 |
|------|------|
| `/start` | 顯示歡迎訊息與可用會話列表 |
| `/status` | 查看所有會話狀態（路徑、tmux、CLI 類型、Hook 狀態） |
| `/sessions` | 列出配置的會話與使用方式 |
| `/restart #session` | 終止並重建指定會話的 tmux 環境 |
| `/reload` | 熱重載 sessions.yaml 配置（無需重啟 Bot） |
| `/chain` | 查看活躍的會話串接 |
| `/chain cancel #session` | 取消指定會話的串接 |

### bridge.sh 管理命令

| 子命令 | 說明 |
|--------|------|
| `start` | 後台啟動 Bot（含配置驗證、venv 初始化） |
| `stop` | 優雅停止 Bot 並清理 hooks、tmux 會話及日誌 |
| `restart` | 重啟 Bot（先 stop 後 start） |
| `status` | 顯示 Bot 與會話運行狀態 |
| `logs [session]` | 查看 Bot 主日誌或指定會話日誌 |
| `validate` | 驗證所有配置（.env、sessions.yaml、CLI 安裝、權限） |

### 功能特性一覽

| 功能 | 說明 |
|------|------|
| 雙向通訊 | Telegram ↔ AI CLI，Hook 驅動即時推送（延遲 < 1 秒） |
| 多 CLI 支援 | Claude Code + Gemini CLI + Codex CLI，Strategy 模式抽象 |
| 多會話並行 | 同時管理多個獨立 CLI 實例 |
| 智能路由 | `#session` 指定目標、`#all` 廣播（無預設會話） |
| 會話串接 | `#A msg >> #B prefix` 自動轉發，含循環偵測和深度限制 |
| 互動按鈕 | 確認提示自動轉 Inline Keyboard |
| 訊息佇列 | 序列化處理，最大 1000 訊息 |
| 速率限制 | 每用戶 5 秒最多 3 則訊息 |
| 用戶驗證 | ALLOWED_USER_IDS 白名單，未設定拒絕啟動 |
| 訊息截斷 | 超過 4000 字元自動截斷 |
| 日誌輪替 | 超過 10MB 自動截斷至 5MB |
| 熱重載 | `/reload` 更新配置，不中斷現有會話 |
| Markdown fallback | 格式解析失敗自動改用純文字 |
| 多語言支援 | 支援繁體中文（zh-TW）和英文（en），透過 `.env` 切換 |
| Plan Mode 互動 | 自動偵測 Plan mode 選項並推送為 Telegram 按鈕 |

## 系統架構

```
                    Telegram 用戶
                         │
                    #webapp 訊息
                    #api 訊息
                    #all 訊息
                         │
                         ▼
                 ┌───────────────┐
                 │ telegram_bot  │
                 │   (路由器)    │
                 └───────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │  tmux   │    │  tmux   │    │  tmux   │
    │ webapp  │    │   api   │    │  docs   │
    └────┬────┘    └────┬────┘    └────┬────┘
         │              │              │
         ▼              ▼              ▼
    [#webapp]       [#api]         [#docs]
         │              │              │
         └──────────────┼──────────────┘
                        ▼
                    Telegram
```

## 快速開始

### 前置要求

> **重要**：本工具僅負責 Telegram ↔ CLI 的訊息轉發，不處理 CLI 登入。啟動前請確認：

1. **CLI 已登入**：在終端執行 `claude`、`gemini` 或 `codex` 確認可正常互動（非登入畫面）
2. **tmux 已安裝**：`tmux -V`
3. **Python 3.8+**：`python3 --version`

### 1. 安裝依賴

```bash
# 安裝 tmux
brew install tmux

# 安裝 Python 依賴
pip install -r requirements.txt
```

### 2. 創建 Telegram Bot

1. 在 Telegram 找到 [@BotFather](https://t.me/BotFather)
2. 發送 `/newbot` 創建 bot
3. 保存 Bot Token

### 3. 獲取 User ID

1. 在 Telegram 找到 [@userinfobot](https://t.me/userinfobot)
2. 發送 `/start`
3. 記下 User ID

### 4. 配置

**創建 .env 文件：**

```bash
cp .env.example .env
```

編輯 `.env`：

```env
TELEGRAM_BOT_TOKEN=你的_bot_token
ALLOWED_USER_IDS=你的_user_id
```

**創建 sessions.yaml 配置文件：**

```yaml
sessions:
  - name: webapp
    path: /Users/你的用戶名/project/webapp-project
    tmux: claude-webapp

  - name: api
    path: /Users/你的用戶名/project/api-server
    tmux: claude-api
```

### 5. 啟動

```bash
./bridge.sh start
./bridge.sh status
./bridge.sh stop
```

## 使用方法

### 訊息路由語法

在 Telegram 中發送訊息：

```
#webapp 查詢當前路徑          → 發送給 webapp 會話
#api 執行測試                → 發送給 api 會話
#all 生成文檔                → 發送給所有會話
#webapp 分析程式碼 >> #api 根據分析結果寫測試  → 串接：webapp 完成後自動轉發給 api
```

**注意**：必須使用 `#` 前綴指定目標會話，沒有前綴的訊息會返回錯誤並顯示可用會話列表。

### 回覆格式

所有回覆都會標記來源（Hook 驅動，即時推送）：

```
📍 webapp

這是一個房租管理系統...

📍 api

測試完成！所有測試通過。
```

### Telegram 命令

- `/start` - 顯示幫助和會話列表
- `/status` - 查看所有會話狀態
- `/sessions` - 查看會話列表
- `/restart #session` - 重啟指定會話
- `/reload` - 重新載入 sessions.yaml 配置（無需重啟 Bot）
- `/chain` - 查看活躍串接
- `/chain cancel #session` - 取消指定串接

### 會話串接

將多個 AI 會話串聯起來，前一個的回應自動轉發給下一個：

```
#webapp 分析這段程式碼的效能瓶頸 >> #api 根據分析結果進行優化
```

- 支援多段串接：`#A msg >> #B >> #C`（最多 4 次轉發）
- 含循環偵測（同一會話不可重複出現）
- 串接過期時間 1 小時

### 互動式按鈕

當 AI CLI 詢問確認時，會自動顯示按鈕：

```
[#webapp]
Do you want to proceed with editing these 3 files?
  1. Yes, proceed with edits
  2. No, cancel

[✅ 1. Yes]  [❌ 2. No]  ← 點擊按鈕自動回覆
```

### 管理命令

```bash
./bridge.sh start          # 後台啟動 Bot
./bridge.sh stop           # 停止 Bot 並清理 hooks、tmux、日誌
./bridge.sh restart        # 重啟 Bot
./bridge.sh status         # 查看 Bot 和會話狀態
./bridge.sh logs           # 查看 Bot 主日誌
./bridge.sh logs webapp    # 查看指定會話日誌
./bridge.sh validate       # 驗證配置
```

### 連接到終端

你可以隨時 attach 到 tmux 會話直接操作：

```bash
# 查看所有會話
tmux ls

# 連接到指定會話（tmux 名稱見 sessions.yaml 配置）
tmux attach -t <tmux_session_name>

# 退出但不終止（按鍵）
Ctrl+B, 然後按 D
```

## 配置說明

### sessions.yaml 格式

```yaml
sessions:
  - name: 會話名稱          # 用於 #name 路由
    path: 專案路徑          # CLI 工作目錄
    cli_type: claude        # CLI 類型（可選，claude、gemini 或 codex，預設 claude）
    tmux: tmux_會話名稱     # tmux 會話名稱（可選，預設 {cli_type}-{name}）
    cli_args: "啟動參數"     # CLI 啟動參數（可選）
```

**範例：**

```yaml
sessions:
  - name: webapp
    path: /path/to/webapp-project

  - name: api
    path: /path/to/api-server
    cli_args: "--model sonnet"

  - name: devops
    path: /path/to/infrastructure
    cli_type: gemini
    cli_args: "--yolo"

  - name: codex-app
    path: /path/to/codex-app
    cli_type: codex
    cli_args: "--model o4-mini"
```
### .env 配置

```env
TELEGRAM_BOT_TOKEN=你的_telegram_bot_token
ALLOWED_USER_IDS=user_id_1,user_id_2
AI_BRIDGE_LANGUAGE=zh-TW
```

**變數說明：**
- `TELEGRAM_BOT_TOKEN` - 必填，從 BotFather 獲取
- `ALLOWED_USER_IDS` - 必填，逗號分隔的用戶 ID（留空將拒絕啟動）
- `AI_BRIDGE_LANGUAGE` - 可選，介面語言（`zh-TW` 繁體中文 / `en` 英文，預設 `zh-TW`）。舊鍵名 `LANGUAGE` 仍可用，但與系統 gettext 環境變數同名、可能被覆蓋

## 工作原理

### 即時通知（Hook 驅動）

1. AI CLI 完成回應時觸發 hook（Claude: Stop, Gemini: AfterAgent, Codex: Stop）
2. `notify_telegram.sh` 從 hook stdin 讀取回應（Claude/Codex: `last_assistant_message`, Gemini: `prompt_response`）
3. `send_telegram_notification.py` 透過 Telegram Bot API 即時推送
4. 延遲 < 1 秒，事件驅動，回覆內容乾淨無 ANSI 碼

### 訊息路由

1. `MessageRouter` 解析 `#project` 語法
2. `SessionManager` 將訊息路由到對應會話
3. 使用 `tmux send-keys` 注入到 Claude Code
4. 支援 `#all` 廣播給所有會話

### 並行執行

- 所有會話獨立運行，互不干擾
- 每個會話有獨立的 Hook 通知
- 回覆按完成順序即時推送，附上來源標記

## 文件說明

**主程式：**
- `telegram_bot_multi.py` - Telegram Bot 主程式

**核心模組：**
- `session_manager.py` - 會話管理器
- `message_router.py` - 訊息路由器
- `tmux_bridge.py` - Tmux 橋接模組
- `config.py` - 集中配置管理
- `cli_provider.py` - CLI 抽象層（Strategy 模式，支援 Claude/Gemini/Codex）

**Hook 通知：**
- `notify_telegram.sh` - CLI Hook 腳本（Claude: Stop, Gemini: AfterAgent, Codex: Stop）
- `send_telegram_notification.py` - Telegram API 發送器

**國際化：**
- `i18n.py` - 多語言翻譯模組
- `locales/zh-TW.json` / `locales/en.json` - Python 翻譯檔
- `locales/zh-TW.sh` / `locales/en.sh` - Shell 翻譯檔

**啟動與配置：**
- `bridge.sh` - 統一管理工具（start/stop/restart/status/logs/validate）
- `sessions.yaml` - 會話配置
- `.env` - 環境變數
- `requirements.txt` - Python 依賴

## 安全建議

1. **限制用戶**：`ALLOWED_USER_IDS` 為必填項，未設定時 Bot 拒絕啟動
2. **保護配置**：`.env` 加入 `.gitignore`，不要提交敏感資訊
3. **Shell 注入防護**：所有傳入 tmux 的參數使用 `shlex.quote()` 跳脫
4. **鎖定依賴版本**：`requirements.txt` 鎖定精確版本，防止供應鏈攻擊
5. **工作目錄權限**：確保專案目錄權限正確，日誌檔案權限為 `0o600`
6. **網絡安全**：使用 Polling 模式，無需公開網址

## 故障排除

### 會話無法創建

```bash
# 檢查 tmux
which tmux

# 手動測試
tmux new -s test
```

### 無法接收輸出

```bash
# 檢查日誌文件
ls -la ~/.ai_bridge/logs/*_*.log

# 查看日誌（格式：{cli_type}_{session}.log）
tail -f ~/.ai_bridge/logs/claude_webapp.log
```

### Bot 無法啟動

```bash
# 檢查配置
cat .env
cat sessions.yaml

# 檢查 Python 模組
python3 -c "import telegram; import yaml; import requests"
```

### Hook 通知未觸發

```bash
# 檢查 hook 配置
cat /path/to/project/.claude/settings.local.json  # Claude
cat /path/to/project/.gemini/settings.json         # Gemini
cat /path/to/project/.codex/hooks.json             # Codex
cat ~/.codex/config.toml                           # Codex 功能旗標

# 檢查 hook 腳本權限
ls -la notify_telegram.sh send_telegram_notification.py

# 查看 hook 除錯日誌
cat ~/.ai_bridge/logs/hook_debug_*.log

# 查看 bot 日誌
./bridge.sh logs
```

### 訊息未送達

```bash
# 檢查 tmux 會話
tmux ls

# 在 Telegram 查看狀態
/status
```

## 常見問題

**Q: Claude Code Plan Mode 在 Telegram 如何操作？**
A: Plan mode 期間的互動選項（AskUserQuestion、ExitPlanMode）會透過 tmux 輪詢自動推送為 InlineKeyboard 按鈕。直接點擊即可選擇。文字輸入選項（✏️ 標記）選擇後需再發送 `#session 回饋內容`。

**Q: 為什麼要用 tmux？**
A: tmux 提供會話管理和日誌記錄，是實現雙向通訊的基礎。

**Q: 可以在遠程伺服器使用嗎？**
A: 可以！只要伺服器能連接 Telegram API。

**Q: 如何停止橋接？**
A: 使用管理工具一鍵停止（自動清理所有 tmux 會話）：
```bash
./bridge.sh stop
```

**Q: 如何添加新專案？**
A: 在 `sessions.yaml` 添加新配置，然後使用 `/reload` 命令熱重載配置，無需重啟 Bot。

**Q: 會話出現問題如何重啟？**
A: 使用 `/restart #session` 命令重啟指定會話，例如 `/restart #webapp`。這會終止舊的 tmux 會話並創建新的會話。

**Q: 修改配置後需要重啟 Bot 嗎？**
A: 不需要！使用 `/reload` 命令即可熱重載 `sessions.yaml`，系統會自動添加新會話、移除舊會話，並保持現有會話運行。

**Q: 什麼是會話串接？**
A: 使用 `>>` 語法將多個會話串聯：`#webapp 分析程式碼 >> #api 寫測試`。webapp 完成分析後，其回應會自動轉發給 api，附帶「寫測試」的前綴指示。用 `/chain` 查看進度，`/chain cancel #session` 取消。

## 完整移除

如果要完全移除此專案，請按照以下順序操作。**直接刪除專案資料夾而不清理 hooks 會導致 Claude Code / Gemini CLI / Codex CLI 每次回應結束時 hook 報錯。**

### 1. 停止服務

```bash
./bridge.sh stop    # 停止 bot、清理 tmux 會話、刪除 PID 和日誌
```

### 2. 清理各專案的 Hook 配置

啟動時 bot 會將 hook 寫入 `sessions.yaml` 中每個專案的配置檔。你需要手動移除這些 hook 條目：

**Claude 專案** — 編輯 `{專案路徑}/.claude/settings.local.json`，移除 `hooks.Stop` 中包含 `notify_telegram.sh` 的條目：

```bash
# 檢查哪些專案有 hook
grep -rl "notify_telegram" /path/to/project/.claude/settings.local.json
```

**Gemini 專案** — 編輯 `{專案路徑}/.gemini/settings.json`，移除 `hooks.AfterAgent` 中包含 `notify_telegram.sh` 的條目。

**Codex 專案** — 編輯 `{專案路徑}/.codex/hooks.json`，移除 `hooks.Stop` 中包含 `notify_telegram.sh` 的條目。

### 3. 清理信任目錄設定（如有使用 Gemini 或 Codex）

- **Gemini**：編輯 `~/.gemini/trustedFolders.json`，移除由此 bot 添加的路徑條目。
- **Codex**：編輯 `~/.codex/config.toml`，移除 `[projects."..."]` 區塊中由此 bot 添加的信任目錄。

### 4. 刪除系統目錄

```bash
rm -rf ~/.ai_bridge    # 日誌和 PID 檔案
```

### 5. 刪除專案目錄

```bash
rm -rf /path/to/ai_bridge
```

### 6. 確認無殘留 tmux 會話

```bash
tmux ls    # 檢查是否有殘留的 claude-*、gemini-* 或 codex-* 會話
tmux kill-session -t <會話名稱>    # 如有殘留，逐一清除
```

## 授權

MIT License

## 相關連結

- [Claude Code 官方文檔](https://docs.claude.com/claude-code)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot](https://python-telegram-bot.readthedocs.io/)
- [tmux](https://github.com/tmux/tmux/wiki)