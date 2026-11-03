# Epic Profile Switcher

[English](README.md) | [Русский](README.ru.md)

A Windows desktop app for saving and switching Epic Games Launcher sessions.

## Features

- Save the current Epic session as a named profile.
- Switch profiles without blocking the interface. The app shows progress, reports when the launcher is starting, and rolls back the live session if the launcher cannot be started.
- Open a fresh Epic sign-in session.
- Rename and delete saved profiles.
- See the application version and open the project on GitHub from the main window.
- Keep dialogs centered over the main window.
- Encrypt saved session snapshots with Windows DPAPI for the current Windows user.
- Check GitHub Releases for updates, show download progress, verify the SHA-256 checksum, and restart with the new version.

## Requirements

- Windows
- Python 3.10 or newer

## Run from source

From the repository root, create and activate a virtual environment, install the development dependencies, and launch the app:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m epic_profile_switcher
```

Run the tests with:

```powershell
pytest -q
```

Automatic update checks are enabled only in the packaged Windows executable, not when running from source.

## Build the Windows executable

Make sure `python.exe` is available on `PATH`, then run this in PowerShell:

```powershell
.\build-windows.ps1
# Optional: keep a copy of the existing executable
.\build-windows.ps1 -Backup
```

The script creates or validates `.venv-windows` against the active Python version, installs the build dependencies, runs the tests, and builds a single-file, windowed executable at `dist/windows/EpicProfileSwitcher.exe`. Python is not required on the target computer. The first launch can take a little longer while bundled files are extracted to a temporary directory.

## Releases and automatic updates

The GitHub Actions release workflow runs when a `v*` tag is pushed. It can also be started manually with a tag. To publish a release:

1. Set `__version__` in `src/epic_profile_switcher/__init__.py`.
2. Push a matching tag, such as `v1.4` for version `1.4`, or manually run the **Windows release** workflow with that tag.
3. The workflow builds the executable and publishes both `EpicProfileSwitcher.exe` and `EpicProfileSwitcher.exe.sha256` to the GitHub Release.

The packaged app checks the latest GitHub Release. If a newer version is available, it offers **Update**, **Later**, and **Skip version**. A skipped version is remembered in the user's settings. When an update is accepted, the app displays download progress, verifies the downloaded executable against the release's SHA-256 checksum, closes, replaces itself, and restarts. The executable must be in a folder where the current Windows user can write.

## Profile storage and encryption

Profiles are stored under `%LOCALAPPDATA%\EpicProfileSwitcher\profiles\<profile-id>`. Each saved session is stored as `session.ini.dpapi` and protected with Windows Data Protection API (DPAPI), using `CryptProtectData` and `CryptUnprotectData` with the current Windows user's default scope. The app does not ask for a separate password or store its own encryption key; Windows manages the key material.

Only the saved session snapshot is encrypted. The accompanying `profile.json` metadata is readable and contains the profile name, creation time, account section identifiers, and hashes used to identify the active profile. Do not treat profile names or this metadata as secret.

When a profile is switched, the app decrypts its snapshot and writes the session data to Epic's normal live session file so the launcher can use it. That live file is not encrypted by Epic Profile Switcher. The plaintext session is also necessarily present in memory while it is being saved or restored.

DPAPI protects saved snapshots from users or processes that cannot access the current Windows user's DPAPI data. It is not protection against malware or another program running as that same user, which may be able to ask Windows to decrypt the data. Saved snapshots generally cannot be decrypted after moving them to another computer or Windows account. If the Windows account's DPAPI data is lost or becomes unavailable, the snapshots may no longer be recoverable.

## Epic Games Launcher location

The app detects standard install folders and Windows uninstall registry entries. If Epic was installed in a custom location that is not registered, use **Browse…** to select `EpicGamesLauncher.exe`.
