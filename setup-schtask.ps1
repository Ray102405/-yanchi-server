# 删除旧任务
schtasks /DELETE /TN "YanchiServer" /F 2>$null

# 新建计划任务：登录后 15 秒自动恢复 pm2 进程
schtasks /CREATE /SC ONLOGON /TN "YanchiServer" /TR "cmd.exe /c cd /d C:\Users\Ray\yanchi-server && pm2 resurrect" /IT /DELAY 0000:15 /RL LIMITED /F

Write-Host "done"
