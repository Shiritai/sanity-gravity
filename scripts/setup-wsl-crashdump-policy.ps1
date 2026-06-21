[CmdletBinding()]
param(
    [string]$WslConfigPath = "$env:USERPROFILE\.wslconfig",
    [switch]$CleanExisting,
    [switch]$RestartWsl
)

$desiredKey = "maxCrashDumpCount"
$desiredValue = "-1"
$crashDir = Join-Path $env:TEMP "wsl-crashes"

function Set-Wsl2Value {
    param(
        [string[]]$Lines,
        [string]$Key,
        [string]$Value
    )

    $output = New-Object System.Collections.Generic.List[string]
    $inWsl2 = $false
    $sawWsl2 = $false
    $wroteKey = $false

    foreach ($line in $Lines) {
        if ($line -match '^\s*\[(.+)\]\s*$') {
            if ($inWsl2 -and -not $wroteKey) {
                $output.Add("$Key=$Value")
                $wroteKey = $true
            }

            $section = $matches[1]
            $inWsl2 = ($section -ieq "wsl2")
            if ($inWsl2) {
                $sawWsl2 = $true
            }
        }

        if ($inWsl2 -and $line -match "^\s*$([regex]::Escape($Key))\s*=") {
            if (-not $wroteKey) {
                $output.Add("$Key=$Value")
                $wroteKey = $true
            }
            continue
        }

        $output.Add($line)
    }

    if ($inWsl2 -and -not $wroteKey) {
        $output.Add("$Key=$Value")
        $wroteKey = $true
    }

    if (-not $sawWsl2) {
        if ($output.Count -gt 0 -and $output[$output.Count - 1] -ne "") {
            $output.Add("")
        }
        $output.Add("[wsl2]")
        $output.Add("$Key=$Value")
    }

    return $output.ToArray()
}

if (Test-Path -LiteralPath $WslConfigPath) {
    $lines = Get-Content -LiteralPath $WslConfigPath
} else {
    $parent = Split-Path -Parent $WslConfigPath
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    $lines = @()
}

$updated = Set-Wsl2Value -Lines $lines -Key $desiredKey -Value $desiredValue
Set-Content -LiteralPath $WslConfigPath -Value $updated -Encoding utf8

Write-Host "Updated $WslConfigPath with [wsl2] $desiredKey=$desiredValue"

if ($CleanExisting) {
    if (Test-Path -LiteralPath $crashDir) {
        Get-ChildItem -LiteralPath $crashDir -File -Filter "*.dmp" |
            Remove-Item -Force
        Write-Host "Removed existing WSL crash dumps from $crashDir"
    } else {
        Write-Host "No WSL crash dump directory found at $crashDir"
    }
}

if ($RestartWsl) {
    Write-Host "Running wsl --shutdown to apply .wslconfig changes..."
    wsl --shutdown
}

Write-Host "Done."
