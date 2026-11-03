from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from urllib.request import Request

import pytest

from epic_profile_switcher import updater


def release(tag: str) -> bytes:
    assets = [
        {
            "name": updater.EXECUTABLE_NAME,
            "browser_download_url": "https://github.com/p166/EpicProfileSwitcher/releases/download/v1.1/EpicProfileSwitcher.exe",
        },
        {
            "name": updater.CHECKSUM_NAME,
            "browser_download_url": "https://github.com/p166/EpicProfileSwitcher/releases/download/v1.1/EpicProfileSwitcher.exe.sha256",
        },
    ]
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def test_check_for_update_returns_newer_github_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "_read_url", lambda *_args, **_kwargs: release("v1.1"))

    result = updater.check_for_update("1.0")

    assert result is not None
    assert result.version == "v1.1"
    assert result.executable_url.endswith("/EpicProfileSwitcher.exe")
    assert result.checksum_url.endswith("/EpicProfileSwitcher.exe.sha256")


def test_check_for_update_ignores_equal_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "_read_url", lambda *_args, **_kwargs: release("v1.0.0"))

    assert updater.check_for_update("1.0") is None


def test_check_for_update_rejects_non_github_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.loads(release("v1.1"))
    data["assets"][0]["browser_download_url"] = "https://example.com/EpicProfileSwitcher.exe"
    monkeypatch.setattr(updater, "_read_url", lambda *_args, **_kwargs: json.dumps(data).encode())

    with pytest.raises(ValueError, match="invalid EpicProfileSwitcher.exe download URL"):
        updater.check_for_update("1.0")


def test_download_update_checks_sha256_and_stages_beside_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = b"new executable"
    checksum = hashlib.sha256(binary).hexdigest().encode()
    monkeypatch.setattr(updater, "_read_url", lambda *_args, **_kwargs: checksum)

    class Response(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.headers = {"Content-Length": str(len(data))}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    def open_url(request: Request, timeout: int) -> Response:
        assert request.full_url == "https://github.com/p166/app.exe"
        assert timeout == 30
        return Response(binary)

    monkeypatch.setattr(updater.urllib.request, "urlopen", open_url)
    target = tmp_path / updater.EXECUTABLE_NAME
    target.write_bytes(b"old executable")
    progress: list[tuple[int, int | None]] = []

    staged = updater.download_update(
        updater.UpdateInfo("v1.1", "https://github.com/p166/app.exe", "https://github.com/p166/app.sha256"),
        target,
        progress=lambda downloaded, total: progress.append((downloaded, total)),
    )

    assert staged.parent == tmp_path
    assert staged.read_bytes() == binary
    assert target.read_bytes() == b"old executable"
    assert progress == [(0, len(binary)), (len(binary), len(binary))]


def test_download_update_removes_bad_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(updater, "_read_url", lambda *_args, **_kwargs: b"0" * 64)

    class Response(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.headers = {"Content-Length": str(len(data))}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(b"tampered"))
    target = tmp_path / updater.EXECUTABLE_NAME
    target.write_bytes(b"old executable")

    with pytest.raises(ValueError, match="failed its SHA-256 check"):
        updater.download_update(
            updater.UpdateInfo("v1.1", "https://github.com/p166/app.exe", "https://github.com/p166/app.sha256"),
            target,
        )

    assert list(tmp_path.iterdir()) == [target]


def test_launch_updater_tolerates_application_already_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "updater.ps1"
    started: list[list[str]] = []

    def create_script(*, prefix: str, suffix: str) -> tuple[int, str]:
        assert prefix == "epic-profile-updater-"
        assert suffix == ".ps1"
        return os.open(script_path, os.O_CREAT | os.O_RDWR), str(script_path)

    monkeypatch.setattr(updater.tempfile, "mkstemp", create_script)
    monkeypatch.setattr(
        updater.subprocess,
        "Popen",
        lambda arguments, **_kwargs: started.append(arguments),
    )

    updater.launch_updater(tmp_path / "staged.exe", tmp_path / "app.exe", 123)

    script = script_path.read_text(encoding="utf-8")
    assert "Get-Process -Id $ProcessId -ErrorAction SilentlyContinue" in script
    assert "Wait-Process -Id" not in script
    assert "[System.IO.File]::Replace($StagedPath, $TargetPath, $BackupPath)" in script
    assert '$env:PYINSTALLER_RESET_ENVIRONMENT = "1"' in script
    assert started
