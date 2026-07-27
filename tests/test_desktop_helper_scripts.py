from pathlib import Path


def test_install_desktop_helper_task_script_is_helper_only() -> None:
    script = Path("scripts/install_desktop_browser_helper_task.ps1")

    text = script.read_text(encoding="utf-8")

    assert "content_pipeline.diagnostics desktop-helper" in text
    assert "127.0.0.1" in text
    assert "8767" in text
    assert "WindowsIdentity" in text
    assert "New-ScheduledTaskPrincipal" in text
    assert "Interactive" in text
    assert "Limited" in text
    assert "Register-ScheduledTask" in text
    assert "Start-Process" not in text
    assert "chrome.exe" not in text.lower()
    assert "gemini.google.com" not in text.lower()


def test_uninstall_desktop_helper_task_script_removes_only_named_task() -> None:
    script = Path("scripts/uninstall_desktop_browser_helper_task.ps1")

    text = script.read_text(encoding="utf-8")

    assert '"AI Popline Desktop Browser Helper"' in text
    assert "Unregister-ScheduledTask" in text
    assert "Remove-Item" not in text
    assert "Start-Process" not in text
