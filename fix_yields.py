#!/usr/bin/env python
"""Fix broken f-strings in main.py - replace split yield lines."""
import sys

FILE = r"C:\Users\Ray\yanchi-server\backend\main.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix 1: error yield
content = content.replace(
    "yield f'{\"t\":\"error\",\"d\":\"API error ({resp.status_code}): {error_text[:100].decode()}\"}\n'",
    "yield f'{{\"t\":\"error\",\"d\":\"API error ({resp.status_code}): {error_text[:100].decode()}\"}}\\n'"
)

# Fix 2: usage yield (no choices block)
content = content.replace(
    "yield f'{\"t\":\"usage\",\"d\":{json.dumps(usage)}}\n'",
    "yield f'{{\"t\":\"usage\",\"d\":{json.dumps(usage)}}}\\n'"
)

# Fix 3: think yield
content = content.replace(
    "yield f'{\"t\":\"think\",\"d\":{json.dumps(reasoning)}}\n'",
    "yield f'{{\"t\":\"think\",\"d\":{json.dumps(reasoning)}}}\\n'"
)

# Fix 4: text yield
content = content.replace(
    "yield f'{\"t\":\"text\",\"d\":{json.dumps(text)}}\n'",
    "yield f'{{\"t\":\"text\",\"d\":{json.dumps(text)}}}\\n'"
)

# Fix 5: final usage yield (finish block)
content = content.replace(
    "yield f'{\"t\":\"usage\",\"d\":{json.dumps(usage)}}\n'",
    "yield f'{{\"t\":\"usage\",\"d\":{json.dumps(usage)}}}\\n'"
)
# But wait, there are TWO identical yield usage lines after fix 2 already replaced one
# Need to handle this more carefully - let me just re-check
# Actually, fix 2 and fix 5 have the same string, so the 2nd replace won't find anything

# Fix 6: error retry yield
content = content.replace(
    "yield f'{\"t\":\"error\",\"d\":\"砚迟暂时离开了一下，请重试\"}\n'",
    "yield f'{{\"t\":\"error\",\"d\":\"砚迟暂时离开了一下，请重试\"}}\\n'"
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("All yields fixed!")
