#!/usr/bin/env python3
"""
互動選項偵測模組
從 CLI 的 tmux 輸出（日誌尾部或 capture-pane 畫面）解析互動選項，
供 interaction_polling_worker 推送 Telegram InlineKeyboard 按鈕。

三種 CLI 的畫面格式各自獨立解析：
- Claude Code：分隔線後 + ❯ 標記選項
- Gemini CLI：╭╰ 框框 + │ 邊線 + ● 標記
- Codex CLI：› 標記 + 純編號列表（capture-pane 渲染後畫面）
"""

import re

from config import config as app_config, patterns, truncate_utf16_tail

# 文字輸入選項的關鍵字（選擇後需要使用者追加輸入）
TEXT_INPUT_KEYWORDS = ['Type something', 'Tell Claude what to change',
                       'tell Codex what to do differently']


def clean_ansi(text: str) -> str:
    """清理 ANSI escape codes 和控制字元"""
    # 先把 cursor forward \x1b[NC] 替換為空格（TUI 用它代替空格）
    text = re.sub(r'\x1b\[(\d+)C', lambda m: ' ' * int(m.group(1)), text)
    text = patterns.ANSI_ESCAPE.sub('', text)
    text = patterns.CONTROL_CHARS.sub('', text)
    return text


def _is_border_line(line: str) -> bool:
    """判斷是否為分隔線（╌ 或 ─ 連續 10 個以上）"""
    stripped = line.strip()
    return ('╌' in stripped or
            (stripped.startswith('─') and len(stripped) > 10))


def _extract_options_claude(text: str) -> tuple:
    """Claude Code 格式：分隔線後 + ❯ 標記選項"""
    lines = text.split('\n')

    # 找最後一條分隔線（╌ 或 ─），只在其後搜尋選項
    last_border_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if _is_border_line(lines[i]):
            last_border_idx = i
            break

    # 沒有分隔線 → 退回用 ❯ 標記直接搜尋（從尾部往前找 ❯ 行）
    if last_border_idx < 0:
        # 從尾部找 ❯ 所在行，往前擴展選項區塊
        marker_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if '❯' in lines[i]:
                marker_idx = i
                break
        if marker_idx < 0:
            return "", []
        search_start = max(0, marker_idx - 10)
    else:
        search_start = last_border_idx + 1

    options = []
    first_option_idx = None
    has_marker = False

    for i in range(search_start, len(lines)):
        line_stripped = lines[i].strip()
        if not line_stripped:
            continue
        match = patterns.CONFIRMATION_OPTION.match(line_stripped)
        if match:
            num, label = match.group(1), match.group(2).strip()
            if len(num) <= 2:
                if first_option_idx is None:
                    first_option_idx = i
                if '❯' in lines[i]:
                    has_marker = True
                options.append((num, label))

    # 沒有 ❯ 標記的編號列表不是互動選項
    if not has_marker:
        return "", []

    # 標題：分隔線後、選項前的文字
    title = ""
    if first_option_idx is not None:
        title_lines = []
        for i in range(first_option_idx - 1, max(first_option_idx - 60, -1), -1):
            if i < 0:
                break
            line = lines[i].strip()
            if not line:
                continue
            if _is_border_line(lines[i]):
                break
            title_lines.insert(0, line)
        title = '\n'.join(title_lines)
        title = truncate_utf16_tail(title, app_config.telegram.MAX_TITLE_LENGTH)

    return title, options


def _extract_options_gemini(text: str) -> tuple:
    """Gemini CLI 格式：╭╰ 框框包裹，│ 邊線，● 標記當前選項"""
    lines = text.split('\n')

    # 找最後一個 ╰ 結束行（框框底部）
    box_end = -1
    for i in range(len(lines) - 1, -1, -1):
        if '╰' in lines[i]:
            box_end = i
            break

    if box_end < 0:
        return "", []

    # 找對應的 ╭ 開始行
    box_start = -1
    for i in range(box_end - 1, -1, -1):
        if '╭' in lines[i]:
            box_start = i
            break

    if box_start < 0:
        return "", []

    # 在框框內搜尋選項（移除 │ 邊線後匹配）
    options = []
    title_lines = []
    first_option_idx = None

    for i in range(box_start + 1, box_end):
        line = lines[i]
        # 移除 │ 邊線
        cleaned_line = line.replace('│', '').strip()
        if not cleaned_line:
            continue

        match = patterns.GEMINI_OPTION.match(cleaned_line)
        if match:
            num, label = match.group(1), match.group(2).strip()
            if len(num) <= 2:
                if first_option_idx is None:
                    first_option_idx = i
                options.append((num, label))
        elif first_option_idx is None:
            # 選項之前的內容作為標題
            title_lines.append(cleaned_line)

    title = '\n'.join(title_lines)
    title = truncate_utf16_tail(title, app_config.telegram.MAX_TITLE_LENGTH)

    return title, options


def _extract_options_codex(text: str) -> tuple:
    """Codex CLI 格式：› 標記當前選項，純編號列表

    Codex 使用 ink/React TUI，需透過 tmux capture-pane 取得渲染後文字。
    格式範例：
        › 1. Yes, proceed (y)
          2. Yes, and don't ask again for ... (p)
          3. No, and tell Codex what to do differently (esc)
    """
    lines = text.split('\n')

    # Codex 選項模式（預編譯於 config.py）
    codex_option_re = patterns.CODEX_OPTION

    # 從尾部往前掃描找到選項區塊
    options = []
    first_option_idx = None
    last_option_idx = None
    has_marker = False  # 至少一個選項要有 › 標記

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        match = codex_option_re.match(line)
        if match:
            num, label = match.group(1), match.group(2).strip()
            if len(num) <= 2:
                if last_option_idx is None:
                    last_option_idx = i
                first_option_idx = i
                if '›' in lines[i]:
                    has_marker = True
                options.insert(0, (num, label))
        elif last_option_idx is not None:
            # 遇到非選項行且已找到選項，選項區塊結束
            break

    # 沒有 › 標記的編號列表不是互動選項
    if not options or not has_marker:
        return "", []

    # 標題：選項區塊之前的內容（往前最多 30 行）
    title_lines = []
    for i in range(first_option_idx - 1, max(first_option_idx - 30, -1), -1):
        if i < 0:
            break
        line = lines[i].strip()
        if not line:
            continue
        # 遇到分隔線或 › 提示行（非選項的輸入行）停止
        if line.startswith('─') and len(line) > 10:
            break
        if line.startswith('›') and not codex_option_re.match(line):
            break
        title_lines.insert(0, line)

    title = '\n'.join(title_lines)
    title = truncate_utf16_tail(title, app_config.telegram.MAX_TITLE_LENGTH)

    return title, options


_OPTION_EXTRACTORS = {
    'gemini': _extract_options_gemini,
    'codex': _extract_options_codex,
}


def extract_options(text: str, cli_type: str = 'claude') -> tuple:
    """從清理後的文字提取標題和選項行，根據 CLI 類型分派邏輯

    Returns:
        (title, options) — title 為提問文字，options 為 [(num, label), ...]
    """
    return _OPTION_EXTRACTORS.get(cli_type, _extract_options_claude)(text)
