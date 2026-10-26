# Epic Profile Switcher

A small Windows desktop app for saving and switching Epic Games Launcher sessions.

## Features

- Save the current Epic session as a named profile.
- Switch profiles by closing the launcher, replacing its session file, and reopening it.
- Start a fresh Epic sign-in session.
- Rename and delete saved profiles.
- Encrypt session snapshots with Windows DPAPI, scoped to the current Windows user.
- Roll back the live session file if Epic cannot be started after a switch.

## Run from source

Requires Windows and Python 3.10 or newer.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m epic_profile_switcher
```

Run service tests with:

```powershell
pytest
```

## Build the Windows executable

On Windows, install Python 3.10 or newer with the Python Launcher (`py.exe`), then run the build script in PowerShell:

```powershell
.\build-windows.ps1
# Optional: keep a copy of the existing executable
.\build-windows.ps1 -Backup
```

The script runs the tests and builds a single-file executable at `dist/windows/EpicProfileSwitcher.exe`. Python is not required on the target computer. The first launch can take a little longer because the bundled files are extracted to a temporary directory.

Profiles are stored under `%LOCALAPPDATA%\EpicProfileSwitcher\profiles`. The session INI copies are encrypted for the current Windows account; profile names and account section identifiers are kept as metadata. Epic's live session file remains managed by Epic in its normal config folder.

The app detects standard install folders and Windows uninstall registry entries. If Epic was installed in a custom location that is not registered, use **Browse…** to select `EpicGamesLauncher.exe`.