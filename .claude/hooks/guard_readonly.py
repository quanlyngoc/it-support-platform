# -*- coding: utf-8 -*-
"""Rào "dự án cũ CHỈ ĐỌC" cho Claude Code (hook PreToolUse).

Chặn mọi thao tác GHI vào hệ đang chạy: D:\\NetworkInventory, D:\\ExaminationSystem, D:\\Agent,
D:\\Caddy, D:\\RemoteControl. Đọc vẫn được (Read/Grep/Glob không đi qua hook này).
- Write/Edit/MultiEdit/NotebookEdit: đích nằm trong thư mục cũ -> deny.
- Bash/PowerShell: lệnh nhắc tới thư mục cũ VÀ có động tác ghi (xoá, chuyển, ghi đè, chuyển hướng
  vào đó, git làm đổi cây) -> deny. Lệnh chép TỪ thư mục cũ SANG nơi khác vẫn được phép.
Lỗi nội bộ của hook -> in stderr, thoát mã 1 (không chặn), để không làm treo phiên làm việc.
"""
import json
import re
import sys

PROTECTED = ["NetworkInventory", "ExaminationSystem", "Agent", "Caddy", "RemoteControl"]

# D:\X, D:/X, /d/X, //d/X (không phân biệt hoa/thường), kết thúc ở ranh giới đường dẫn
_ROOT_RE = re.compile(
    r"(?:[a-z]:[\\/]|/{1,2}d/)(" + "|".join(PROTECTED) + r")(?=$|[\\/\s\"'`;|&)>])",
    re.IGNORECASE,
)
_WRITE_VERBS = re.compile(
    r"(?:^|[\s;|&(])(rm|mv|del|erase|rmdir|rd|move|ren|rename|mkdir|md|touch|tee|truncate|"
    r"remove-item|move-item|rename-item|new-item|set-content|add-content|out-file|clear-content|"
    r"set-itemproperty|new-itemproperty|remove-itemproperty|icacls|attrib)(?=$|[\s;|&)])",
    re.IGNORECASE,
)
_COPY_VERBS = re.compile(r"(?:^|[\s;|&(])(cp|copy|xcopy|robocopy|copy-item)(?=$|[\s;|&)])", re.IGNORECASE)
_SED_INPLACE = re.compile(r"\bsed\s+(-[a-z]*i|--in-place)", re.IGNORECASE)
_GIT_MUTATE = re.compile(
    r"\bgit\b[^;|&]*\b(commit|reset|checkout|clean|stash|add|rm|mv|restore|switch|merge|pull|push|"
    r"apply|am|cherry-pick|rebase|revert|tag|init|gc|prune)\b",
    re.IGNORECASE,
)
_REDIRECT = re.compile(r"(?<![0-9&])>{1,2}\s*(\"[^\"]+\"|'[^']+'|[^\s;|&]+)")


def is_protected_path(p: str) -> bool:
    if not p:
        return False
    s = p.strip().strip("\"'")
    return bool(_ROOT_RE.search(s if s.endswith(("/", "\\")) else s + "\\"))


def _last_path_token(segment: str) -> str:
    """Tham số cuối không phải cờ (bỏ '-x', '--x', và cờ kiểu robocopy '/E', '/MIR', '/R:2')."""
    toks = re.findall(r"\"[^\"]*\"|'[^']*'|\S+", segment.strip())
    paths = [t for t in toks
             if not t.startswith("-") and not re.match(r"^/[A-Za-z]+(:\S*)?$", t)]
    return paths[-1] if paths else ""


def check_command(cmd: str):
    """Trả về lý do chặn (str) hoặc None nếu cho phép."""
    if not cmd or not _ROOT_RE.search(cmd):
        return None
    for m in _REDIRECT.finditer(cmd):
        if is_protected_path(m.group(1)):
            return "chuyển hướng ghi (>) vào thư mục của hệ đang chạy"
    if _SED_INPLACE.search(cmd):
        return "sed -i sửa tệp tại chỗ trong thư mục của hệ đang chạy"
    if _GIT_MUTATE.search(cmd):
        return "lệnh git làm thay đổi kho của hệ đang chạy"
    if _WRITE_VERBS.search(cmd):
        return "lệnh xoá/chuyển/tạo/ghi trong thư mục của hệ đang chạy"
    for seg in re.split(r"[;|&]+", cmd):
        if _COPY_VERBS.search(seg) and is_protected_path(_last_path_token(seg)):
            return "chép tệp VÀO thư mục của hệ đang chạy"
    return None


def decide(payload: dict):
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if is_protected_path(target):
            return f"{tool} vào {target}: dự án cũ chỉ đọc (CLAUDE.md §0 luật 14)"
        return None
    if tool in ("Bash", "PowerShell"):
        reason = check_command(ti.get("command", ""))
        if reason:
            return reason + " — dự án cũ chỉ đọc (CLAUDE.md §0 luật 14). Mã mới chỉ nằm trong D:\\ITSupportPlatform."
    return None


def main() -> int:
    # Windows mặc định cp1252: ép UTF-8 để lý do chặn tiếng Việt không làm hook vỡ đúng lúc cần chặn
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception as e:  # không chặn khi hook tự lỗi
        print(f"guard_readonly: không đọc được dữ liệu vào: {e}", file=sys.stderr)
        return 1
    reason = decide(payload)
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "deny",
                                          "permissionDecisionReason": reason}}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
