# Start the local personal platform once per Windows sign-in.
$personalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$userRoot = [Environment]::GetFolderPath('UserProfile')
$pythonCandidates = @(
  (Join-Path $userRoot '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
  (Join-Path $userRoot 'AppData\Local\Programs\Python\Python314\python.exe'),
  'python.exe'
)
$python = $pythonCandidates | Where-Object {
  if ($_ -eq 'python.exe') { $true } else { Test-Path -LiteralPath $_ }
} | Select-Object -First 1
if (-not $python) { exit 1 }

$running = Test-NetConnection -ComputerName '127.0.0.1' -Port 8766 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $running) {
  Start-Process -FilePath $python -ArgumentList @('-u', 'ai_server.py') -WorkingDirectory $personalDir -WindowStyle Hidden
  for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    if (Test-NetConnection -ComputerName '127.0.0.1' -Port 8766 -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
  }
}

Start-Process 'http://127.0.0.1:8766/'
