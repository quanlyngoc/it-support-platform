<#
.SYNOPSIS
  Cài / kiểm / gỡ 2 tác vụ vận hành BẮT BUỘC trước canary (Sổ tay 0.6 + 0.7). CHỈ ĐỌC hệ cũ.

.DESCRIPTION
  ITM Sao luu CSDL cu  : hằng ngày 23:30 → D:\Backup\daily\database_<ngày>.db + may_<ngày>.csv (giữ 14 bản),
                         nhật ký D:\Backup\daily\sao_luu.log
  ITM Canh bao online  : mỗi 1 phút → Telegram khi máy rớt bất thường hoặc mất hub; baseline từng phút
                         D:\Backup\baseline\online_<ngày>.csv; sự kiện D:\Backup\baseline\canh_bao.log;
                         máy đã chuyển sang Core (canary) ghi vào D:\Backup\baseline\canary_hosts.txt (mỗi dòng 1 tên máy)
  Cả hai chạy bằng SYSTEM bằng Python của bản chạy Core (D:\ITSupportPlatformRun) — không cài gì vào Python hệ thống.
  Không sửa gì của hệ cũ: chỉ đọc database.db (mode=ro) + app.py (lấy token nội bộ) và gọi GET /internal/machines.
  Bí mật (token nội bộ, Telegram) tự lấy từ hệ cũ, ghi vào D:\ITSupportPlatformSecrets — chỉ SYSTEM + Administrators đọc.

.EXAMPLE
  # PowerShell "Run as Administrator":
  Set-ExecutionPolicy -Scope Process Bypass -Force; & D:\ITSupportPlatform\platform-deployment\ops\cai_dat_ops.ps1 -Lenh CaiDat
  ... -Lenh KiemTra    xem trạng thái 2 tác vụ, bản sao lưu mới nhất, dòng baseline cuối
  ... -Lenh Go         gỡ 2 tác vụ (giữ nguyên bản sao lưu, baseline, kho bí mật)
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('CaiDat', 'KiemTra', 'Go')]
    [string]$Lenh,
    [string]$Py = 'D:\ITSupportPlatformRun\platform-core\.venv\Scripts\python.exe',
    [string]$NguonOps = 'D:\ITSupportPlatform\platform-deployment\ops',
    [string]$Tools = 'D:\Backup\tools',
    [string]$Daily = 'D:\Backup\daily',
    [string]$Baseline = 'D:\Backup\baseline',
    [string]$BiMat = 'D:\ITSupportPlatformSecrets',
    [string]$GioSaoLuu = '23:30'
)

$ErrorActionPreference = 'Stop'
$TK_SL = 'ITM Sao luu CSDL cu'
$TK_CB = 'ITM Canh bao online'
$BI_MAT_TEP = @{ internal_token = 'internal_token.txt'; telegram_token = 'telegram_token.txt'; telegram_chat = 'telegram_chat.txt' }

function Buoc([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Dat([string]$m) { Write-Host "    [ĐẠT] $m" -ForegroundColor Green }
function Canh([string]$m) { Write-Host "    [!]   $m" -ForegroundColor Yellow }
function Dung([string]$m) { Write-Host "    [X]   $m" -ForegroundColor Red; exit 1 }

function Test-LaAdmin {
    $p = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-KetQua([int64]$ma) {
    switch ($ma) { 0 { 'OK (0x0)' } 267009 { 'đang chạy' } 267011 { 'chưa chạy lần nào' } default { '0x{0:X}' -f $ma } }
}

function Show-TacVu([string]$ten) {
    $t = Get-ScheduledTask -TaskName $ten -ErrorAction SilentlyContinue
    if (-not $t) { Canh "Chưa có tác vụ '$($ten)'"; return $null }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "    $($ten): $($t.State) · chạy cuối $($i.LastRunTime) → $(Get-KetQua $i.LastTaskResult) · lần tới $($i.NextRunTime)"
    return $i
}

function Wait-TacVu([string]$ten, [datetime]$tu, [int]$giay) {
    # Chờ tác vụ chạy xong một lượt bắt đầu sau mốc $tu; trả mã kết quả (hoặc $null nếu quá giờ)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $giay) {
        Start-Sleep -Seconds 2
        $t = Get-ScheduledTask -TaskName $ten
        $i = $t | Get-ScheduledTaskInfo
        if ($t.State -ne 'Running' -and $i.LastRunTime -ge $tu.AddSeconds(-2) -and $i.LastTaskResult -ne 267009) {
            return [int64]$i.LastTaskResult
        }
    }
    return $null
}

function Test-NoiDung([string]$p) {
    # Tệp tồn tại VÀ có nội dung (Get-Content -Raw trả $null với tệp rỗng → .Trim() sẽ làm dừng script)
    return (Test-Path $p) -and ([string](Get-Content $p -Raw)).Trim().Length -gt 0
}

function Invoke-PyRaw([string[]]$thamSo) {
    # Gọi Python, lấy stdout dạng chuỗi; EAP cục bộ Continue để stderr không biến thành lỗi dừng script (PS 5.1)
    $ErrorActionPreference = 'Continue'
    $out = & $Py @thamSo 2>$null
    return [pscustomobject]@{ Ma = $LASTEXITCODE; Out = ($out -join "`n") }
}

switch ($Lenh) {

    'KiemTra' {
        Buoc 'Tác vụ'
        $null = Show-TacVu $TK_SL
        $null = Show-TacVu $TK_CB
        Buoc 'Sao lưu (0.6)'
        $b = Get-ChildItem $Daily -Filter 'database_*.db' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
        if ($b) { Write-Host "    Mới nhất: $($b.Name) · $([math]::Round($b.Length / 1MB, 1)) MB · $($b.LastWriteTime)" }
        else { Canh "Chưa có bản sao lưu trong $Daily" }
        $l = Join-Path $Daily 'sao_luu.log'
        if (Test-Path $l) { Get-Content $l -Tail 3 -Encoding UTF8 | ForEach-Object { Write-Host "    $_" } }
        Buoc 'Cảnh báo online (0.7)'
        $c = Get-ChildItem $Baseline -Filter 'online_*.csv' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
        if ($c) { Write-Host "    Baseline cuối (giờ, online, còn kênh lệnh, tổng máy): $(Get-Content $c.FullName -Tail 1)" }
        else { Canh "Chưa có baseline trong $Baseline" }
        $e = Join-Path $Baseline 'canh_bao.log'
        if (Test-Path $e) { Write-Host '    Sự kiện gần nhất:'; Get-Content $e -Tail 5 -Encoding UTF8 | ForEach-Object { Write-Host "      $_" } }
        $k = Join-Path $Baseline 'canary_hosts.txt'
        if (Test-Path $k) { Write-Host "    Máy canary (miễn cảnh báo): $((Get-Content $k | Where-Object { $_.Trim() }) -join ', ')" }
        exit 0
    }

    'Go' {
        Buoc 'Gỡ 2 tác vụ'
        if (-not (Test-LaAdmin)) { Dung 'Cần PowerShell "Run as Administrator".' }
        foreach ($ten in @($TK_SL, $TK_CB)) {
            if (Get-ScheduledTask -TaskName $ten -ErrorAction SilentlyContinue) {
                Unregister-ScheduledTask -TaskName $ten -Confirm:$false
                Dat "Đã gỡ '$($ten)'"
            } else { Dat "Không có '$($ten)'" }
        }
        Write-Host "    Giữ nguyên: $Daily · $Baseline · $BiMat"
        exit 0
    }

    'CaiDat' {
        Buoc 'Kiểm điều kiện'
        if (-not (Test-LaAdmin)) { Dung 'Cần PowerShell "Run as Administrator".' }
        if (-not (Test-Path $Py)) { Dung "Không thấy Python của bản chạy Core: $Py" }
        foreach ($f in @('sao_luu_csdl_cu.py', 'canh_bao_online.py', 'lay_cau_hinh_cu.py')) {
            if (-not (Test-Path (Join-Path $NguonOps $f))) { Dung "Thiếu $f trong $NguonOps" }
        }
        Dat "Quyền Administrator · Python $Py · đủ 3 script"

        Buoc 'Thư mục + kho bí mật (chỉ SYSTEM + Administrators)'
        foreach ($d in @($Tools, $Daily, $Baseline, $BiMat)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        $icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'  # máy chủ thiếu System32 trong PATH
        $ErrorActionPreference = 'Continue'
        & $icacls $BiMat /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' 2>&1 | Out-Null
        $ma = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($ma -ne 0) { Dung "icacls lỗi (mã $ma) khi khoá quyền $BiMat" }
        Dat "$Tools · $Daily · $Baseline · $BiMat (đã khoá quyền)"

        $thieu = @($BI_MAT_TEP.Values | Where-Object { -not (Test-NoiDung (Join-Path $BiMat $_)) })
        if ($thieu) {
            $r = Invoke-PyRaw @((Join-Path $NguonOps 'lay_cau_hinh_cu.py'))
            if ($r.Ma -ne 0) { Dung 'Không đọc được cấu hình hệ cũ (lay_cau_hinh_cu.py lỗi).' }
            $cfg = $r.Out | ConvertFrom-Json
            foreach ($k in $BI_MAT_TEP.Keys) {
                $p = Join-Path $BiMat $BI_MAT_TEP[$k]
                if (Test-NoiDung $p) { continue }
                $v = [string]$cfg.$k
                if (-not $v.Trim()) { Dung "Hệ cũ không có giá trị cho $k — tự ghi 1 dòng vào $p rồi chạy lại." }
                Set-Content -Path $p -Value $v.Trim() -Encoding ASCII -NoNewline
                Dat "$($BI_MAT_TEP[$k]) lấy từ hệ cũ (dài $($v.Trim().Length) ký tự)"
            }
        } else { Dat 'Kho bí mật đã đủ 3 tệp (giữ nguyên)' }

        Buoc "Chép script vào $Tools"
        foreach ($f in @('sao_luu_csdl_cu.py', 'canh_bao_online.py')) { Copy-Item (Join-Path $NguonOps $f) $Tools -Force }
        Dat 'Đã chép (tác vụ chạy bản trong D:\Backup\tools, không phụ thuộc thư mục phát triển)'

        Buoc 'Đăng ký 2 tác vụ (SYSTEM)'
        $pr = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $a1 = New-ScheduledTaskAction -Execute $Py -Argument ('"{0}"' -f (Join-Path $Tools 'sao_luu_csdl_cu.py')) -WorkingDirectory $Tools
        $s1 = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
        Register-ScheduledTask -TaskName $TK_SL -Action $a1 -Trigger (New-ScheduledTaskTrigger -Daily -At $GioSaoLuu) `
            -Principal $pr -Settings $s1 -Description 'ITSupportPlatform - So tay 0.6: sao luu CSDL he cu (chi doc)' -Force | Out-Null
        $a2 = New-ScheduledTaskAction -Execute $Py -Argument ('"{0}"' -f (Join-Path $Tools 'canh_bao_online.py')) -WorkingDirectory $Tools
        $t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
        $s2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
        Register-ScheduledTask -TaskName $TK_CB -Action $a2 -Trigger $t2 -Principal $pr -Settings $s2 `
            -Description 'ITSupportPlatform - So tay 0.7: canh bao Telegram khi online tut (chi doc)' -Force | Out-Null
        $task = Get-ScheduledTask -TaskName $TK_CB
        if ($task.Triggers[0].Repetition.Duration) {  # phải lặp VÔ HẠN, không dừng sau 1 ngày
            $task.Triggers[0].Repetition.Duration = ''
            $task | Set-ScheduledTask | Out-Null
        }
        $rep = (Get-ScheduledTask -TaskName $TK_CB).Triggers[0].Repetition
        if ($rep.Interval -ne 'PT1M' -or $rep.Duration) { Dung "Lịch lặp sai (Interval=$($rep.Interval), Duration=$($rep.Duration))" }
        Dat "'$TK_SL' hằng ngày $GioSaoLuu · '$TK_CB' mỗi 1 phút, lặp vô hạn"

        Buoc 'Chạy thử sao lưu ngay'
        $tu = Get-Date
        Start-ScheduledTask -TaskName $TK_SL
        $kq = Wait-TacVu $TK_SL $tu 180
        $b = Join-Path $Daily ("database_{0:yyyyMMdd}.db" -f (Get-Date))
        if ($kq -ne 0 -or -not (Test-Path $b)) {
            Get-Content (Join-Path $Daily 'sao_luu.log') -Tail 3 -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
            Dung "Sao lưu không đạt (kết quả: $(if ($null -eq $kq) { 'quá giờ' } else { Get-KetQua $kq }))"
        }
        Dat "$(Split-Path $b -Leaf) · $([math]::Round((Get-Item $b).Length / 1MB, 1)) MB — $(Get-Content (Join-Path $Daily 'sao_luu.log') -Tail 1 -Encoding UTF8)"

        Buoc 'Gửi tin thử Telegram'
        $r = Invoke-PyRaw @((Join-Path $Tools 'canh_bao_online.py'), '--thu')
        if ($r.Ma -ne 0) { Dung 'Không gửi được tin thử Telegram (kiểm mạng ra Internet / token / chat).' }
        Dat 'Đã gửi — xem nhóm Telegram cảnh báo có tin "ITM: thử kênh cảnh báo online"'

        Buoc 'Chạy thử cảnh báo online ngay'
        $tu = Get-Date
        Start-ScheduledTask -TaskName $TK_CB
        $kq = Wait-TacVu $TK_CB $tu 90
        $c = Join-Path $Baseline ("online_{0:yyyyMMdd}.csv" -f (Get-Date))
        if ($kq -ne 0 -or -not (Test-Path $c)) {
            Get-Content (Join-Path $Baseline 'canh_bao.log') -Tail 3 -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
            Dung "Cảnh báo online không đạt (kết quả: $(if ($null -eq $kq) { 'quá giờ' } else { Get-KetQua $kq }))"
        }
        Dat "Gọi được hub · baseline (giờ, online, còn kênh lệnh, tổng máy): $(Get-Content $c -Tail 1)"

        Buoc 'Xong'
        Write-Host '    Kiểm lại bất cứ lúc nào (không cần Admin): ...\cai_dat_ops.ps1 -Lenh KiemTra'
        Write-Host "    Trước khi chuyển máy thử sang Core (Sổ tay 3.6): ghi tên máy vào $Baseline\canary_hosts.txt"
        exit 0
    }
}
