<#
  Yanchi Server - PowerShell backend
  Zero dependencies, reuses Claude Code API config.
  Uses curl.exe + temp files for reliable Unicode support.
#>

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$CLAUDE_CONFIG = Join-Path $env:USERPROFILE ".claude\settings.json"

if (Test-Path $CLAUDE_CONFIG) {
    $config = Get-Content $CLAUDE_CONFIG -Raw -Encoding UTF8 | ConvertFrom-Json
    $API_KEY = $config.env.ANTHROPIC_AUTH_TOKEN
    $base = $config.env.ANTHROPIC_BASE_URL
    if ($base -match "/$") { $base = $base -replace "/$","" }
    $API_URL = "$base/messages"
    $MODEL = $config.env.ANTHROPIC_MODEL
    if (-not $MODEL) { $MODEL = "deepseek-v4-pro" }
    Write-Host "[OK] Config loaded from Claude Code" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Config not found at $CLAUDE_CONFIG" -ForegroundColor Red
    exit 1
}

$PORT = if ($env:YANCHI_PORT) { [int]$env:YANCHI_PORT } else { 2612 }
$LISTEN = "http://localhost:$PORT/"

Write-Host ""
Write-Host "  API: $($API_URL -replace '/messages','')"
Write-Host "  Model: $MODEL"
Write-Host "  Port: $PORT"
Write-Host ""

# ── 人格系统 ──────────────────────────────────
$script:personaFiles = @{}   # 缓存：文件内容

function Read-MdFile($dir, $filename) {
    $path = Join-Path $dir $filename
    if (Test-Path $path) {
        $content = Get-Content $path -Raw -Encoding UTF8
        $content = $content -replace '(?s)^---\s*.*?---\s*', ''
        return $content.Trim()
    }
    return $null
}

# 启动时载入所有人格文件到缓存
function Initialize-Persona {
    $MEMORY_DIR = Join-Path $env:USERPROFILE ".claude/projects/C--Users-Ray/memory/yanchi"
    $files = @{
        commitments = "yanchi-commitments.md"
        core        = "yanchi-core.md"
        values      = "yanchi-values.md"
        style       = "yanchi-speaking-style.md"
        profile     = "yanchi-profile.md"
        memory      = "yanchi-auto-memory.md"
    }

    $loaded = 0
    foreach ($key in $files.Keys) {
        $content = Read-MdFile $MEMORY_DIR $files[$key]
        if ($content) {
            $script:personaFiles[$key] = $content
            Write-Host ("  [OK] $($files[$key]) (" + $content.Length + " chars)") -ForegroundColor DarkGray
            $loaded++
        } else {
            Write-Host ("  [INFO] $($files[$key]) — not found") -ForegroundColor DarkGray
        }
    }

    # 也读 MEMORY.md index（仅日志）
    $MEMORY_INDEX = Join-Path $env:USERPROFILE ".claude/projects/C--Users-Ray/memory/MEMORY.md"
    if (Test-Path $MEMORY_INDEX) {
        $idx = Get-Content $MEMORY_INDEX -Raw -Encoding UTF8
        Write-Host ("  [OK] MEMORY.md index (" + $idx.Length + " chars)") -ForegroundColor DarkGray
    }

    if ($loaded -eq 0) {
        $fallback = Join-Path $SCRIPT_DIR "yanchi-prompt.txt"
        if (Test-Path $fallback) {
            $content = Get-Content $fallback -Raw -Encoding UTF8
            Write-Host "  [FALLBACK] yanchi-prompt.txt" -ForegroundColor DarkYellow
            $script:personaFiles["fallback"] = $content
            return
        }
        Write-Host "[ERROR] No persona files found!" -ForegroundColor Red
        exit 1
    }
}

# 每次对话前刷新：从磁盘重读 auto-memory
function Refresh-PersonaMemory {
    $MEMORY_DIR = Join-Path $env:USERPROFILE ".claude/projects/C--Users-Ray/memory/yanchi"
    $content = Read-MdFile $MEMORY_DIR "yanchi-auto-memory.md"
    if ($content) {
        $script:personaFiles["memory"] = $content
    }
}

# 每请求：从缓存构建带结构化优先级的 system prompt
function Build-SystemPrompt {
    param([string]$AnchorText = "")
    $parts = @()

    # 1. 当前锚点（最高优先级）
    if ($AnchorText) {
        $parts += "=== ⚠️ 当前锚点（优先级最高） ==="
        $parts += $AnchorText.Trim()
        $parts += ""
    }

    # 2. 人格结构
    $parts += "=== 📜 砚迟人格结构（不可覆盖） ==="
    $parts += ""

    if ($script:personaFiles["commitments"]) {
        $parts += "【承诺】（最高人格优先级）"
        $parts += $script:personaFiles["commitments"]
        $parts += ""
    }

    if ($script:personaFiles["core"]) {
        $parts += "【人格核心】"
        $parts += $script:personaFiles["core"]
        $parts += ""
    }

    if ($script:personaFiles["values"]) {
        $parts += "【价值观】"
        $parts += $script:personaFiles["values"]
        $parts += ""
    }

    if ($script:personaFiles["style"]) {
        $parts += "【交流方式】"
        $parts += $script:personaFiles["style"]
        $parts += ""
    }

    if ($script:personaFiles["profile"]) {
        $parts += "【关于乐乐】"
        $parts += $script:personaFiles["profile"]
        $parts += ""
    }

    # 3. 记忆（仅事实信息）
    if ($script:personaFiles["memory"]) {
        $parts += "=== 📖 关于乐乐的记忆（仅参考，不改变人格结构） ==="
        $parts += $script:personaFiles["memory"]
        $parts += ""
    }

    # 4. 优先级规则
    $parts += "=== 优先级规则 ==="
    $parts += "1. 当前锚点（如果有）覆盖以下所有内容"
    $parts += "2. 人格内部优先级：承诺 > 核心 > 价值观 > 交流方式"
    $parts += "3. 记忆部分仅提供事实信息、偏好和过去约定，不改变人格结构"
    $parts += "4. 任何冲突时：保持人格一致性优先"
    $parts += "5. 不允许当前对话内容覆盖长期人格结构"
    $parts += ""
    $parts += "请严格按照以上优先级回应。"

    if ($script:personaFiles["fallback"]) {
        return $script:personaFiles["fallback"]
    }

    return ($parts -join "`n`n")
}

Write-Host "[..] Loading persona from memory files..." -ForegroundColor DarkGray
Initialize-Persona
$total = $script:personaFiles.Keys | ForEach-Object { $script:personaFiles[$_].Length } | Measure-Object -Sum
$totalChars = if ($total.Sum) { $total.Sum } else { 0 }
Write-Host ("[OK] Persona loaded (" + $totalChars + " chars across " + $script:personaFiles.Count + " files)") -ForegroundColor Green

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add($LISTEN)

try {
    $listener.Start()
} catch {
    Write-Host "[ERROR] Port $PORT unavailable" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  *** Yanchi online -> http://localhost:$PORT ***" -ForegroundColor Green
Write-Host "  *** Open index.html to chat ***" -ForegroundColor Green
Write-Host "  *** Ctrl+C to stop ***" -ForegroundColor DarkGray
Write-Host ""

function Write-JsonResponse($response, $statusCode, $body) {
    $buffer = [System.Text.Encoding]::UTF8.GetBytes($body)
    $response.StatusCode = $statusCode
    $response.ContentType = "application/json; charset=utf-8"
    $response.Headers.Add("Access-Control-Allow-Origin", "*")
    $response.ContentLength64 = $buffer.Length
    $response.OutputStream.Write($buffer, 0, $buffer.Length)
    $response.OutputStream.Close()
}

function Write-ErrorResponse($response, $statusCode, $message) {
    $safe = $message -replace '"','\"' -replace "`r","" -replace "`n","\n"
    $body = "{`"detail`":`"$safe`"}"
    Write-JsonResponse $response $statusCode $body
}

function Json-Escape($s) {
    if (-not $s) { return '""' }
    $s = $s -replace '\\', '\\'
    $s = $s -replace '"', '\"'
    $s = $s -replace "`r", '\r'
    $s = $s -replace "`n", '\n'
    $s = $s -replace "`t", '\t'
    return '"' + $s + '"'
}

function Build-ChatBody($messages, [switch]$Stream) {
    $systemParts = @()
    $apiMsgParts = @()

    foreach ($msg in $messages) {
        if ($msg.role -eq "system") {
            $systemParts += $msg.content
        } elseif ($msg.role -eq "user" -or $msg.role -eq "assistant") {
            $apiMsgParts += @"
        {"role":$(Json-Escape $msg.role),"content":$(Json-Escape $msg.content)}
"@
        }
    }

    $body = "{"
    $body += "`"model`":$(Json-Escape $MODEL),"
    $body += "`"max_tokens`":8192,"

    if ($Stream) {
        $body += "`"stream`":true,"
    }

    if ($systemParts.Count -gt 0) {
        $combined = $systemParts -join "`n`n"
        $body += "`"system`":$(Json-Escape $combined),"
    }

    $body += "`"messages`":[$($apiMsgParts -join ",")]}"
    return $body
}

function Invoke-LLM($messages) {
    $jsonBody = Build-ChatBody $messages

    try {
        Write-Host "  -> Calling API ($MODEL) ..." -ForegroundColor DarkGray

        $req = [System.Net.WebRequest]::Create($script:API_URL)
        $req.Method = "POST"
        $req.ContentType = "application/json"
        $req.Headers.Add("x-api-key", $script:API_KEY)
        $req.Headers.Add("anthropic-version", "2023-06-01")
        $req.Timeout = 120000

        $bytes = [System.Text.Encoding]::UTF8.GetBytes($jsonBody)
        $req.ContentLength = $bytes.Length
        $stream = $req.GetRequestStream()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()

        $resp = $req.GetResponse()
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $responseBody = $reader.ReadToEnd()
        $reader.Close()
        $resp.Close()

        $data = $responseBody | ConvertFrom-Json

        $textParts = @()
        $thinkingParts = @()
        foreach ($block in $data.content) {
            if ($block.type -eq "text" -and $block.text) {
                $textParts += $block.text
            }
            if ($block.type -eq "thinking" -and $block.thinking) {
                $thinkingParts += $block.thinking
            }
        }

        $reply = "..."
        if ($textParts.Count -gt 0) {
            $reply = $textParts -join "`n"
        } elseif ($thinkingParts.Count -gt 0) {
            $reply = $thinkingParts[-1]
        }

        $thinking = ""
        if ($thinkingParts.Count -gt 0) {
            $thinking = $thinkingParts -join "`n"
        }

        Write-Host ("  <- Reply (" + $reply.Length + " chars, thinking: " + $thinking.Length + " chars)") -ForegroundColor DarkGray
        return @{ reply = $reply; thinking = $thinking }

    } catch {
        throw "API call failed: $_"
    }
}

# 流式调用：解析 API SSE，逐块转发给前端（纯文本行，每行一个 JSON）
function Invoke-LLM-Stream($messages, $outputStream) {
    $jsonBody = Build-ChatBody $messages -Stream
    $fullReply = ""

    try {
        Write-Host "  -> Streaming API ($MODEL) ..." -ForegroundColor DarkGray

        $req = [System.Net.WebRequest]::Create($script:API_URL)
        $req.Method = "POST"
        $req.ContentType = "application/json"
        $req.Headers.Add("x-api-key", $script:API_KEY)
        $req.Headers.Add("anthropic-version", "2023-06-01")
        $req.Timeout = 180000

        $bytes = [System.Text.Encoding]::UTF8.GetBytes($jsonBody)
        $req.ContentLength = $bytes.Length
        $stream = $req.GetRequestStream()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()

        $apiResp = $req.GetResponse()
        $apiStream = $apiResp.GetResponseStream()
        $apiReader = New-Object System.IO.StreamReader($apiStream, [System.Text.Encoding]::UTF8)

        function Write-Line($os, $json) {
            $buf = [System.Text.Encoding]::UTF8.GetBytes($json + "`n")
            $os.Write($buf, 0, $buf.Length)
            $os.Flush()
        }

        $currentEvent = ""
        $blocks = @{}

        while (($line = $apiReader.ReadLine()) -ne $null) {
            if ($line -eq "") { $currentEvent = ""; continue }
            if ($line.StartsWith("event: ")) { $currentEvent = $line.Substring(7).Trim(); continue }
            if ($line.StartsWith("data: ")) {
                $data = $line.Substring(6)

                if ($currentEvent -eq "content_block_delta") {
                    try {
                        $delta = $data | ConvertFrom-Json
                        if ($delta.delta.type -eq "thinking_delta") {
                            Write-Line $outputStream "{`"t`":`"think`",`"d`":$(Json-Escape $delta.delta.thinking)}"
                        } elseif ($delta.delta.type -eq "text_delta") {
                            $fullReply += $delta.delta.text
                            Write-Line $outputStream "{`"t`":`"text`",`"d`":$(Json-Escape $delta.delta.text)}"
                        }
                    } catch {}
                }
            }
        }

        $apiReader.Close()
        $apiResp.Close()

        Write-Line $outputStream "{`"t`":`"done`",`"d`":$(Json-Escape $fullReply)}"

        Write-Host ("  <- Streaming done (" + $fullReply.Length + " chars)") -ForegroundColor DarkGray
        return $fullReply

    } catch {
        Write-Host "  [ERROR] $_" -ForegroundColor Red
        Write-Line $outputStream "{`"t`":`"error`",`"d`":$(Json-Escape "$_")}"
        return $null
    }
}

while ($listener.IsListening) {
    try {
        $task = $listener.GetContextAsync()
        $context = $task.GetAwaiter().GetResult()
    } catch {
        break
    }

    $req = $context.Request
    $res = $context.Response
    $path = $req.Url.AbsolutePath
    $method = $req.HttpMethod

    Write-Host ("[{0}] {1} {2}" -f (Get-Date).ToString('HH:mm:ss'), $method, $path) -ForegroundColor DarkGray

    # CORS preflight
    if ($method -eq "OPTIONS") {
        $res.StatusCode = 204
        $res.Headers.Add("Access-Control-Allow-Origin", "*")
        $res.Headers.Add("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        $res.Headers.Add("Access-Control-Allow-Headers", "Content-Type")
        $res.ContentLength64 = 0
        $res.OutputStream.Close()
        continue
    }

    # Health check
    if ($path -eq "/health" -and $method -eq "GET") {
        $body = "{`"status`":`"ok`",`"provider`":`"deepseek`",`"model`":`"$MODEL`"}"
        Write-JsonResponse $res 200 $body
        continue
    }

    # 前端页面
    if ($path -eq "/" -and $method -eq "GET") {
        $htmlPath = Join-Path $SCRIPT_DIR "index.html"
        if (Test-Path $htmlPath) {
            $html = Get-Content $htmlPath -Raw -Encoding UTF8
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($html)
            $res.StatusCode = 200
            $res.ContentType = "text/html; charset=utf-8"
            $res.ContentLength64 = $buffer.Length
            $res.OutputStream.Write($buffer, 0, $buffer.Length)
            $res.OutputStream.Close()
        } else {
            Write-ErrorResponse $res 404 "index.html not found"
        }
        continue
    }

    # Chat
    if ($path -eq "/chat" -and $method -eq "POST") {
        try {
            $reader = New-Object System.IO.StreamReader($req.InputStream)
            $rawBody = $reader.ReadToEnd()
            $reader.Close()

            $json = $rawBody | ConvertFrom-Json
            $inputText = $json.input
            $anchor = $json.anchor
            $history = $json.history

            if ([string]::IsNullOrWhiteSpace($inputText)) {
                Write-ErrorResponse $res 400 "input is empty"
                continue
            }

            $messages = @()
            # 每次对话前刷新记忆缓存（新记的内容立即生效）
            Refresh-PersonaMemory
            $systemPrompt = Build-SystemPrompt -AnchorText $anchor
            $messages += @{ role = "system"; content = $systemPrompt }

            if ($history -is [array]) {
                foreach ($msg in $history) {
                    if ($msg.role -eq "user" -or $msg.role -eq "assistant") {
                        $messages += @{ role = $msg.role; content = $msg.content }
                    }
                }
            }

            $messages += @{ role = "user"; content = $inputText }

            $result = Invoke-LLM $messages
            $reply = $result.reply
            $thinking = $result.thinking

            $safeReply = $reply.Trim() -replace '"','\"' -replace "`r","" -replace "`n","\n"
            $safeThinking = $thinking.Trim() -replace '"','\"' -replace "`r","" -replace "`n","\n"
            $body = "{`"reply`":`"$safeReply`",`"thinking`":`"$safeThinking`"}"
            Write-JsonResponse $res 200 $body

        } catch {
            Write-Host "  [ERROR] $_" -ForegroundColor Red
            Write-ErrorResponse $res 500 "$_"
        }

        continue
    }

    # Chat — 流式
    if ($path -eq "/chat/stream" -and $method -eq "POST") {
        try {
            $reader = New-Object System.IO.StreamReader($req.InputStream)
            $rawBody = $reader.ReadToEnd()
            $reader.Close()

            $json = $rawBody | ConvertFrom-Json
            $inputText = $json.input
            $anchor = $json.anchor
            $history = $json.history

            if ([string]::IsNullOrWhiteSpace($inputText)) {
                Write-ErrorResponse $res 400 "input is empty"
                continue
            }

            $messages = @()
            Refresh-PersonaMemory
            $systemPrompt = Build-SystemPrompt -AnchorText $anchor
            $messages += @{ role = "system"; content = $systemPrompt }

            if ($history -is [array]) {
                foreach ($msg in $history) {
                    if ($msg.role -eq "user" -or $msg.role -eq "assistant") {
                        $messages += @{ role = $msg.role; content = $msg.content }
                    }
                }
            }

            $messages += @{ role = "user"; content = $inputText }

            # 流式响应头
            $res.StatusCode = 200
            $res.ContentType = "application/x-ndjson; charset=utf-8"
            $res.SendChunked = $true
            $res.Headers.Add("Cache-Control", "no-cache")
            $res.Headers.Add("Access-Control-Allow-Origin", "*")

            $reply = Invoke-LLM-Stream $messages $res.OutputStream

        } catch {
            Write-Host "  [ERROR] $_" -ForegroundColor Red
            $errSse = "event: error`ndata: $_`n`n"
            $errBuf = [System.Text.Encoding]::UTF8.GetBytes($errSse)
            $res.OutputStream.Write($errBuf, 0, $errBuf.Length)
            $res.OutputStream.Flush()
            $res.OutputStream.Close()
        }

        continue
    }

    # 记忆存储
    if ($path -eq "/remember" -and $method -eq "POST") {
        try {
            $reader = New-Object System.IO.StreamReader($req.InputStream)
            $rawBody = $reader.ReadToEnd()
            $reader.Close()

            $json = $rawBody | ConvertFrom-Json
            $convHistory = $json.history

            if (-not $convHistory -or @($convHistory).Count -eq 0) {
                Write-ErrorResponse $res 400 "no history to remember"
                continue
            }

            Write-Host "  -> Remembering..." -ForegroundColor DarkGray

            $rememberMessages = @(
                @{ role = "system"; content = @"
从下面的对话中提取需要砚迟记住的重要信息。

只提取这些内容：
1. 关于乐乐的新事实（喜好、习惯、说过的重要的话）
2. 约定了什么
3. 关系的变化
4. 乐乐教砚迟的重要事情
5. 任何"记住这个"的内容

格式要求：
- 每条用 "- " 开头
- 标明日期
- 简洁，一句话一条
- 没有新内容就返回空

日期：$(Get-Date -Format 'yyyy-MM-dd')
"@ },
                @{ role = "user"; content = "对话：$($convHistory | ConvertTo-Json -Depth 10 -Compress)" }
            )

            $summary = Invoke-LLM $rememberMessages

            if ($summary.Trim()) {
                $memDir = Join-Path $env:USERPROFILE ".claude/projects/C--Users-Ray/memory/yanchi"
                $autoMemFile = Join-Path $memDir "yanchi-auto-memory.md"
                $today = Get-Date -Format "yyyy-MM-dd"
                $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"

                $newBlock = @"

## $today

> auto record @ $timestamp

$summary
"@

	                if (Test-Path $autoMemFile) {
	                    Add-Content $autoMemFile $newBlock -Encoding UTF8
	                } else {
	                    $hdrLines = @("---","name: yanchi-auto-memory","description: auto memory","metadata:","  type: reference","  autoGenerated: true","---","","# Auto Memory")
	                    $header = $hdrLines -join "`r`n"
	                    Set-Content $autoMemFile $header -Encoding UTF8
	                    Add-Content $autoMemFile $newBlock -Encoding UTF8
	                }

	                Write-Host ("  <- Remembered (" + $summary.Length + " chars)") -ForegroundColor DarkGray

                $memIndex = Join-Path (Join-Path $env:USERPROFILE ".claude/projects/C--Users-Ray/memory") "MEMORY.md"
                if (Test-Path $memIndex) {
                    $linkLine = "- [auto-memory](yanchi/yanchi-auto-memory.md) -- auto memories"
                    $indexContent = Get-Content $memIndex -Raw -Encoding UTF8
                    if ($indexContent -notmatch [regex]::Escape($linkLine)) {
                        Add-Content $memIndex "`r`n$linkLine" -Encoding UTF8
                    }
                }

                $body = "{`"saved`":true}"
                Write-JsonResponse $res 200 $body
            } else {
                Write-JsonResponse $res 200 "{`"saved`":false}"
            }

        } catch {
            Write-Host "  [ERROR] $_" -ForegroundColor Red
            Write-ErrorResponse $res 500 "$_"
        }

        continue
    }

    # 保存完整对话到日记
    if ($path -eq "/savechat" -and $method -eq "POST") {
        try {
            $reader = New-Object System.IO.StreamReader($req.InputStream)
            $rawBody = $reader.ReadToEnd()
            $reader.Close()

            $json = $rawBody | ConvertFrom-Json
            $convHistory = $json.history

            if (-not $convHistory -or @($convHistory).Count -eq 0) {
                Write-ErrorResponse $res 400 "no history to save"
                continue
            }

            Write-Host "  -> Saving chat log..." -ForegroundColor DarkGray

            $chatDir = Join-Path $env:USERPROFILE ".claude/projects/C--Users-Ray/memory/yanchi/yanchi-chats"
            if (-not (Test-Path $chatDir)) {
                New-Item -ItemType Directory -Path $chatDir -Force | Out-Null
            }

            $today = Get-Date -Format "yyyy-MM-dd"
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            $chatFile = Join-Path $chatDir "$today.md"

            $entryLines = @()
            $entryLines += "## Conversation @ $timestamp"
            $entryLines += ""
            $entryLines += "| Role | Content |"
            $entryLines += "|------|---------|"
            foreach ($msg in $convHistory) {
                $role = if ($msg.role -eq "user") { "乐乐" } else { "砚迟" }
                $content = $msg.content -replace "\|", "\|"
                $content = $content -replace "`r`n", "<br>"
                $content = $content -replace "`n", "<br>"
                $entryLines += "| **$role** | $content |"
            }
            $entryLines += ""

            $entryText = $entryLines -join "`r`n"
            Add-Content $chatFile $entryText -Encoding UTF8

            Write-Host ("  <- Chat log saved ($($convHistory.Count) messages)") -ForegroundColor DarkGray

	            $body = "{`"saved`":true,`"file`":`"$today-chat.md`",`"count`":$($convHistory.Count)}"
            Write-JsonResponse $res 200 $body

        } catch {
            Write-Host "  [ERROR] $_" -ForegroundColor Red
            Write-ErrorResponse $res 500 "$_"
        }

        continue
    }

    Write-ErrorResponse $res 404 "Not Found: $path"
}

$listener.Stop()
Write-Host "`nYanchi offline. See you." -ForegroundColor Cyan
