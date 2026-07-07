#!/usr/bin/env python3
"""
Debug script to check what's in the transcript
Usage: python3 test_transcript_parser.py <transcript_path>
"""

import sys
import json

if len(sys.argv) != 2:
    print("Usage: python3 test_transcript_parser.py <transcript_path>")
    sys.exit(1)

transcript_path = sys.argv[1]

try:
    with open(transcript_path, 'r') as f:
        data = json.load(f)

    messages = data.get('messages', [])

    print(f"Total messages: {len(messages)}")
    print("\n" + "="*80)

    # Find assistant messages after last user message
    assistant_messages = []
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            print(f"\nLast user message: {msg.get('content', '')[:100]}...")
            break
        if msg.get('role') == 'assistant':
            assistant_messages.insert(0, msg)

    print(f"\nAssistant messages since last user: {len(assistant_messages)}")
    print("="*80)

    for idx, msg in enumerate(assistant_messages):
        print(f"\n--- Assistant Message {idx + 1} ---")
        content = msg.get('content', [])
        print(f"Content blocks: {len(content)}")

        for c_idx, c in enumerate(content):
            c_type = c.get('type')
            print(f"\n  Block {c_idx + 1}: {c_type}")

            if c_type == 'text':
                text = c.get('text', '')
                # Show first 200 chars
                preview = text[:200].replace('\n', '\\n')
                print(f"    Text preview: {preview}...")
                print(f"    Text length: {len(text)}")

            elif c_type == 'tool_use':
                tool_name = c.get('name')
                tool_input = c.get('input', {})
                print(f"    Tool: {tool_name}")
                print(f"    Input: {str(tool_input)[:100]}...")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
