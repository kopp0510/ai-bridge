[繁體中文](README.md) | **English**

# AI CLI Telegram Multi-Session Bridge

Interact bidirectionally with multiple running AI CLI instances (Claude Code, Gemini CLI, OpenAI Codex CLI) via Telegram.

## Features

- 🔄 **Bidirectional Communication**: AI CLI output is pushed to Telegram in real-time; Telegram messages are sent back to AI CLI
- 🔀 **Multi-Session Parallel**: Manage multiple AI CLI instances (Claude Code, Gemini CLI, Codex CLI) simultaneously, running tasks in parallel
- 🏷️ **Source Tagging**: All replies are tagged with source `📍 project` for clear identification
- 📮 **Smart Routing**: Use `#project` syntax to target specific sessions, or `#all` to broadcast to all
- 🔗 **Session Chaining**: `#A msg >> #B prefix` automatically forwards A's response to B, supports multi-step chains
- 🖥️ **Concurrent Access**: Interact with Claude Code from both terminal and Telegram at the same time
- 🤖 **Hook-Based Notifications**: Instant push when AI CLI finishes responding via hooks (Claude: Stop, Gemini: AfterAgent, Codex: Stop), latency < 1 second
- 🎯 **Interactive Buttons**: Confirmation prompts are automatically converted to Inline Keyboard buttons
- 📋 **Plan Mode Interaction**: Plan mode options are auto-detected via tmux polling and pushed to Telegram as clickable buttons
- 📊 **Message Truncation**: Messages over 4000 characters are automatically truncated
- 🔒 **User Authentication**: Only authorized users can access the bot
- ⚡ **Message Queue**: Sequential processing to avoid conflicts
- 🌐 **Multi-Language**: Switch between Traditional Chinese and English via `AI_BRIDGE_LANGUAGE` in `.env`

## Support Matrix

### Supported AI CLI Tools

| CLI Tool | Hook Type | Config Path | Launch Command |
|----------|-----------|-------------|---------------|
| Claude Code | Stop | `.claude/settings.local.json` | `claude {args}` |
| Gemini CLI | AfterAgent | `.gemini/settings.json` | `gemini {args}` |
| Codex CLI | Stop | `.codex/hooks.json` | `codex {args}` |

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message and available sessions |
| `/status` | View all session status (path, tmux, CLI type, Hook status) |
| `/sessions` | List configured sessions and usage |
| `/restart #session` | Terminate and recreate a session's tmux environment |
| `/reload` | Hot-reload sessions.yaml configuration (no bot restart needed) |
| `/chain` | View active session chains |
| `/chain cancel #session` | Cancel a session's chain |

### bridge.sh Management Commands

| Subcommand | Description |
|------------|-------------|
| `start` | Start bot in background (with config validation, venv init) |
| `stop` | Gracefully stop bot and clean up hooks, tmux sessions and logs |
| `restart` | Restart bot (stop then start) |
| `status` | Show bot and session running status |
| `logs [session]` | View bot main log or specific session log |
| `validate` | Validate all configs (.env, sessions.yaml, CLI installation, permissions) |

### Feature Overview

| Feature | Description |
|---------|-------------|
| Bidirectional Communication | Telegram ↔ AI CLI, Hook-driven instant push (latency < 1s) |
| Multi-CLI Support | Claude Code + Gemini CLI + Codex CLI, Strategy pattern abstraction |
| Multi-Session Parallel | Manage multiple independent CLI instances simultaneously |
| Smart Routing | `#session` targeting, `#all` broadcast (no default session) |
| Session Chaining | `#A msg >> #B prefix` auto-forward with cycle detection and depth limit |
| Interactive Buttons | Confirmation prompts auto-converted to Inline Keyboard |
| Message Queue | Sequential processing, max 1000 messages |
| Rate Limiting | Max 3 messages per user per 5 seconds |
| User Authentication | ALLOWED_USER_IDS whitelist, refuses to start if unset |
| Message Truncation | Auto-truncate messages over 4000 characters |
| Log Rotation | Auto-truncate logs over 10MB to 5MB |
| Hot Reload | `/reload` updates config without interrupting existing sessions |
| Markdown Fallback | Auto-retry with plain text when Markdown parsing fails |
| Multi-Language | Supports Traditional Chinese (zh-TW) and English (en) via `.env` |
| Plan Mode Interaction | Auto-detect plan mode options and push as Telegram buttons |

## System Architecture

```
                    Telegram User
                         │
                    #webapp message
                    #api message
                    #all message
                         │
                         ▼
                 ┌───────────────┐
                 │ telegram_bot  │
                 │   (router)    │
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

## Quick Start

### Prerequisites

> **Important**: This tool only bridges messages between Telegram and CLI — it does NOT handle CLI login. Before starting, make sure:

1. **CLI is logged in**: Run `claude`, `gemini`, or `codex` in terminal and confirm it works interactively (not a login screen)
2. **tmux is installed**: `tmux -V`
3. **Python 3.8+**: `python3 --version`

### 1. Install Dependencies

```bash
# Install tmux
brew install tmux

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Create a Telegram Bot

1. Find [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` to create a bot
3. Save the Bot Token

### 3. Get Your User ID

1. Find [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send `/start`
3. Note your User ID

### 4. Configuration

**Create .env file:**

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
ALLOWED_USER_IDS=your_user_id
```

**Create sessions.yaml configuration:**

```yaml
sessions:
  - name: webapp
    path: /Users/your_username/project/webapp-project
    tmux: claude-webapp

  - name: api
    path: /Users/your_username/project/api-server
    tmux: claude-api
```

### 5. Launch

```bash
./bridge.sh start
./bridge.sh status
./bridge.sh stop
```

## Usage

### Message Routing Syntax

Send messages in Telegram:

```
#webapp check current path           → Send to webapp session
#api run tests                       → Send to api session
#all generate docs                   → Send to all sessions
#webapp analyze code >> #api write tests based on analysis  → Chain: auto-forward after webapp completes
```

**Note**: You must use the `#` prefix to specify a target session. Messages without a prefix will return an error with a list of available sessions.

### Reply Format

All replies are tagged with their source (Hook-driven, instant push):

```
📍 webapp

This is a rent management system...

📍 api

Tests complete! All tests passed.
```

### Telegram Commands

- `/start` - Show help and session list
- `/status` - View all session status
- `/sessions` - View session list
- `/restart #session` - Restart a specific session
- `/reload` - Reload sessions.yaml configuration (no bot restart needed)
- `/chain` - View active chains
- `/chain cancel #session` - Cancel a specific chain

### Session Chaining

Chain multiple AI sessions together — the previous session's response is automatically forwarded to the next:

```
#webapp analyze performance bottlenecks >> #api optimize based on analysis
```

- Supports multi-step chains: `#A msg >> #B >> #C` (max 4 forwards)
- Cycle detection (same session cannot appear twice)
- Chain TTL: 1 hour

### Interactive Buttons

When AI CLI asks for confirmation, buttons are displayed automatically:

```
[#webapp]
Do you want to proceed with editing these 3 files?
  1. Yes, proceed with edits
  2. No, cancel

[✅ 1. Yes]  [❌ 2. No]  ← Click buttons to auto-reply
```

### Management Commands

```bash
./bridge.sh start          # Start bot in background
./bridge.sh stop           # Stop bot and clean up hooks, tmux, logs
./bridge.sh restart        # Restart bot
./bridge.sh status         # View bot and session status
./bridge.sh logs           # View bot main log
./bridge.sh logs webapp    # View specific session log
./bridge.sh validate       # Validate configuration
```

### Connect to Terminal

You can attach to tmux sessions at any time for direct access:

```bash
# List all sessions
tmux ls

# Attach to a specific session (tmux name from sessions.yaml)
tmux attach -t <tmux_session_name>

# Detach without terminating (key combo)
Ctrl+B, then press D
```

## Configuration

### sessions.yaml Format

```yaml
sessions:
  - name: session_name          # Used for #name routing
    path: project_path          # CLI working directory
    cli_type: claude            # CLI type (optional, claude, gemini, or codex, defaults to claude)
    tmux: tmux_session_name     # tmux session name (optional, defaults to {cli_type}-{name})
    cli_args: "launch args"     # CLI arguments (optional)
```

**Example:**

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

### .env Configuration

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ALLOWED_USER_IDS=user_id_1,user_id_2
AI_BRIDGE_LANGUAGE=en
```

**Variables:**
- `TELEGRAM_BOT_TOKEN` - Required, obtained from BotFather
- `ALLOWED_USER_IDS` - Required, comma-separated user IDs (bot refuses to start if empty)
- `AI_BRIDGE_LANGUAGE` - Optional, UI language (`zh-TW` Traditional Chinese / `en` English, default `zh-TW`). The legacy key `LANGUAGE` still works but clashes with the standard gettext environment variable and may be overridden by the system

## How It Works

### Instant Notifications (Hook-Driven)

1. AI CLI triggers hook when it finishes responding (Claude: Stop, Gemini: AfterAgent, Codex: Stop)
2. `notify_telegram.sh` reads response from hook stdin (Claude/Codex: `last_assistant_message`, Gemini: `prompt_response`)
3. `send_telegram_notification.py` pushes instantly via Telegram Bot API
4. Latency < 1 second, event-driven, clean reply content without ANSI codes

### Message Routing

1. `MessageRouter` parses `#project` syntax
2. `SessionManager` routes messages to the corresponding session
3. Uses `tmux send-keys` to inject into Claude Code
4. Supports `#all` to broadcast to all sessions

### Parallel Execution

- All sessions run independently without interference
- Each session has its own Hook notification
- Replies are pushed instantly in completion order, tagged with source

## File Description

**Main Program:**
- `telegram_bot_multi.py` - Telegram Bot main program

**Core Modules:**
- `session_manager.py` - Session manager
- `message_router.py` - Message router
- `tmux_bridge.py` - Tmux bridge module
- `config.py` - Centralized configuration management
- `cli_provider.py` - CLI abstraction layer (Strategy pattern, supports Claude/Gemini/Codex)

**Hook Notifications:**
- `notify_telegram.sh` - CLI Hook script (Claude: Stop, Gemini: AfterAgent, Codex: Stop)
- `send_telegram_notification.py` - Telegram API sender

**Internationalization:**
- `i18n.py` - Multi-language translation module
- `locales/zh-TW.json` / `locales/en.json` - Python translation files
- `locales/zh-TW.sh` / `locales/en.sh` - Shell translation files

**Launch & Configuration:**
- `bridge.sh` - Unified management tool (start/stop/restart/status/logs/validate)
- `sessions.yaml` - Session configuration
- `.env` - Environment variables
- `requirements.txt` - Python dependencies

## Security

1. **User Restriction**: `ALLOWED_USER_IDS` is required; bot refuses to start if not set
2. **Config Protection**: `.env` is in `.gitignore`; never commit sensitive information
3. **Working Directory Permissions**: Ensure project directory permissions are correct
4. **Network Security**: Uses Polling mode, no public URL required
5. **Shell Injection Protection**: `shlex.quote()` is used for pipe-pane paths and hook commands
6. **Rate Limiting**: Maximum 3 messages per user per 5 seconds
7. **Pinned Dependencies**: Exact versions locked to prevent supply chain attacks

## Troubleshooting

### Session Cannot Be Created

```bash
# Check tmux
which tmux

# Manual test
tmux new -s test
```

### Cannot Receive Output

```bash
# Check log files
ls -la ~/.ai_bridge/logs/*_*.log

# View logs (format: {cli_type}_{session}.log)
tail -f ~/.ai_bridge/logs/claude_webapp.log
```

### Bot Cannot Start

```bash
# Check configuration
cat .env
cat sessions.yaml

# Check Python modules
python3 -c "import telegram; import yaml; import requests"
```

### Hook Notifications Not Triggering

```bash
# Check hook config
cat /path/to/project/.claude/settings.local.json  # Claude
cat /path/to/project/.gemini/settings.json         # Gemini
cat /path/to/project/.codex/hooks.json             # Codex
cat ~/.codex/config.toml                           # Codex feature flag

# Check hook script permissions
ls -la notify_telegram.sh send_telegram_notification.py

# View hook debug logs
cat ~/.ai_bridge/logs/hook_debug_*.log

# View bot logs
./bridge.sh logs
```

### Messages Not Delivered

```bash
# Check tmux sessions
tmux ls

# Check status in Telegram
/status
```

## FAQ

**Q: How does Claude Code Plan Mode work in Telegram?**
A: Plan mode interactions (AskUserQuestion, ExitPlanMode options) are auto-detected via tmux polling and pushed as InlineKeyboard buttons. Click to select directly. Text input options (marked with ✏️) require a follow-up message: `#session your feedback`.

**Q: Why use tmux?**
A: tmux provides session management and logging, forming the foundation for bidirectional communication.

**Q: Can it be used on a remote server?**
A: Yes! As long as the server can connect to the Telegram API.

**Q: How to stop the bridge?**
A: Use the management tool for one-click shutdown (automatically cleans up all tmux sessions):
```bash
./bridge.sh stop
```

**Q: How to add a new project?**
A: Add a new configuration in `sessions.yaml`, then use the `/reload` command to hot-reload without restarting the bot.

**Q: How to restart a problematic session?**
A: Use the `/restart #session` command to restart a specific session, e.g., `/restart #webapp`. This terminates the old tmux session and creates a new one.

**Q: Do I need to restart the bot after changing configuration?**
A: No! Use the `/reload` command to hot-reload `sessions.yaml`. The system automatically adds new sessions, removes old ones, and keeps existing sessions running.

**Q: What is session chaining?**
A: Use `>>` syntax to chain sessions: `#webapp analyze code >> #api write tests`. After webapp finishes its analysis, its response is automatically forwarded to api with the "write tests" prefix instruction. Use `/chain` to view progress and `/chain cancel #session` to cancel.

## Complete Removal

Follow these steps in order to fully remove this project. **Deleting the project folder without cleaning up hooks will cause Claude Code / Gemini CLI / Codex CLI to throw hook errors on every response.**

### 1. Stop the Service

```bash
./bridge.sh stop    # Stops bot, cleans up tmux sessions, removes PID and logs
```

### 2. Clean Up Hook Configurations in Each Project

On startup, the bot writes hooks into config files in each project listed in `sessions.yaml`. You need to manually remove these hook entries:

**Claude projects** — Edit `{project_path}/.claude/settings.local.json`, remove entries containing `notify_telegram.sh` from `hooks.Stop`:

```bash
# Check which projects have hooks
grep -rl "notify_telegram" /path/to/project/.claude/settings.local.json
```

**Gemini projects** — Edit `{project_path}/.gemini/settings.json`, remove entries containing `notify_telegram.sh` from `hooks.AfterAgent`.

**Codex projects** — Edit `{project_path}/.codex/hooks.json`, remove entries containing `notify_telegram.sh` from `hooks.Stop`.

### 3. Clean Up Trusted Folder Settings (if using Gemini or Codex)

- **Gemini**: Edit `~/.gemini/trustedFolders.json` and remove path entries added by this bot.
- **Codex**: Edit `~/.codex/config.toml` and remove `[projects."..."]` sections added by this bot.

### 4. Remove System Directory

```bash
rm -rf ~/.ai_bridge    # Logs and PID files
```

### 5. Remove Project Directory

```bash
rm -rf /path/to/ai_bridge
```

### 6. Verify No Residual tmux Sessions

```bash
tmux ls    # Check for leftover claude-*, gemini-*, or codex-* sessions
tmux kill-session -t <session_name>    # Remove any remaining sessions
```

## License

MIT License

## Related Links

- [Claude Code Documentation](https://docs.claude.com/claude-code)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot](https://python-telegram-bot.readthedocs.io/)
- [tmux](https://github.com/tmux/tmux/wiki)
