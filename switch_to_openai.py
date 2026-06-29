#!/usr/bin/env python
"""Switch API from Anthropic format to OpenAI format (硅基流动)."""

FILE = r"C:\Users\Ray\yanchi-server\backend\main.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace call_llm (non-streaming)
old_call_llm = r"""async def call_llm(messages: list[dict]) -> dict:
    body = {
        "model": _current_model,
        "max_tokens": 8192,
        "messages": messages,
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(API_URL, json=body, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"API error ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    text_parts = []
    thinking_parts = []
    for block in data.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            text_parts.append(block["text"])
        if block.get("type") == "thinking" and block.get("thinking"):
            thinking_parts.append(block["thinking"])

    reply = text_parts[-1] if text_parts else (thinking_parts[-1] if thinking_parts else "...")
    thinking = "\\n".join(thinking_parts)

    return {"reply": reply, "thinking": thinking, "usage": data.get("usage", {})}"""

new_call_llm = r"""async def call_llm(messages: list[dict]) -> dict:
    body = {
        "model": _current_model,
        "max_tokens": 8192,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(API_URL, json=body, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"API error ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})
    reply = msg.get("content", "") or ""
    thinking = msg.get("reasoning_content", "") or ""
    if not thinking and msg.get("reasoning"):
        thinking = msg["reasoning"]

    return {"reply": reply, "thinking": thinking, "usage": data.get("usage", {})}"""

if old_call_llm in content:
    content = content.replace(old_call_llm, new_call_llm, 1)
    print("1. call_llm updated")
else:
    print("1. SKIP call_llm - pattern not found")

# 2. Replace call_llm_stream
old_stream = r"""async def call_llm_stream(messages: list[dict], retry: int = 0):
    body = {
        "model": _current_model,
        "max_tokens": 8192,
        "stream": True,
        "messages": messages,
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream("POST", API_URL, json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        yield f'{{"t":"error","d":"API error ({resp.status_code}): {error_text[:100].decode()}"}}\\n'
                        return

                    current_event = ""
                    async for line in resp.aiter_lines():
                        if not line:
                            current_event = ""
                            continue
                        if line.startswith("event: "):
                            current_event = line[7:].strip()
                            continue
                        if line.startswith("data: "):
                            raw = line[6:]
                            if current_event == "message_start":
                                try:
                                    msg = json.loads(raw).get("message", {})
                                    usage = msg.get("usage", {})
                                    if usage:
                                        yield f'{{"t":"usage","d":{json.dumps(usage)}}}\\n'
                                except json.JSONDecodeError:
                                    pass

                            elif current_event == "content_block_delta":
                                try:
                                    delta = json.loads(raw)
                                    dt = delta.get("delta", {})
                                    if dt.get("type") == "thinking_delta":
                                        txt = dt.get("thinking", "")
                                        yield f'{{"t":"think","d":{json.dumps(txt)}}}\\n'
                                    elif dt.get("type") == "text_delta":
                                        txt = dt.get("text", "")
                                        yield f'{{"t":"text","d":{json.dumps(txt)}}}\\n'
                                except json.JSONDecodeError:
                                    pass

                        elif current_event == "message_delta":
                            try:
                                delta = json.loads(raw)
                                usage = delta.get("usage", {})
                                if usage:
                                    yield f'{{"t":"usage","d":{json.dumps(usage)}}}\\n'
                            except json.JSONDecodeError:
                                pass
            return

        except Exception as e:
            log.error(f"  [Stream] Attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                log.info("  [Stream] Retrying once...")
                continue
            yield f'{{"t":"error","d":"砚迟暂时离开了一下，请重试"}}\\n'"""

new_stream = r"""async def call_llm_stream(messages: list[dict], retry: int = 0):
    body = {
        "model": _current_model,
        "max_tokens": 8192,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "content-type": "application/json",
    }

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream("POST", API_URL, json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        yield f'{{"t":"error","d":"API error ({resp.status_code}): {error_text[:100].decode()}"}}\n'
                        return

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw.strip() == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            usage = chunk.get("usage", {})
                            if usage:
                                yield f'{{"t":"usage","d":{json.dumps(usage)}}}\n'
                            continue

                        delta = choices[0].get("delta", {})

                        reasoning = delta.get("reasoning_content", "")
                        if reasoning:
                            yield f'{{"t":"think","d":{json.dumps(reasoning)}}}\n'

                        text = delta.get("content", "")
                        if text:
                            yield f'{{"t":"text","d":{json.dumps(text)}}}\n'

                        finish = choices[0].get("finish_reason")
                        if finish:
                            usage = chunk.get("usage", {})
                            if usage:
                                yield f'{{"t":"usage","d":{json.dumps(usage)}}}\n'
            return

        except Exception as e:
            log.error(f"  [Stream] Attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                log.info("  [Stream] Retrying once...")
                continue
            yield f'{{"t":"error","d":"砚迟暂时离开了一下，请重试"}}\n'"""

if old_stream in content:
    content = content.replace(old_stream, new_stream, 1)
    print("2. call_llm_stream updated")
else:
    print("2. SKIP call_llm_stream - pattern not found")

# 3. Remove cache_control from system prompts
content = content.replace(', "cache_control": {"type": "ephemeral"}', '')
print("3. cache_control removed")

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
