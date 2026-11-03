"""Tkinter user interface for Epic profile management."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Literal, TypeVar

from . import __version__
from .service import EpicProfileService, Profile
from .updater import UpdateInfo, check_for_update, download_update, launch_updater

PROJECT_URL = "https://github.com/p166/EpicProfileSwitcher"
_DialogResult = TypeVar("_DialogResult")


def _center_native_dialogs(owner_hwnd: int, stop_event: threading.Event) -> None:
    import ctypes
    from ctypes import wintypes

    class Rect(ctypes.Structure):
        _fields_ = (
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        )

    user32 = ctypes.windll.user32
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    owner_rect = Rect()
    if not user32.GetWindowRect(owner_hwnd, ctypes.byref(owner_rect)):
        return

    def center_owned_window(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or int(user32.GetWindow(hwnd, 4) or 0) != owner_hwnd:
            return True
        dialog_rect = Rect()
        if not user32.GetWindowRect(hwnd, ctypes.byref(dialog_rect)):
            return True

        x = owner_rect.left + (
            (owner_rect.right - owner_rect.left) - (dialog_rect.right - dialog_rect.left)
        ) // 2
        y = owner_rect.top + (
            (owner_rect.bottom - owner_rect.top) - (dialog_rect.bottom - dialog_rect.top)
        ) // 2
        centered = user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)
        return not centered

    callback = enum_proc_type(center_owned_window)
    while not stop_event.is_set():
        if not user32.EnumWindows(callback, 0):
            return
        stop_event.wait(0.025)


def _run_centered_dialog(parent: tk.Misc, show_dialog: Callable[[], _DialogResult]) -> _DialogResult:
    if os.name != "nt":
        return show_dialog()

    owner_hwnd = int(parent.winfo_toplevel().wm_frame(), 0)
    stop_event = threading.Event()
    centerer = threading.Thread(
        target=_center_native_dialogs,
        args=(owner_hwnd, stop_event),
        daemon=True,
    )
    centerer.start()
    try:
        return show_dialog()
    finally:
        stop_event.set()
        centerer.join()


def _center_toplevel(parent: tk.Misc, dialog: tk.Toplevel) -> None:
    parent.update_idletasks()
    dialog.update_idletasks()
    screen_left = parent.winfo_vrootx()
    screen_top = parent.winfo_vrooty()
    screen_right = screen_left + parent.winfo_vrootwidth()
    screen_bottom = screen_top + parent.winfo_vrootheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
    x = min(max(x, screen_left), max(screen_left, screen_right - dialog.winfo_width()))
    y = min(max(y, screen_top), max(screen_top, screen_bottom - dialog.winfo_height()))
    dialog.geometry(f"+{x}+{y}")


class MainWindow(tk.Tk):
    def __init__(self, service: EpicProfileService) -> None:
        super().__init__()
        self.service = service
        self._profiles: dict[str, Profile] = {}
        self._profile_ids: list[str] = []
        self._update_checks: queue.Queue[UpdateInfo | Exception | None] = queue.Queue()
        self._download_results: queue.Queue[Path | Exception] = queue.Queue()
        self._download_progress: queue.Queue[tuple[int, int | None]] = queue.Queue()
        self._switch_status_updates: queue.Queue[str] = queue.Queue()
        self._switch_results: queue.Queue[Exception | None] = queue.Queue()
        self._update_check_pending = False
        self._download_pending = False
        self._switch_pending = False
        self._profile_selection_color = "#1769aa"
        self._switch_animation_after: str | None = None
        self.title("Epic Profile Switcher")
        self.geometry("760x560")
        self.minsize(600, 440)
        self.iconbitmap(default=str(Path(__file__).with_name("app.ico")))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f5f7")
        style.configure("TLabel", background="#f4f5f7", foreground="#20242b")
        style.configure("Heading.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", foreground="#626b78", font=("Segoe UI", 9))
        style.configure(
            "Link.TButton",
            background="#f4f5f7",
            foreground="#1769aa",
            borderwidth=0,
            padding=0,
            relief="flat",
            font=("Segoe UI", 9, "underline"),
        )
        style.map(
            "Link.TButton",
            background=[("active", "#f4f5f7")],
            foreground=[("active", "#104e7a")],
        )
        style.configure(
            "TButton",
            background="#ffffff",
            foreground="#20242b",
            bordercolor="#cbd1d8",
            lightcolor="#ffffff",
            darkcolor="#cbd1d8",
            padding=(13, 9),
            relief="flat",
            borderwidth=1,
            font=("Segoe UI", 9),
        )
        style.map(
            "TButton",
            background=[("disabled", "#f4f5f7"), ("pressed", "#dfe3e8"), ("active", "#edf0f3")],
            foreground=[("disabled", "#9ba2ab")],
            bordercolor=[("active", "#b9c2cb")],
        )
        style.configure(
            "Primary.TButton",
            background="#1769aa",
            foreground="#ffffff",
            bordercolor="#1769aa",
            lightcolor="#1769aa",
            darkcolor="#1769aa",
            padding=(13, 9),
            relief="flat",
            borderwidth=1,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("disabled", "#94aec4"), ("pressed", "#104e7a"), ("active", "#12598f")],
            foreground=[("disabled", "#f4f5f7")],
            bordercolor=[("disabled", "#94aec4"), ("!disabled", "#1769aa")],
        )

        root = ttk.Frame(self, padding=(24, 22))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        ttk.Label(root, text="Epic profiles", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 14)
        )
        header_links = ttk.Frame(root)
        header_links.grid(row=0, column=1, sticky="e", pady=(0, 14))
        ttk.Label(header_links, text=f"Version {__version__}", style="Muted.TLabel").pack(
            side="left"
        )
        ttk.Button(
            header_links,
            text="GitHub",
            style="Link.TButton",
            command=self._open_project_page,
        ).pack(side="left", padx=(12, 0))

        path_row = ttk.Frame(root)
        path_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        path_row.columnconfigure(0, weight=1)
        self.path_label = ttk.Label(path_row, style="Muted.TLabel")
        self.path_label.grid(row=0, column=0, sticky="w")
        self.browse_button = ttk.Button(path_row, text="Browse...", command=self._browse_launcher)
        self.browse_button.grid(row=0, column=1, padx=(12, 0))

        list_frame = ttk.Frame(root)
        list_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.profile_list = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            activestyle="none",
            background="white",
            foreground="#20242b",
            selectbackground=self._profile_selection_color,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#d7dce2",
            highlightcolor="#1769aa",
            borderwidth=0,
            font=("Segoe UI", 12),
            relief="flat",
        )
        self.profile_list.grid(row=0, column=0, sticky="nsew")
        self.profile_list.bind("<<ListboxSelect>>", self._update_buttons)
        self.profile_list.bind("<Double-Button-1>", lambda _: self._switch_profile())
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.profile_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.profile_list.configure(yscrollcommand=scrollbar.set)

        self.status_label = ttk.Label(root, style="Muted.TLabel", wraplength=660)
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 12))

        self.download_progress = ttk.Progressbar(root, mode="indeterminate", maximum=100)
        self._progress_mode = "indeterminate"
        self.switch_progress = ttk.Progressbar(root, mode="indeterminate", maximum=100)

        actions = ttk.Frame(root)
        actions.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.save_button = ttk.Button(actions, text="Save current", command=self._save_current)
        self.save_button.pack(side="left")
        self.switch_button = ttk.Button(
            actions,
            text="Switch to selected",
            command=self._switch_profile,
            style="Primary.TButton",
        )
        self.switch_button.pack(side="left", padx=(8, 0))

        secondary = ttk.Frame(root)
        secondary.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.add_login_button = ttk.Button(secondary, text="Add another login", command=self._add_login)
        self.add_login_button.pack(side="left")
        self.delete_button = ttk.Button(secondary, text="Delete", command=self._delete_profile)
        self.delete_button.pack(side="right")
        self.rename_button = ttk.Button(secondary, text="Rename", command=self._rename_profile)
        self.rename_button.pack(side="right", padx=(0, 8))

        self._refresh()
        self._refresh_active_markers()
        if os.name == "nt" and getattr(sys, "frozen", False):
            self._update_check_pending = True
            self.after(250, self._poll_update_results)
            threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _check_for_updates(self) -> None:
        try:
            self._update_checks.put(check_for_update(__version__))
        except Exception as error:
            self._update_checks.put(error)

    def _poll_update_results(self) -> None:
        if self._switch_pending:
            if self._update_check_pending or self._download_pending:
                self.after(250, self._poll_update_results)
            return

        latest_progress: tuple[int, int | None] | None = None
        while True:
            try:
                latest_progress = self._download_progress.get_nowait()
            except queue.Empty:
                break
        if latest_progress is not None:
            self._show_download_progress(*latest_progress)

        try:
            result = self._update_checks.get_nowait()
        except queue.Empty:
            pass
        else:
            self._update_check_pending = False
            if isinstance(result, Exception):
                self.status_label.configure(text=f"Update check failed: {result}")
            elif result is not None and self.service.get_skipped_update_version() != result.version:
                action = self._ask_update_action(result.version)
                if action == "skip":
                    try:
                        self.service.skip_update_version(result.version)
                    except Exception as error:
                        self._show_error_dialog("Could not skip version", str(error))
                    else:
                        self.status_label.configure(text=f"Version {result.version} skipped.")
                elif action == "update":
                    self._start_update_download(result)

        try:
            download_result = self._download_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._download_pending = False
            if isinstance(download_result, Exception):
                self._hide_download_progress()
                self._update_buttons()
                self._show_error_dialog("Update failed", str(download_result))
            else:
                try:
                    launch_updater(download_result, Path(sys.executable), os.getpid(), os.getppid())
                except Exception as error:
                    download_result.unlink(missing_ok=True)
                    self._hide_download_progress()
                    self._update_buttons()
                    self._show_error_dialog("Update failed", str(error))
                else:
                    self.destroy()
                    return

        if self._update_check_pending or self._download_pending:
            self.after(250, self._poll_update_results)

    def _ask_update_action(self, version: str) -> Literal["update", "later", "skip"]:
        dialog = tk.Toplevel(self)
        dialog.title("Update available")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        action: Literal["update", "later", "skip"] = "later"

        content = ttk.Frame(dialog, padding=18)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=f"Version {version} is available.").pack(anchor="w", pady=(0, 16))

        buttons = ttk.Frame(content)
        buttons.pack(fill="x")

        def finish(selection: Literal["update", "later", "skip"]) -> None:
            nonlocal action
            action = selection
            dialog.destroy()

        ttk.Button(
            buttons,
            text="Update",
            command=lambda: finish("update"),
            style="Primary.TButton",
        ).pack(side="left")
        ttk.Button(buttons, text="Later", command=lambda: finish("later")).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="Skip version", command=lambda: finish("skip")).pack(
            side="left", padx=(8, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish("later"))
        dialog.bind("<Escape>", lambda _event: finish("later"))
        _center_toplevel(self, dialog)
        self.wait_window(dialog)
        return action

    def _start_update_download(self, update: UpdateInfo) -> None:
        self._download_pending = True
        self._update_buttons()
        self.status_label.configure(text=f"Downloading version {update.version}...")
        self.download_progress.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 12),
        )
        self.download_progress.start(10)
        threading.Thread(
            target=self._download_update,
            args=(update,),
            daemon=True,
        ).start()

    def _show_download_progress(self, downloaded: int, total: int | None) -> None:
        if not self.download_progress.winfo_manager():
            self.download_progress.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        downloaded_mb = downloaded / (1024 * 1024)
        if total is None:
            self.status_label.configure(text=f"Downloading update: {downloaded_mb:.1f} MB")
            return

        if self._progress_mode == "indeterminate":
            self.download_progress.stop()
            self.download_progress.configure(mode="determinate")
            self._progress_mode = "determinate"
        self.download_progress.configure(maximum=max(total, 1), value=downloaded)
        total_mb = total / (1024 * 1024)
        percent = min(100, downloaded * 100 // max(total, 1))
        self.status_label.configure(
            text=f"Downloading update: {percent}% ({downloaded_mb:.1f} / {total_mb:.1f} MB)"
        )

    def _hide_download_progress(self) -> None:
        self.download_progress.stop()
        self.download_progress.grid_remove()
        self.download_progress.configure(mode="indeterminate", value=0)
        self._progress_mode = "indeterminate"

    def _download_update(self, update: UpdateInfo) -> None:
        try:
            result = download_update(
                update,
                Path(sys.executable),
                progress=lambda downloaded, total: self._download_progress.put((downloaded, total)),
            )
        except Exception as error:
            self._download_results.put(error)
        else:
            self._download_results.put(result)

    def _refresh(self, status: str = "") -> None:
        selected = self._selected_profile()
        selected_id = selected.profile_id if selected else None
        self._profiles = {profile.profile_id: profile for profile in self.service.list_profiles()}
        self._profile_ids = list(self._profiles)
        self.profile_list.delete(0, tk.END)
        for profile_id in self._profile_ids:
            profile = self._profiles[profile_id]
            marker = "  ·  Active" if profile.active else ""
            self.profile_list.insert(tk.END, f"{profile.name}{marker}")
        if selected_id in self._profile_ids:
            index = self._profile_ids.index(selected_id)
            self.profile_list.selection_set(index)
            self.profile_list.activate(index)

        launcher_path = self.service.launcher_path
        self.path_label.configure(
            text=f"Launcher: {launcher_path}" if launcher_path else "Epic Launcher not found"
        )
        if not status:
            status = (
                "Session profiles are encrypted for this Windows user."
                if self._profiles
                else "Save the current Epic session to create your first profile."
            )
        self.status_label.configure(text=status)
        self._update_buttons()

    def _selected_profile(self) -> Profile | None:
        selection = self.profile_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self._profile_ids):
            return None
        return self._profiles.get(self._profile_ids[index])

    def _refresh_active_markers(self) -> None:
        if self._switch_pending:
            self.after(2000, self._refresh_active_markers)
            return

        self._profiles = {profile.profile_id: profile for profile in self.service.list_profiles()}
        selection = self.profile_list.curselection()
        for index, profile_id in enumerate(self._profile_ids):
            profile = self._profiles.get(profile_id)
            if profile is not None:
                marker = "  ·  Active" if profile.active else ""
                self.profile_list.delete(index)
                self.profile_list.insert(index, f"{profile.name}{marker}")
        if selection:
            self.profile_list.selection_set(selection[0])
        self.after(2000, self._refresh_active_markers)

    def _update_buttons(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self._switch_animation_after is not None:
            self.after_cancel(self._switch_animation_after)
            self._switch_animation_after = None
            self.profile_list.configure(selectbackground=self._profile_selection_color)
        selected = self._selected_profile() is not None and not (
            self._switch_pending or self._download_pending
        )
        self.switch_button.configure(state="normal" if selected else "disabled")
        self.rename_button.configure(state="normal" if selected else "disabled")
        self.delete_button.configure(state="normal" if selected else "disabled")

    def _set_profile_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for control in (
            self.profile_list,
            self.browse_button,
            self.save_button,
            self.add_login_button,
        ):
            control.configure(state=state)
        if enabled:
            self._update_buttons()
        else:
            self.switch_button.configure(state="disabled")
            self.rename_button.configure(state="disabled")
            self.delete_button.configure(state="disabled")

    def _animate_profile_switch(self, profile_id: str) -> None:
        colors = ("#1769aa", "#2586ad", "#3b986f", "#2586ad", "#1769aa")

        def show_frame(frame: int) -> None:
            self._switch_animation_after = None
            selected = self._selected_profile()
            if selected is None or selected.profile_id != profile_id:
                self.profile_list.configure(selectbackground=self._profile_selection_color)
                return

            self.profile_list.configure(selectbackground=colors[frame])
            if frame + 1 < len(colors):
                self._switch_animation_after = self.after(90, lambda: show_frame(frame + 1))

        show_frame(0)

    def _browse_launcher(self) -> None:
        selected = _run_centered_dialog(
            self,
            lambda: filedialog.askopenfilename(
                parent=self,
                title="Select Epic Games Launcher",
                initialdir=str(Path.home()),
                filetypes=(("Epic Games Launcher", "EpicGamesLauncher.exe"),),
            ),
        )
        if selected:
            try:
                self.service.save_launcher_path(Path(selected))
                self._refresh("Launcher path saved.")
            except Exception as error:
                self._show_error(error)

    def _open_project_page(self) -> None:
        try:
            opened = webbrowser.open_new_tab(PROJECT_URL)
        except Exception as error:
            self._show_error(error)
            return
        if not opened:
            self._show_error_dialog(
                "Could not open GitHub",
                "The project page could not be opened in a browser.",
            )

    def _save_current(self) -> None:
        name = _run_centered_dialog(
            self,
            lambda: simpledialog.askstring(
                "Save current profile",
                "Profile name:",
                parent=self,
            ),
        )
        if name is None:
            return
        try:
            profile = self.service.save_current_profile(name.strip())
            self._refresh(f"Saved profile: {profile.name}")
        except Exception as error:
            self._show_error(error)

    def _switch_profile(self) -> None:
        if self._switch_pending or self._download_pending:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        if not self._ask_yes_no(
            "Switch Epic profile",
            f"Close Epic Games Launcher and switch to '{profile.name}'?",
        ):
            return
        self._switch_pending = True
        self._set_profile_controls_enabled(False)
        self.status_label.configure(text=f"Switching to {profile.name}...")
        self.switch_progress.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 12),
        )
        self.switch_progress.start(10)
        try:
            threading.Thread(
                target=self._switch_profile_worker,
                args=(profile.profile_id,),
                name="profile-switch",
                daemon=False,
            ).start()
        except Exception as error:
            self._switch_pending = False
            self.switch_progress.stop()
            self.switch_progress.grid_remove()
            self._set_profile_controls_enabled(True)
            self.status_label.configure(text=f"Could not start switching to {profile.name}.")
            self._show_error(error)
            return
        self.after(100, lambda: self._poll_switch_results(profile))

    def _switch_profile_worker(self, profile_id: str) -> None:
        try:
            self.service.switch_profile(
                profile_id,
                on_launcher_start=lambda: self._switch_status_updates.put(
                    "Starting Epic Games Launcher..."
                ),
            )
        except Exception as error:
            self._switch_results.put(error)
        else:
            self._switch_results.put(None)

    def _poll_switch_results(self, profile: Profile) -> None:
        status_updated = False
        while True:
            try:
                status = self._switch_status_updates.get_nowait()
            except queue.Empty:
                break
            self.status_label.configure(text=status)
            status_updated = True
        if status_updated:
            self.after(250, lambda: self._poll_switch_results(profile))
            return

        try:
            result = self._switch_results.get_nowait()
        except queue.Empty:
            self.after(100, lambda: self._poll_switch_results(profile))
            return

        self._switch_pending = False
        self.switch_progress.stop()
        self.switch_progress.grid_remove()
        self._set_profile_controls_enabled(True)
        if isinstance(result, Exception):
            self.status_label.configure(text=f"Could not switch to {profile.name}.")
            self._show_error(result)
        else:
            try:
                self._refresh(f"Switched to {profile.name}.")
                self._animate_profile_switch(profile.profile_id)
            except Exception as error:
                self._show_error(error)

        if self._update_check_pending or self._download_pending:
            self.after(250, self._poll_update_results)

    def _add_login(self) -> None:
        if not self._ask_yes_no(
            "Add another login",
            "Close Epic Games Launcher and open a fresh sign-in session?",
        ):
            return
        try:
            self.service.add_new_login()
            self._refresh("Epic login opened. Save the new session here after signing in.")
        except Exception as error:
            self._show_error(error)

    def _rename_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        name = _run_centered_dialog(
            self,
            lambda: simpledialog.askstring(
                "Rename profile",
                "Profile name:",
                initialvalue=profile.name,
                parent=self,
            ),
        )
        if name is None:
            return
        try:
            self.service.rename_profile(profile.profile_id, name.strip())
            self._refresh("Profile renamed.")
        except Exception as error:
            self._show_error(error)

    def _delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if not self._ask_yes_no(
            "Delete profile",
            f"Delete the saved snapshot '{profile.name}'? This does not delete the Epic account.",
        ):
            return
        try:
            self.service.delete_profile(profile.profile_id)
            self._refresh("Profile deleted.")
        except Exception as error:
            self._show_error(error)

    def _show_error(self, error: Exception) -> None:
        self._show_error_dialog("Epic Profile Switcher", str(error))

    def _show_error_dialog(self, title: str, message: str) -> None:
        _run_centered_dialog(
            self,
            lambda: messagebox.showerror(title, message, parent=self),
        )

    def _ask_yes_no(self, title: str, message: str) -> bool:
        return _run_centered_dialog(
            self,
            lambda: messagebox.askyesno(title, message, parent=self),
        )