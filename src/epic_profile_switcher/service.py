"""Epic launcher discovery and profile snapshot operations."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .protection import DpapiProtector

DATA_PATTERN = re.compile(rb"(?m)^Data=(\S.*)\r?$")
SECTION_PATTERN = re.compile(rb"(?mi)^\[([0-9a-f]{32})_")
LAUNCHER_RELATIVE = Path("Epic Games/Launcher/Portal/Binaries")


class Protector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


@dataclass(frozen=True)
class Profile:
    profile_id: str
    name: str
    created_at: str
    active: bool = False


def _default_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "EpicProfileSwitcher"
    return Path.home() / ".local" / "share" / "EpicProfileSwitcher"


def _existing_session_path() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    config = local_app_data / "EpicGamesLauncher" / "Saved" / "Config"
    candidates = [
        config / "Windows" / "GameUserSettings.ini",
        config / "WindowsEditor" / "GameUserSettings.ini",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _launcher_candidates() -> list[Path]:
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    candidates = [
        Path(root) / LAUNCHER_RELATIVE / architecture / "EpicGamesLauncher.exe"
        for root in roots
        if root
        for architecture in ("Win64", "Win32")
    ]
    return candidates


def _registry_launcher_candidates() -> list[Path]:
    if os.name != "nt":
        return []

    import winreg

    roots = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    access_modes = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    found: list[Path] = []
    for root in roots:
        for view in access_modes:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root, 0, winreg.KEY_READ | view) as key:
                    subkey_count = winreg.QueryInfoKey(key)[0]
                    for index in range(subkey_count):
                        try:
                            name = winreg.EnumKey(key, index)
                            with winreg.OpenKey(key, name) as entry:
                                display_name = winreg.QueryValueEx(entry, "DisplayName")[0]
                                if "epic games launcher" not in str(display_name).casefold():
                                    continue
                                try:
                                    install_location = Path(winreg.QueryValueEx(entry, "InstallLocation")[0])
                                    found.extend(
                                        install_location / "Launcher/Portal/Binaries" / architecture / "EpicGamesLauncher.exe"
                                        for architecture in ("Win64", "Win32")
                                    )
                                except (FileNotFoundError, TypeError, ValueError):
                                    pass
                                try:
                                    icon = str(winreg.QueryValueEx(entry, "DisplayIcon")[0]).strip().strip('"')
                                    icon_path = Path(icon.rsplit(",", 1)[0] if "," in icon else icon)
                                    if icon_path.name.casefold() == "epicgameslauncher.exe":
                                        found.append(icon_path)
                                except (FileNotFoundError, TypeError, ValueError):
                                    pass
                        except (OSError, IndexError):
                            continue
            except OSError:
                continue
    return found


def detect_launcher() -> Path | None:
    candidates = [*_launcher_candidates(), *_registry_launcher_candidates()]
    return next((path for path in candidates if path.is_file()), None)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _session_identity(content: bytes) -> tuple[str | None, str, tuple[str, ...]]:
    data_match = DATA_PATTERN.search(content)
    data_hash = hashlib.sha256(data_match.group(1)).hexdigest() if data_match else None
    whole_file_hash = hashlib.sha256(content).hexdigest()
    section_ids = tuple(sorted(set(SECTION_PATTERN.findall(content))))
    return data_hash, whole_file_hash, tuple(value.decode("ascii") for value in section_ids)


class EpicProfileService:
    def __init__(
        self,
        root: Path | None = None,
        launcher_path: Path | None = None,
        session_path: Path | None = None,
        protector: Protector | None = None,
        stop_launcher: Callable[[], None] | None = None,
        start_launcher: Callable[[Path], None] | None = None,
    ) -> None:
        self.root = root or _default_root()
        self.profiles_dir = self.root / "profiles"
        self.settings_path = self.root / "settings.json"
        self._protector = protector or DpapiProtector()
        saved_settings = self._read_settings()
        saved_launcher = saved_settings.get("launcher_path")
        self.launcher_path = launcher_path or (Path(saved_launcher) if saved_launcher else detect_launcher())
        self.session_path = session_path or _existing_session_path()
        self._stop_launcher = stop_launcher or self._stop_epic
        self._start_launcher = start_launcher or self._start_epic
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _read_settings(self) -> dict[str, str]:
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_launcher_path(self, path: Path) -> None:
        self.launcher_path = path
        settings = self._read_settings()
        settings["launcher_path"] = str(path)
        _atomic_write(self.settings_path, json.dumps(settings, indent=2).encode("utf-8"))

    def list_profiles(self) -> list[Profile]:
        current_identity: tuple[str | None, str, tuple[str, ...]] | None = None
        if self.session_path.is_file():
            current_identity = _session_identity(self.session_path.read_bytes())

        profiles: list[Profile] = []
        for profile_dir in self.profiles_dir.iterdir():
            metadata_path = profile_dir / "profile.json"
            encrypted_path = profile_dir / "session.ini.dpapi"
            if not profile_dir.is_dir() or not metadata_path.is_file() or not encrypted_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                stored_ids = tuple(metadata.get("section_ids", []))
                stored_data_hash = metadata.get("data_hash")
                stored_whole_hash = metadata.get("whole_file_hash")
                active = False
                if current_identity is not None:
                    current_data_hash, current_whole_hash, current_ids = current_identity
                    active = bool(current_data_hash and current_data_hash == stored_data_hash)
                    if not active:
                        active = current_whole_hash == stored_whole_hash
                    if not active and current_ids and stored_ids:
                        active = current_ids == stored_ids
                profiles.append(
                    Profile(
                        profile_id=str(metadata["id"]),
                        name=str(metadata["name"]),
                        created_at=str(metadata["created_at"]),
                        active=active,
                    )
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(profiles, key=lambda profile: (profile.name.casefold(), profile.profile_id))

    def save_current_profile(self, name: str) -> Profile:
        name = name.strip()
        if not name:
            raise ValueError("Enter a name for this profile.")
        if not self.session_path.is_file():
            raise FileNotFoundError("Epic session file was not found. Sign in to Epic first.")

        content = self.session_path.read_bytes()
        data_hash, whole_file_hash, section_ids = _session_identity(content)

        matching = next(
            (
                profile
                for profile in self._profile_metadata()
                if (section_ids and tuple(profile.get("section_ids", [])) == section_ids)
                or (data_hash and profile.get("data_hash") == data_hash)
                or whole_file_hash == profile.get("whole_file_hash")
            ),
            None,
        )
        profile_id = str(matching["id"]) if matching else uuid.uuid4().hex
        created_at = matching["created_at"] if matching else datetime.now(timezone.utc).isoformat()
        profile_dir = self.profiles_dir / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(profile_dir / "session.ini.dpapi", self._protector.protect(content))
        metadata = {
            "id": profile_id,
            "name": name,
            "created_at": created_at,
            "data_hash": data_hash,
            "whole_file_hash": whole_file_hash,
            "section_ids": list(section_ids),
        }
        _atomic_write(profile_dir / "profile.json", json.dumps(metadata, indent=2).encode("utf-8"))
        return Profile(profile_id, name, created_at, active=True)

    def rename_profile(self, profile_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Profile name cannot be empty.")
        profile_dir = self._profile_dir(profile_id)
        metadata_path = profile_dir / "profile.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["name"] = name
        _atomic_write(metadata_path, json.dumps(metadata, indent=2).encode("utf-8"))

    def delete_profile(self, profile_id: str) -> None:
        shutil.rmtree(self._profile_dir(profile_id))

    def switch_profile(self, profile_id: str) -> None:
        if self.launcher_path is None or not self.launcher_path.is_file():
            raise FileNotFoundError("Select the Epic Games Launcher executable first.")
        profile_file = self._profile_dir(profile_id) / "session.ini.dpapi"
        target_content = self._protector.unprotect(profile_file.read_bytes())
        old_content = self.session_path.read_bytes() if self.session_path.is_file() else None

        self._stop_launcher()
        _atomic_write(self.session_path, target_content)
        try:
            self._start_launcher(self.launcher_path)
        except Exception:
            if old_content is None:
                self.session_path.unlink(missing_ok=True)
            else:
                _atomic_write(self.session_path, old_content)
            raise

    def add_new_login(self) -> None:
        if self.launcher_path is None or not self.launcher_path.is_file():
            raise FileNotFoundError("Select the Epic Games Launcher executable first.")
        old_content = self.session_path.read_bytes() if self.session_path.is_file() else None
        self._stop_launcher()
        self.session_path.unlink(missing_ok=True)
        try:
            self._start_launcher(self.launcher_path)
        except Exception:
            if old_content is not None:
                _atomic_write(self.session_path, old_content)
            raise

    def _profile_dir(self, profile_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", profile_id):
            raise ValueError("Invalid profile identifier.")
        profile_dir = self.profiles_dir / profile_id
        if not profile_dir.is_dir():
            raise FileNotFoundError("Profile not found.")
        return profile_dir

    def _profile_metadata(self) -> list[dict[str, object]]:
        metadata: list[dict[str, object]] = []
        for path in self.profiles_dir.glob("*/profile.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and (path.parent / "session.ini.dpapi").is_file():
                    metadata.append(value)
            except (OSError, json.JSONDecodeError):
                continue
        return metadata

    @staticmethod
    def _stop_epic() -> None:
        if os.name != "nt":
            raise OSError("Stopping Epic Games Launcher is supported only on Windows.")

        def is_running() -> bool:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq EpicGamesLauncher.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=True,
            )
            return any(
                row and row[0].casefold() == "epicgameslauncher.exe"
                for row in csv.reader(result.stdout.splitlines())
            )

        if not is_running():
            return

        result = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "EpicGamesLauncher.exe"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and is_running():
            raise RuntimeError(result.stderr.strip() or "Could not stop Epic Games Launcher.")

        deadline = time.monotonic() + 15
        while is_running():
            if time.monotonic() >= deadline:
                raise TimeoutError("Epic Games Launcher did not close within 15 seconds.")
            time.sleep(0.25)

    @staticmethod
    def _start_epic(path: Path) -> None:
        subprocess.Popen([str(path)], close_fds=True)