# -*- coding: utf-8 -*-
"""Test cho hook rào chỉ đọc (.claude/hooks/guard_readonly.py). Chạy: python -m pytest platform-deployment/qa -q"""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "guard_readonly.py"
_spec = importlib.util.spec_from_file_location("guard_readonly", _P)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def deny(tool, **ti):
    return g.decide({"tool_name": tool, "tool_input": ti}) is not None


# ---------- Write / Edit ----------
def test_ghi_vao_du_an_cu_bi_chan():
    for p in [r"D:\NetworkInventory\app.py", "D:/NetworkInventory/app.py", "/d/NetworkInventory/app.py",
              r"d:\networkinventory\templates\x.html", r"D:\ExaminationSystem\app.py", r"D:\Agent\a.md",
              r"D:\Caddy\Caddyfile", r"D:\RemoteControl\relay.py", r"D:\NetworkInventory"]:
        assert deny("Write", file_path=p), p
        assert deny("Edit", file_path=p), p


def test_ghi_vao_du_an_moi_duoc_phep():
    for p in [r"D:\ITSupportPlatform\platform-core\app\x.py", r"D:\AgentX\a.txt", r"D:\Agents\a.txt",
              r"C:\Users\x\AppData\Local\Temp\a.txt", r"D:\Backup\Moc0\a.db"]:
        assert not deny("Write", file_path=p), p


def test_notebook():
    assert deny("NotebookEdit", notebook_path=r"D:\NetworkInventory\n.ipynb")


# ---------- Shell ----------
def test_lenh_doc_duoc_phep():
    for c in ["cat /d/NetworkInventory/app.py", "grep -n route D:/NetworkInventory/app.py",
              "git -C D:\\NetworkInventory status", "git -C /d/NetworkInventory log --oneline -5",
              "git -C /d/NetworkInventory diff", "python -c \"open(r'D:\\NetworkInventory\\app.py').read()\"",
              "ls /d/Caddy 2>/dev/null", "wc -l /d/NetworkInventory/app.py 2>&1",
              "cp /d/NetworkInventory/CLAUDE.md /d/ITSupportPlatform/docs/ref/",
              "Copy-Item D:\\NetworkInventory\\x.txt D:\\ITSupportPlatform\\docs\\x.txt",
              "robocopy D:\\NetworkInventory\\Maps D:\\ITSupportPlatform\\tmp /E /R:1"]:
        assert not deny("Bash", command=c), c


def test_lenh_ghi_bi_chan():
    for c in ["rm -rf /d/NetworkInventory/logs", "mv /d/Agent/a.md /d/Agent/b.md",
              "echo x > /d/NetworkInventory/a.txt", "echo x >> D:\\Caddy\\Caddyfile",
              "sed -i 's/a/b/' /d/NetworkInventory/app.py", "git -C /d/NetworkInventory commit -m x",
              "git -C D:\\NetworkInventory checkout -- app.py", "touch /d/ExaminationSystem/x",
              "Remove-Item D:\\NetworkInventory\\x.txt", "Set-Content D:\\Caddy\\Caddyfile 'x'",
              "cp a.txt /d/NetworkInventory/", "Copy-Item .\\a.txt D:\\RemoteControl\\a.txt",
              "mkdir /d/NetworkInventory/newdir"]:
        assert deny("Bash", command=c), c
    assert deny("PowerShell", command="Remove-Item D:\\Agent\\x.md")


def test_khong_nhac_du_an_cu_thi_khong_xet():
    assert not deny("Bash", command="rm -rf /d/ITSupportPlatform/platform-core/.pytest_cache")
