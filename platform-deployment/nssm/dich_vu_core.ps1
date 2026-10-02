<#
.SYNOPSIS
  Cài / kiểm / cập nhật / gỡ dịch vụ Windows "PlatformCore" bằng NSSM (Sổ tay bước 2.11).

.DESCRIPTION
  Dịch vụ chạy Core từ BẢN SAO RIÊNG (mặc định D:\ITSupportPlatformRun, nhánh main), KHÔNG chạy thẳng từ thư mục
  phát triển D:\ITSupportPlatform — để việc sửa mã / cài thư viện khi phát triển không khoá tệp của dịch vụ đang chạy.

  Phạm vi: CHỈ đụng dịch vụ PlatformCore. Không đụng CaddyServer, PhenikaaAgentHub, PhenikaaMonitorUI hay bất kỳ dịch vụ
  nào của hệ cũ. Core chỉ nghe 127.0.0.1:7009 và Caddy chưa trỏ gì tới cổng này → máy trạm/agent KHÔNG bị ảnh hưởng.

  Không tin mã thoát của nssm (bài học hệ cũ 10.17): mọi bước đều kiểm lại bằng Get-Service + registry + gọi /api/health.

.EXAMPLE
  # Mở PowerShell bằng "Run as Administrator" rồi chạy:
  powershell -ExecutionPolicy Bypass -File D:\ITSupportPlatform\platform-deployment\nssm\dich_vu_core.ps1 -Lenh CaiDat

  -Lenh KiemTra   xem trạng thái (KHÔNG cần Administrator)
  -Lenh CapNhat   dừng → lấy mã mới nhất nhánh main từ D:\ITSupportPlatform → cài thư viện → bật lại (lỗi thì quay về bản cũ)
  -Lenh Go        dừng + gỡ dịch vụ (giữ nguyên thư mục chạy và nhật ký)
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('CaiDat', 'KiemTra', 'CapNhat', 'Go')]
    [string]$Lenh,
    [string]$NguonRepo = 'D:\ITSupportPlatform',
    [string]$ThuMucChay = 'D:\ITSupportPlatformRun',
    # HOAN_BAO_MAT: giai đoạn dựng thử dùng chung .env của thư mục phát triển; khi chạy thật chuyển ra thư mục bí mật riêng
    [string]$TepEnv = 'D:\ITSupportPlatform\platform-core\.env',
    [int]$Cong = 7009,
    [string]$Nssm = 'C:\Program Files\NSSM\nssm.exe',
    [string]$Uv = '',
    [switch]$BoQuaThuTuHoi
)

$ErrorActionPreference = 'Stop'
$TenDV = 'PlatformCore'
$CoreDir = Join-Path $ThuMucChay 'platform-core'
$Py = Join-Path $CoreDir '.venv\Scripts\python.exe'
$LogDir = Join-Path $ThuMucChay 'logs'
$HealthUrl = "http://127.0.0.1:$Cong/api/health"
$RegParams = "HKLM:\SYSTEM\CurrentControlSet\Services\$TenDV\Parameters"
$EnvMongMuon = @("DOTENV_PATH=$TepEnv", 'PYTHONIOENCODING=utf-8', 'PYTHONUNBUFFERED=1', 'HOST=127.0.0.1', "PORT=$Cong")
[System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy  # gọi 127.0.0.1 trực tiếp, không qua proxy hệ thống

function Buoc([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Dat([string]$m) { Write-Host "    [ĐẠT] $m" -ForegroundColor Green }
function Canh([string]$m) { Write-Host "    [!]   $m" -ForegroundColor Yellow }
function Dung([string]$m) { Write-Host "    [X]   $m" -ForegroundColor Red; exit 1 }

function Test-LaAdmin {
    $p = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-DichVu { Get-Service -Name $TenDV -ErrorAction SilentlyContinue }

function Invoke-Ngoai([string]$exe, [string[]]$thamSo, [switch]$Im) {
    # Gọi chương trình ngoài, chỉ dựa vào MÃ THOÁT. EAP cục bộ = Continue: git/uv in tiến độ ra stderr, PowerShell 5.1
    # (nhất là ISE) sẽ biến dòng đó thành lỗi dừng script nếu để 'Stop'.
    $ErrorActionPreference = 'Continue'
    if ($Im) { & $exe @thamSo 2>&1 | Out-Null } else { & $exe @thamSo | Out-Host }
    return $LASTEXITCODE
}

function Invoke-Nssm {
    # nssm 2.24 in chữ dạng UTF-16 khi bị chuyển hướng → không đọc chữ của nó; mã thoát chỉ là tín hiệu phụ,
    # cấu hình thật được đọc lại từ registry sau khi cài.
    $code = Invoke-Ngoai $Nssm ([string[]]$args) -Im
    if ($code -ne 0) { Dung "nssm $($args -join ' ') trả mã $code" }
}

function Find-Exe([string]$ten, [string[]]$ungVien) {
    $tu = Get-Command $ten -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
    $c = @($ungVien + $tu) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $c) { Dung "Không tìm thấy $ten.exe" }
    return $c
}

function Find-Uv {
    return Find-Exe 'uv' @($Uv, (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        'C:\Users\anh.nguyennhuhoang\.local\bin\uv.exe')
}

function Find-Git { return Find-Exe 'git' @('C:\Program Files\Git\cmd\git.exe') }

function Get-Commit([string]$repo, [string]$ref = 'HEAD') {
    $ErrorActionPreference = 'Continue'
    $g = Find-Git
    $c = & $g -c safe.directory=* -C $repo rev-parse --short $ref 2>$null
    if ($LASTEXITCODE -ne 0) { return '?' }
    return "$c".Trim()
}

function Get-SucKhoe([switch]$Db) {
    $u = $HealthUrl
    if ($Db) { $u += '?db=1' }
    try {
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 25
        return [pscustomobject]@{ Ma = [int]$r.StatusCode; Than = ($r.Content | ConvertFrom-Json) }
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { return $null }
        $txt = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd()
        $than = $null
        try { $than = $txt | ConvertFrom-Json } catch { $than = $null }
        return [pscustomobject]@{ Ma = [int]$resp.StatusCode; Than = $than }
    } catch {
        return $null
    }
}

function Get-ChuCong {
    Get-NetTCPConnection -LocalPort $Cong -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Wait-SanSang([int]$Giay = 60, [int]$PidCu = 0) {
    # Sẵn sàng = có tiến trình MỚI (khác $PidCu) nghe cổng VÀ /api/health trả 200
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Giay) {
        $l = Get-ChuCong
        if ($l -and $l.OwningProcess -ne $PidCu) {
            $h = Get-SucKhoe
            if ($h -and $h.Ma -eq 200) {
                return [pscustomobject]@{ Pid = $l.OwningProcess; Giay = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Show-NhatKy([int]$Dong = 20) {
    foreach ($f in @('core-err.log', 'core-out.log')) {
        $p = Join-Path $LogDir $f
        if (Test-Path $p) {
            Write-Host "    --- $p (cuối $Dong dòng) ---" -ForegroundColor DarkGray
            Get-Content $p -Tail $Dong -Encoding UTF8 | ForEach-Object { Write-Host "    $_" }
        }
    }
}

function Test-NapMa {
    # Nạp thử mã + thư viện bằng đúng python của dịch vụ (không chạy server)
    Push-Location $CoreDir
    try { $code = Invoke-Ngoai $Py @('-c', 'import app.server') } finally { Pop-Location }
    return ($code -eq 0)
}

function Sync-ThuVien {
    $u = Find-Uv
    Push-Location $CoreDir
    try { $code = Invoke-Ngoai $u @('sync', '--no-dev', '--locked') } finally { Pop-Location }
    if ($code -ne 0) { throw "uv sync lỗi (mã $code)" }
}

function Initialize-BanChay {
    if (-not (Test-Path (Join-Path $ThuMucChay '.git'))) {
        if (Test-Path $ThuMucChay) { Dung "$ThuMucChay đã có nhưng không phải bản sao git — kiểm tay rồi đổi tên/xoá." }
        Buoc "Tạo bản sao chạy: $NguonRepo (main) → $ThuMucChay"
        $g = Find-Git
        $code = Invoke-Ngoai $g @('-c', 'safe.directory=*', 'clone', '--branch', 'main', $NguonRepo, $ThuMucChay)
        if ($code -ne 0) { Dung 'git clone lỗi' }
    }
    if (-not (Test-Path $Py)) {
        Buoc 'Cài thư viện cho bản chạy (uv sync --no-dev --locked)'
        Sync-ThuVien
    }
}

function Start-VaCho([int]$Giay = 90) {
    Invoke-Nssm start $TenDV
    $s = Wait-SanSang -Giay $Giay
    if (-not $s) {
        Canh "Sau $Giay s dịch vụ chưa trả lời $HealthUrl. Trạng thái: $((Get-DichVu).Status)"
        Show-NhatKy
        Dung 'Dịch vụ không lên. Sửa theo nhật ký trên rồi chạy -Lenh KiemTra (hoặc -Lenh Go để gỡ).'
    }
    Dat "Dịch vụ trả lời sau $($s.Giay) s (PID nghe cổng $Cong = $($s.Pid))"
    return $s
}

function Test-Csdl {
    $h = Get-SucKhoe -Db
    if ($h -and $h.Ma -eq 200) { Dat "Kết nối CSDL từ tài khoản dịch vụ: ping $($h.Than.db_ms) ms"; return $true }
    $loi = if ($h -and $h.Than) { $h.Than.db_error } else { 'không trả lời' }
    Canh "Dịch vụ chạy nhưng KHÔNG tới được CSDL ($loi). Kiểm: Atlas → Network Access có IP máy chủ; DNS; MONGO_URI trong $TepEnv"
    return $false
}

# ============================================================================================================== lệnh
switch ($Lenh) {

    'KiemTra' {
        Buoc "Dịch vụ $TenDV"
        $dv = Get-DichVu
        if (-not $dv) { Canh 'Chưa cài. Chạy -Lenh CaiDat bằng PowerShell quyền Administrator.'; exit 1 }
        Write-Host "    Trạng thái: $($dv.Status) · Khởi động: $($dv.StartType)"
        $p = Get-ItemProperty $RegParams -ErrorAction SilentlyContinue
        if ($p) {
            Write-Host "    Chạy: $($p.Application) $($p.AppParameters)"
            Write-Host "    Thư mục: $($p.AppDirectory)"
            Write-Host "    Biến môi trường: $(@($p.AppEnvironmentExtra) -join ' · ')"
        }
        Buoc 'Phiên bản mã'
        $chay = Get-Commit $ThuMucChay
        $nguon = Get-Commit $NguonRepo 'main'
        Write-Host "    Bản đang chạy: $chay · main ở thư mục phát triển: $nguon"
        if ($chay -ne $nguon) { Canh 'Bản chạy khác main → muốn lên bản mới: -Lenh CapNhat (quyền Administrator).' }
        Buoc "Cổng $Cong + sức khoẻ"
        $l = Get-ChuCong
        if (-not $l) { Canh "Không có tiến trình nào nghe cổng $Cong"; Show-NhatKy; exit 1 }
        Write-Host "    Nghe $($l.LocalAddress):$Cong — PID $($l.OwningProcess)"
        $h = Get-SucKhoe
        if (-not $h -or $h.Ma -ne 200) { Canh "$HealthUrl không trả 200"; Show-NhatKy; exit 1 }
        Dat "Core $($h.Than.version) đang chạy"
        if (-not (Test-Csdl)) { exit 1 }
        Show-NhatKy -Dong 5
        exit 0
    }

    'CaiDat' {
        Buoc 'Kiểm điều kiện'
        if (-not (Test-LaAdmin)) { Dung 'Cần PowerShell "Run as Administrator".' }
        if (-not (Test-Path $Nssm)) { Dung "Không thấy NSSM tại $Nssm" }
        if (Get-DichVu) { Dung "Dịch vụ $TenDV đã có. Dùng -Lenh KiemTra / -Lenh CapNhat, hoặc -Lenh Go rồi cài lại." }
        if (-not (Test-Path $TepEnv)) { Dung "Không thấy tệp cấu hình $TepEnv" }
        if (-not (Select-String -Path $TepEnv -Pattern '^\s*MONGO_URI\s*=\s*\S' -Quiet)) { Dung "$TepEnv thiếu MONGO_URI" }
        $l = Get-ChuCong
        if ($l) { Dung "Cổng $Cong đang bị PID $($l.OwningProcess) giữ (có thể là bản chạy thử) — tắt nó trước." }
        Dat 'Quyền Administrator · NSSM · tệp .env có MONGO_URI · cổng trống'

        Initialize-BanChay
        if (-not (Test-NapMa)) { Dung "Python của bản chạy không nạp được mã ($Py)" }
        Dat "Bản chạy $ThuMucChay @ $(Get-Commit $ThuMucChay) nạp mã được"
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

        Buoc "Cài dịch vụ $TenDV"
        Invoke-Nssm install $TenDV $Py
        Invoke-Nssm set $TenDV AppParameters '-m app.server'
        Invoke-Nssm set $TenDV AppDirectory $CoreDir
        Invoke-Nssm set $TenDV DisplayName 'Phenikaa Platform Core'
        Invoke-Nssm set $TenDV Description 'ITSupportPlatform - Platform-Core (dung thu, 127.0.0.1:7009). Khong lien quan he cu.'
        Invoke-Nssm set $TenDV Start SERVICE_DELAYED_AUTO_START
        Invoke-Nssm set $TenDV ObjectName LocalSystem
        Invoke-Nssm set $TenDV AppStdout (Join-Path $LogDir 'core-out.log')
        Invoke-Nssm set $TenDV AppStderr (Join-Path $LogDir 'core-err.log')
        Invoke-Nssm set $TenDV AppRotateFiles 1
        Invoke-Nssm set $TenDV AppRotateOnline 1
        Invoke-Nssm set $TenDV AppRotateBytes 10485760
        Invoke-Nssm set $TenDV AppEnvironmentExtra @EnvMongMuon
        Invoke-Nssm set $TenDV AppExit Default Restart
        Invoke-Nssm set $TenDV AppRestartDelay 5000

        # Đọc lại registry thay vì tin nssm
        $p = Get-ItemProperty $RegParams
        $thieu = @($EnvMongMuon | Where-Object { @($p.AppEnvironmentExtra) -notcontains $_ })
        if ($p.Application -ne $Py -or $p.AppParameters -ne '-m app.server' -or $p.AppDirectory -ne $CoreDir -or $thieu) {
            Dung "Cấu hình dịch vụ trong registry không khớp (thiếu: $($thieu -join ', ')). Gỡ bằng -Lenh Go rồi cài lại."
        }
        Dat 'Cấu hình dịch vụ khớp (đọc lại từ registry)'

        Buoc 'Bật dịch vụ'
        $s = Start-VaCho
        $csdlOk = Test-Csdl

        if (-not $BoQuaThuTuHoi) {
            Buoc 'Thử tự hồi: giết tiến trình Core, chờ NSSM bật lại'
            Stop-Process -Id $s.Pid -Force
            $s2 = Wait-SanSang -Giay 60 -PidCu $s.Pid
            if (-not $s2) { Show-NhatKy; Dung 'Sau 60 s dịch vụ KHÔNG tự lên lại.' }
            Dat "Tự lên lại sau $($s2.Giay) s (đã gồm 5 s chờ của NSSM) — PID mới $($s2.Pid)"
        }

        Buoc 'Xong'
        Write-Host "    API:       http://127.0.0.1:$Cong/docs   (chỉ mở được trên chính máy chủ)"
        Write-Host "    Nhật ký:   $LogDir\core-out.log · core-err.log (tự xoay vòng 10 MB)"
        Write-Host "    Kiểm lại:  ...\dich_vu_core.ps1 -Lenh KiemTra"
        if (-not $csdlOk) { exit 1 }
        exit 0
    }

    'CapNhat' {
        Buoc 'Kiểm điều kiện'
        if (-not (Test-LaAdmin)) { Dung 'Cần PowerShell "Run as Administrator".' }
        if (-not (Get-DichVu)) { Dung "Chưa có dịch vụ $TenDV — chạy -Lenh CaiDat." }
        $cu = Get-Commit $ThuMucChay
        $moi = Get-Commit $NguonRepo 'main'
        Write-Host "    Đang chạy $cu → main $moi"
        if ($cu -eq $moi) { Dat 'Đã là bản mới nhất, không làm gì.'; exit 0 }

        Buoc 'Dừng dịch vụ'
        $null = Invoke-Ngoai $Nssm @('stop', $TenDV) -Im
        for ($i = 0; $i -lt 30 -and (Get-DichVu).Status -ne 'Stopped'; $i++) { Start-Sleep -Seconds 1 }
        if ((Get-DichVu).Status -ne 'Stopped') { Dung 'Dịch vụ không dừng sau 30 s — chưa đổi gì.' }
        Dat 'Đã dừng'

        Buoc "Lấy mã mới + cài thư viện"
        $g = Find-Git
        $loi = $null
        try {
            $code = Invoke-Ngoai $g @('-c', 'safe.directory=*', '-C', $ThuMucChay, 'pull', '--ff-only', 'origin', 'main')
            if ($code -ne 0) { throw 'git pull lỗi' }
            Sync-ThuVien
            if (-not (Test-NapMa)) { throw 'bản mới không nạp được mã' }
        } catch {
            $loi = "$_"
        }
        if ($loi) {
            # Fail-safe: quay về đúng bản đang chạy trước đó rồi bật lại — không để Core nằm chết
            Canh "Cập nhật lỗi: $loi → quay về $cu"
            $null = Invoke-Ngoai $g @('-c', 'safe.directory=*', '-C', $ThuMucChay, 'reset', '--hard', $cu) -Im
            try { Sync-ThuVien } catch { Canh "uv sync khi quay về cũng lỗi: $_" }
        }

        Buoc 'Bật lại dịch vụ'
        Start-VaCho | Out-Null
        $csdlOk = Test-Csdl
        if ($loi) { Dung "Đang chạy lại bản cũ $(Get-Commit $ThuMucChay). Xem lỗi phía trên." }
        Dat "Đã lên $(Get-Commit $ThuMucChay)"
        if (-not $csdlOk) { exit 1 }
        exit 0
    }

    'Go' {
        Buoc "Gỡ dịch vụ $TenDV"
        if (-not (Test-LaAdmin)) { Dung 'Cần PowerShell "Run as Administrator".' }
        if (-not (Get-DichVu)) { Dat 'Không có dịch vụ này — không cần gỡ.'; exit 0 }
        $null = Invoke-Ngoai $Nssm @('stop', $TenDV) -Im
        Invoke-Nssm remove $TenDV confirm
        Start-Sleep -Seconds 2
        if (Get-DichVu) { Dung 'Dịch vụ vẫn còn (có thể đang mở services.msc — đóng lại rồi chạy lại).' }
        Dat "Đã gỡ. Thư mục chạy $ThuMucChay và nhật ký được giữ nguyên."
        exit 0
    }
}
