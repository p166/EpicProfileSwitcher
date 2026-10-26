from __future__ import annotations

from pathlib import Path

import pytest

from epic_profile_switcher.service import EpicProfileService


class TestProtector:
    def protect(self, data: bytes) -> bytes:
        return b"protected:" + data

    def unprotect(self, data: bytes) -> bytes:
        assert data.startswith(b"protected:")
        return data.removeprefix(b"protected:")


def epic_ini(token: str, *section_ids: str) -> bytes:
    sections = "".join(f"\n[{section_id}_General]\nValue=1\n" for section_id in section_ids)
    return f"[RememberMe]\nData={token}\n{sections}".encode()


def build_service(tmp_path: Path, *, start=None) -> EpicProfileService:
    session = tmp_path / "live" / "GameUserSettings.ini"
    launcher = tmp_path / "EpicGamesLauncher.exe"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_bytes(b"test executable")
    session.parent.mkdir(parents=True)
    return EpicProfileService(
        root=tmp_path / "profiles-root",
        launcher_path=launcher,
        session_path=session,
        protector=TestProtector(),
        stop_launcher=lambda: None,
        start_launcher=start or (lambda _: None),
    )


def test_save_profile_and_detect_active_after_token_rotation(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    stable_id = "b7e74919ba4444309a5ef489321029dd"
    service.session_path.write_bytes(epic_ini("token-one", stable_id))

    profile = service.save_current_profile("Personal")
    service.session_path.write_bytes(epic_ini("rotated-token", stable_id))

    listed = service.list_profiles()
    assert len(listed) == 1
    assert listed[0].profile_id == profile.profile_id
    assert listed[0].active
    assert (service.profiles_dir / profile.profile_id / "session.ini.dpapi").read_bytes().startswith(b"protected:")


def test_active_detection_prioritizes_session_token_over_section_ids(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    first_id = "b7e74919ba4444309a5ef489321029dd"
    second_id = "7c2c913866fd455ea259b9f426417ecf"
    service.session_path.write_bytes(epic_ini("same-token", first_id))
    profile = service.save_current_profile("Personal")
    service.session_path.write_bytes(epic_ini("same-token", second_id))

    listed = service.list_profiles()

    assert listed[0].profile_id == profile.profile_id
    assert listed[0].active


def test_active_detection_uses_whole_file_hash_when_session_markers_are_missing(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.session_path.write_bytes(b"[EpicSettings]\nWindowPos=100,100\n")

    profile = service.save_current_profile("Settings-only")

    assert service.list_profiles()[0].profile_id == profile.profile_id
    assert service.list_profiles()[0].active


def test_profile_stays_active_when_ini_matches_after_launcher_closes(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.session_path.write_bytes(epic_ini("token-one"))
    profile = service.save_current_profile("Personal")
    assert service.session_path.is_file()
    assert service.list_profiles()[0].profile_id == profile.profile_id
    assert service.list_profiles()[0].active


def test_capture_same_account_updates_existing_profile(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    section_id = "7c2c913866fd455ea259b9f426417ecf"
    service.session_path.write_bytes(epic_ini("token-one", section_id))
    first = service.save_current_profile("Old name")
    service.session_path.write_bytes(epic_ini("token-two", section_id))

    updated = service.save_current_profile("New name")

    assert updated.profile_id == first.profile_id
    assert [profile.name for profile in service.list_profiles()] == ["New name"]


def test_switch_restores_profile_and_rolls_back_when_launcher_fails(tmp_path: Path) -> None:
    service = build_service(tmp_path, start=lambda _: (_ for _ in ()).throw(OSError("launch failed")))
    service.session_path.write_bytes(epic_ini("saved-token"))
    profile = service.save_current_profile("Saved")
    service.session_path.write_bytes(epic_ini("current-token"))

    with pytest.raises(OSError, match="launch failed"):
        service.switch_profile(profile.profile_id)

    assert service.session_path.read_bytes() == epic_ini("current-token")


def test_switch_does_not_replace_live_session_if_launcher_cannot_be_stopped(tmp_path: Path) -> None:
    started: list[Path] = []
    service = build_service(
        tmp_path,
        start=started.append,
    )
    service.session_path.write_bytes(epic_ini("saved-token"))
    profile = service.save_current_profile("Saved")
    current = epic_ini("current-token")
    service.session_path.write_bytes(current)
    service._stop_launcher = lambda: (_ for _ in ()).throw(OSError("access denied"))

    with pytest.raises(OSError, match="access denied"):
        service.switch_profile(profile.profile_id)

    assert service.session_path.read_bytes() == current
    assert not started


def test_new_login_restores_live_session_if_launcher_fails(tmp_path: Path) -> None:
    service = build_service(tmp_path, start=lambda _: (_ for _ in ()).throw(OSError("launch failed")))
    current = epic_ini("current-token")
    service.session_path.write_bytes(current)

    with pytest.raises(OSError, match="launch failed"):
        service.add_new_login()

    assert service.session_path.read_bytes() == current


def test_delete_profile_removes_only_saved_snapshot(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    live = epic_ini("current-token")
    service.session_path.write_bytes(live)
    profile = service.save_current_profile("Personal")

    service.delete_profile(profile.profile_id)

    assert not service.list_profiles()
    assert service.session_path.read_bytes() == live