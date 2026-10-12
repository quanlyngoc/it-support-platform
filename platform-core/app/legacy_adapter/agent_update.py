"""Màn Quản trị → Cập nhật Agent (Sổ tay 8.4) — công cụ chính của GĐ10. Luật §0 (CLAUDE.md hệ cũ) áp TUYỆT ĐỐI.

Hai đường đưa bản mới xuống máy agent v2:
1. **Đẩy lệnh cài an toàn cho máy CHỌN** (hệ cũ `/api/update_now` → `/hubapi/push_update`): gửi action `powershell`
   (agent chạy quyền SYSTEM) chứa script ghi UPDATER ra đĩa rồi giao TASK SCHEDULER chạy ĐỘC LẬP — installer không bao
   giờ là con của agent (luật §0.2). Updater: tải bộ cài → KIỂM SHA-256 + size (hệ cũ chỉ kiểm "> 15 MB") → CHỈ KHI ĐÚNG
   mới dừng agent → cài → tạo lại task `PhenikaaITMonitor` nếu mất → bật agent → kiểm `Client_Manager.exe` đang chạy
   (§0.7). Tải lỗi / sai hash → GIỮ NGUYÊN agent cũ (§0.1). Tiến độ ("Download x%", "Update y%", "Successful",
   "Unsuccessful: lý do") POST về `/ps_bulk_result/<token>` — lưu MongoDB (A9), màn hình đọc lại theo từng máy.
   Script là bản chép `_PUSH_UPDATER_PS` / `_push_bootstrap_ps` của hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\app.py) —
   đã chạy thật trên fleet; chỉ đổi địa chỉ tải (Core qua Caddy :5443, cấu hình `AGENT_UPDATE_BASE`) + thêm kiểm hash.
2. **All Update** = cổng `update.all` của `/check_update` — agent ≥ 2.7.4.1 TỰ cập nhật bằng updater tách rời (client.py
   `_launch_detached_updater`). Bật chỉ được khi ĐÃ có ≥ CANARY_MIN máy online chạy đúng bản đang phát (§0.5–0.6: canary
   trước, có bằng chứng thực địa). Tắt (Dừng khẩn, §0.8) luôn được và xoá SẠCH cổng (all, máy, phòng, %).

Cài lại bản cũ: đẩy lệnh cài một bản trong kho (`releases.py`) — bị từ chối nếu cổng chia đợt vẫn đang mời máy đó lên
bản mới (máy sẽ tự lên lại ngay sau khi hạ). Mỗi đợt quá MANY máy phải xác nhận lại (§0.5: vài máy → 1 phòng →
nhiều phòng).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.legacy_adapter.identity import norm_host

CANARY_MIN = 2           # số máy online đã chạy đúng bản đang phát trước khi cho bật All Update
MANY = 40                # đợt lớn hơn phải xác nhận lại
BUSY = timedelta(minutes=20)   # máy có đợt cài đang chạy trong 20' → không đẩy chồng
PURPOSE = "agent_update"

# Bản chép _PUSH_UPDATER_PS (hệ cũ, đã chạy thật). Khác: $BASES/$URLS = Core; kiểm SHA-256 + size thay cho "> 15MB".
UPDATER_PS = r'''$ErrorActionPreference='Continue'
$APPDIR='C:\Program Files (x86)\PhenikaaIT'
$AGENT=Join-Path $APPDIR 'Client_Manager.exe'
$DIR='C:\ProgramData\PhenikaaIT'
$SETUP=Join-Path $DIR 'PhkUpd_Setup.exe'
$FLAG=Join-Path $DIR 'update.flag'
$LOG=Join-Path $DIR 'update.log'
$TOKEN='__TOKEN__'
$SHA='__SHA__'
$SIZE=__SIZE__
$BASES=@('__BASE__')
$URLS=@('__BASE__/download_setup__QUERY__')
function Log($m){ try{ "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $LOG -Append -Encoding ascii }catch{} }
function Rep($st,$txt,$to=10){
  if(-not $TOKEN){ return }
  $b=@{hostname=$env:COMPUTERNAME; status=$st; stdout=$txt} | ConvertTo-Json -Compress
  foreach($bb in $BASES){
    try{ Invoke-RestMethod -Method Post -Uri ($bb+'/ps_bulk_result/'+$TOKEN) -Body $b -ContentType 'application/json' -TimeoutSec $to | Out-Null; return }catch{}
  }
}
if(-not (Test-Path $DIR)){ New-Item -ItemType Directory -Path $DIR -Force | Out-Null }
try{ [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12 }catch{}
try{ [Net.ServicePointManager]::ServerCertificateValidationCallback={$true} }catch{}
Log "=== updater bat dau (Core day xuong, ban __VERSION__) ==="
Rep 'running' 'Download 0%'
function DL($u){
  $req=[Net.HttpWebRequest]::Create($u); $req.Timeout=30000; $req.ReadWriteTimeout=300000
  $res=$req.GetResponse(); $total=$res.ContentLength
  $in=$res.GetResponseStream(); $out=[IO.File]::Create($SETUP)
  $buf=New-Object byte[] 65536; $got=0; $last=0
  try{
    while(($n=$in.Read($buf,0,$buf.Length)) -gt 0){
      $out.Write($buf,0,$n); $got+=$n
      if($total -gt 0){ $pc=[int](100*$got/$total); if($pc -gt $last){ $last=$pc; Rep 'running' ("Download $pc%") 3 } }
    }
  } finally { $out.Close(); $in.Close(); $res.Close() }
  return $got
}
$ok=$false; $err='khong ro'
for($i=1;$i -le 12;$i++){
  foreach($u in $URLS){
    try{
      $got=DL $u
      $h=''
      try{ $h=(Get-FileHash -Path $SETUP -Algorithm SHA256).Hash.ToLower() }catch{ $h='' }
      if($got -eq $SIZE -and $h -eq $SHA){ $ok=$true; Log "tai xong lan $i tu $u ($got bytes, sha256 khop)"; break }
      $err="bo cai sai sha256/size ($got bytes)"; Log "lan ${i} $u -> $err"
    }catch{ $err=$_.Exception.Message; Log "lan ${i} $u -> $err" }
  }
  if($ok){ break }
  Start-Sleep -Seconds (10+(Get-Random -Minimum 0 -Maximum 15))
}
if(-not $ok){ Log "TAI THAT BAI -> GIU NGUYEN agent cu, khong dung toi"; Rep 'error' ("Unsuccessful: tai that bai - " + $err); Remove-Item $SETUP -Force -ErrorAction SilentlyContinue; schtasks /delete /tn PhenikaaITUpdate /f 2>$null | Out-Null; exit }
Rep 'running' 'Download 100% - Update 0%'
if(Get-Process -Name PhkUpd_Setup -ErrorAction SilentlyContinue){ Log "da co ban cai DANG CHAY -> thoat, khong dam chong (chong bam Update nhieu lan)"; exit }
Set-Content -Path $FLAG -Value (Get-Date) -ErrorAction SilentlyContinue
Stop-Process -Name Client_Manager -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
try{
  $p=Start-Process -FilePath $SETUP -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOCANCEL' -PassThru
  for($w=0; $w -lt 120; $w++){
    if($p.HasExited){ break }
    Set-Content -Path $FLAG -Value (Get-Date) -ErrorAction SilentlyContinue
    $up=[Math]::Min(95, 5+$w*3); Rep 'running' ("Download 100% - Update $up%") 3
    Start-Sleep -Seconds 5
  }
  if(-not $p.HasExited){ $p.WaitForExit(120000) | Out-Null }
  Log "installer exit=$($p.ExitCode)"
}catch{ Log "loi chay installer" }
Start-Sleep -Seconds 3
if(Test-Path $AGENT){
  $hasTask=$false
  try{ schtasks /query /tn PhenikaaITMonitor 2>$null | Out-Null; $hasTask=($LASTEXITCODE -eq 0) }catch{}
  if(-not $hasTask){
    try{
      $prn=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
      $set=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
      Register-ScheduledTask -TaskName 'PhenikaaITMonitor' -Action (New-ScheduledTaskAction -Execute $AGENT) -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $prn -Settings $set -Force | Out-Null
      Log "tao lai task PhenikaaITMonitor"
    }catch{ Log "loi tao task" }
  }
  for($k=1;$k -le 3;$k++){
    if(Get-Process -Name Client_Manager -ErrorAction SilentlyContinue){ break }
    schtasks /run /tn PhenikaaITMonitor 2>$null | Out-Null
    Start-Sleep -Seconds 5
    if(-not (Get-Process -Name Client_Manager -ErrorAction SilentlyContinue)){ Start-Process -FilePath $AGENT -WindowStyle Hidden -ErrorAction SilentlyContinue; Start-Sleep -Seconds 4 }
  }
} else { Log "!! KHONG thay agent sau cai" }
$run=[bool](Get-Process -Name Client_Manager -ErrorAction SilentlyContinue)
Remove-Item $SETUP -Force -ErrorAction SilentlyContinue
Remove-Item $FLAG -Force -ErrorAction SilentlyContinue
Log ("KET QUA agent chay=" + $run)
if($run){ Rep 'done' 'Successful' } else { Rep 'error' 'Unsuccessful: agent khong khoi dong lai' }
schtasks /delete /tn PhenikaaITUpdate /f 2>$null | Out-Null'''  # noqa: E501 — chép NGUYÊN VĂN script đã chạy thật


def updater_script(token: str, base: str, version: str, sha256: str, size: int, query: str = "") -> str:
    for v in (token, sha256, version):
        if not all(c.isalnum() or c == "." for c in v):
            raise ValueError("token / sha256 / phiên bản chứa ký tự lạ")  # chống chèn vào script PowerShell
    if "'" in base or not base.startswith(("https://", "http://")):
        raise ValueError("AGENT_UPDATE_BASE không hợp lệ")
    return (UPDATER_PS.replace("__TOKEN__", token).replace("__SHA__", sha256.lower())
            .replace("__SIZE__", str(int(size)))
            .replace("__BASE__", base.rstrip("/")).replace("__QUERY__", query).replace("__VERSION__", version))


def bootstrap_script(updater: str, base: str) -> str:
    """Bản chép `_push_bootstrap_ps`: ghi updater ra đĩa, giao Task Scheduler chạy ĐỘC LẬP (hẹn thêm 1 phút phòng khi
    `/run` hỏng), dò TCP tới cổng tải, báo thẳng nếu agent không chạy quyền SYSTEM. Trả về NGAY — agent vẫn sống."""
    u = urlparse(base)
    host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
    return ("$ErrorActionPreference='Continue'\n"
            "$d='C:\\ProgramData\\PhenikaaIT'\n"
            "if(-not(Test-Path $d)){ New-Item -ItemType Directory -Path $d -Force | Out-Null }\n"
            "$p=Join-Path $d 'do_update.ps1'\n"
            "$body=@'\n" + updater + "\n'@\n"
            "Set-Content -Path $p -Value $body -Encoding ascii\n"
            "schtasks /end /tn PhenikaaITUpdate 2>$null | Out-Null\n"
            "schtasks /delete /tn PhenikaaITUpdate /f 2>$null | Out-Null\n"
            "$st=(Get-Date).AddMinutes(1).ToString('HH:mm')\n"
            "$cr=(schtasks /create /tn PhenikaaITUpdate /tr \"powershell.exe -ExecutionPolicy Bypass "
            "-WindowStyle Hidden -NonInteractive -File $p\" /sc once /st $st /ru SYSTEM /rl HIGHEST /f 2>&1) "
            "-join ' '\n"
            "$crc=$LASTEXITCODE\n"
            "$rn=(schtasks /run /tn PhenikaaITUpdate 2>&1) -join ' '\n"
            "$rc=$LASTEXITCODE\n"
            "$diag=@()\n"
            f"foreach($pt in @({port})){{ try{{ $c=New-Object Net.Sockets.TcpClient; "
            f"$ia=$c.BeginConnect('{host}',$pt,$null,$null); "
            "$okp=$ia.AsyncWaitHandle.WaitOne(3000); $c.Close(); $diag+=\"${pt}=$okp\" }"
            "catch{ $diag+=\"${pt}=ERR\" } }\n"
            "$me=(whoami)\n"
            "if($crc -ne 0){\n"
            "  \"Unsuccessful: agent dang chay bang '$me' (khong phai SYSTEM) -> khong du quyen cai. \" +\n"
            "  \"Can chay lai agent bang quyen SYSTEM (tac vu PhenikaaITMonitor) roi update lai.\"\n"
            "  exit 1\n"
            "}\n"
            "\"PUSH-OK create=$crc run=$rc as=$me net: \" + ($diag -join ' ') + \" | run:\" + $rn\n")


# ====================================================================== diễn giải tiến độ
def stage(res: dict | None) -> dict:
    """Kết quả 1 máy trong đợt cài → {state: running|done|error|waiting, text}."""
    if not res:
        return {"state": "waiting", "text": "Đã gửi lệnh, chờ máy nhận"}
    out = str(res.get("stdout") or "").strip()
    if out.startswith("Successful"):
        return {"state": "done", "text": "Cài xong — agent đã chạy lại"}
    if out.startswith("Unsuccessful"):
        return {"state": "error", "text": out[:300]}
    if out.startswith("Download") or out.startswith("Update"):
        return {"state": "running", "text": out[:80]}
    if out.startswith("PUSH-OK"):
        return {"state": "running", "text": "Đã giao updater cho Task Scheduler — chờ tải"}
    err = str(res.get("stderr") or "").strip()
    if res.get("exit_code") not in (None, 0) or str(res.get("status")) == "error" or err:
        return {"state": "error", "text": (out or err or "Lỗi khi giao updater")[:300]}
    return {"state": "running", "text": out[:80] or "Đang xử lý"}


def latest_by_host(results_repo: Any, since: datetime) -> dict[str, dict]:
    """Đợt cài gần nhất của từng máy (trong khoảng `since`): {HOST: {token, at, version, mode, by, stage}}."""
    sessions = list(results_repo.find({"kind": "ps_bulk", "role": "session", "meta.purpose": PURPOSE,
                                       "created_at": {"$gte": since}}).sort("created_at", -1).limit(300))
    out: dict[str, dict] = {}
    for s in sessions:
        meta = s.get("meta") or {}
        pending = [h for h in meta.get("expected") or [] if h not in out]
        if not pending:
            continue
        res = {r["hostname"]: r for r in results_repo.find({"token": s["token"], "kind": "ps_bulk", "role": "result",
                                                             "hostname": {"$in": pending}})}
        at = s["created_at"] if s["created_at"].tzinfo else s["created_at"].replace(tzinfo=UTC)
        for h in pending:
            r = res.get(h)
            st = stage(r)
            if st["state"] == "running" and datetime.now(UTC) - at > timedelta(minutes=45):
                st = {"state": "error", "text": f"Quá 45 phút không báo xong (cuối: {st['text']})"}
            if st["state"] == "waiting" and datetime.now(UTC) - at > timedelta(minutes=15):
                st = {"state": "error", "text": "Máy không nhận lệnh trong 15 phút (mất kênh lệnh / tắt máy)"}
            upd = r.get("updated_at") if r else None
            out[h] = {"token": s["token"], "at": at.isoformat(), "version": meta.get("version"),
                      "mode": meta.get("mode"), "by": meta.get("by"),
                      "updated_at": upd.isoformat() if isinstance(upd, datetime) else None, **st}
    return out


def busy_hosts(results_repo: Any) -> set[str]:
    since = datetime.now(UTC) - BUSY
    return {h for h, v in latest_by_host(results_repo, since).items() if v["state"] in ("running", "waiting")}


def hosts_norm(hosts: list[str]) -> list[str]:
    return list(dict.fromkeys(h for h in (norm_host(x) for x in hosts) if h))
