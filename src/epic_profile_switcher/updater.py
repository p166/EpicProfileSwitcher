"""GitHub release checks and Windows executable updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = "p166/EpicProfileSwitcher"
EXECUTABLE_NAME = "EpicProfileSwitcher.exe"
CHECKSUM_NAME = f"{EXECUTABLE_NAME}.sha256"
MAX_DOWNLOAD_SIZE = 256 * 1024 * 1024
_USER_AGENT = "EpicProfileSwitcher-Updater"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    executable_url: str
    checksum_url: str


def _version_parts(version: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,2})", version)
    if match is None:
        raise ValueError(f"Unsupported release version: {version}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (3 - len(parts))


def _asset_url(assets: object, name: str) -> str:
    if not isinstance(assets, list):
        raise ValueError("The GitHub release has an invalid asset list.")
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == name:
            url = asset.get("browser_download_url")
            parsed = urllib.parse.urlparse(url) if isinstance(url, str) else None
            if parsed is None or parsed.scheme != "https" or parsed.hostname != "github.com":
                raise ValueError(f"The release contains an invalid {name} download URL.")
            return url
    raise ValueError(f"The release is missing {name}.")


def _read_url(url: str, *, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("The downloaded file exceeds the allowed size.")
    return data


def check_for_update(current_version: str) -> UpdateInfo | None:
    data = _read_url(
        f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
        limit=2 * 1024 * 1024,
    )
    release = json.loads(data)
    if not isinstance(release, dict):
        raise ValueError("GitHub returned an invalid release response.")
    version = release.get("tag_name")
    if not isinstance(version, str):
        raise ValueError("The GitHub release has no version tag.")
    if _version_parts(version) <= _version_parts(current_version):
        return None

    assets = release.get("assets")
    return UpdateInfo(
        version=version,
        executable_url=_asset_url(assets, EXECUTABLE_NAME),
        checksum_url=_asset_url(assets, CHECKSUM_NAME),
    )


def download_update(update: UpdateInfo, target_path: Path) -> Path:
    target_path = target_path.resolve()
    checksum_data = _read_url(update.checksum_url, limit=1024).decode("ascii")
    match = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_data)
    if match is None:
        raise ValueError("The release checksum file is invalid.")
    expected_hash = match.group(1).lower()

    descriptor, staged_name = tempfile.mkstemp(
        prefix=".EpicProfileSwitcher-update-",
        suffix=".exe",
        dir=target_path.parent,
    )
    staged_path = Path(staged_name)
    digest = hashlib.sha256()
    size = 0
    try:
        request = urllib.request.Request(
            update.executable_url,
            headers={"User-Agent": _USER_AGENT},
        )
        with os.fdopen(descriptor, "wb") as staged_file:
            with urllib.request.urlopen(request, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_SIZE:
                        raise ValueError("The update exceeds the allowed size.")
                    digest.update(chunk)
                    staged_file.write(chunk)
        if digest.hexdigest() != expected_hash:
            raise ValueError("The downloaded update failed its SHA-256 check.")
        return staged_path
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise


def launch_updater(staged_path: Path, target_path: Path, process_id: int) -> None:
    descriptor, script_name = tempfile.mkstemp(prefix="epic-profile-updater-", suffix=".ps1")
    os.close(descriptor)
    script_path = Path(script_name)
    try:
        script_path.write_text(
            """param(
    [Parameter(Mandatory = $true)][string]$StagedPath,
    [Parameter(Mandatory = $true)][string]$TargetPath,
    [Parameter(Mandatory = $true)][int]$ProcessId
)

try {
    Wait-Process -Id $ProcessId -ErrorAction Stop
    [System.IO.File]::Replace($StagedPath, $TargetPath, $null)
    Start-Process -FilePath $TargetPath
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "The update could not be installed: $($_.Exception.Message)",
        "Epic Profile Switcher",
        "OK",
        "Error"
    ) | Out-Null
    exit 1
} finally {
    Remove-Item -LiteralPath $StagedPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
""",
            encoding="utf-8",
        )
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                str(staged_path),
                str(target_path),
                str(process_id),
            ],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        script_path.unlink(missing_ok=True)
        raise
