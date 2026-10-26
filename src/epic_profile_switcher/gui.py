"""Tkinter user interface for Epic profile management."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .service import EpicProfileService, Profile


class MainWindow(tk.Tk):
    def __init__(self, service: EpicProfileService) -> None:
        super().__init__()
        self.service = service
        self._profiles: dict[str, Profile] = {}
        self._profile_ids: list[str] = []
        self.title("Epic Profile Switcher")
        self.geometry("720x500")
        self.minsize(560, 390)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f5f7")
        style.configure("TLabel", background="#f4f5f7", foreground="#20242b")
        style.configure("Heading.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", foreground="#626b78", font=("Segoe UI", 9))
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
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )

        path_row = ttk.Frame(root)
        path_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        path_row.columnconfigure(0, weight=1)
        self.path_label = ttk.Label(path_row, style="Muted.TLabel")
        self.path_label.grid(row=0, column=0, sticky="w")
        ttk.Button(path_row, text="Browse...", command=self._browse_launcher).grid(
            row=0, column=1, padx=(12, 0)
        )

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
            selectbackground="#dceaf7",
            selectforeground="#142a42",
            highlightthickness=1,
            highlightbackground="#d7dce2",
            highlightcolor="#1769aa",
            borderwidth=0,
            font=("Segoe UI", 10),
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

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew")
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
        secondary.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.add_login_button = ttk.Button(secondary, text="Add another login", command=self._add_login)
        self.add_login_button.pack(side="left")
        self.delete_button = ttk.Button(secondary, text="Delete", command=self._delete_profile)
        self.delete_button.pack(side="right")
        self.rename_button = ttk.Button(secondary, text="Rename", command=self._rename_profile)
        self.rename_button.pack(side="right", padx=(0, 8))

        self._refresh()
        self._refresh_active_markers()

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
        selected = self._selected_profile() is not None
        self.switch_button.configure(state="normal" if selected else "disabled")
        self.rename_button.configure(state="normal" if selected else "disabled")
        self.delete_button.configure(state="normal" if selected else "disabled")

    def _browse_launcher(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select Epic Games Launcher",
            initialdir=str(Path.home()),
            filetypes=(("Epic Games Launcher", "EpicGamesLauncher.exe"),),
        )
        if selected:
            try:
                self.service.save_launcher_path(Path(selected))
                self._refresh("Launcher path saved.")
            except Exception as error:
                self._show_error(error)

    def _save_current(self) -> None:
        name = simpledialog.askstring(
            "Save current profile",
            "Profile name:",
            parent=self,
        )
        if name is None:
            return
        try:
            profile = self.service.save_current_profile(name.strip())
            self._refresh(f"Saved profile: {profile.name}")
        except Exception as error:
            self._show_error(error)

    def _switch_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if not messagebox.askyesno(
            "Switch Epic profile",
            f"Close Epic Games Launcher and switch to '{profile.name}'?",
            parent=self,
        ):
            return
        try:
            self.service.switch_profile(profile.profile_id)
            self._refresh(f"Switched to {profile.name}.")
        except Exception as error:
            self._show_error(error)

    def _add_login(self) -> None:
        if not messagebox.askyesno(
            "Add another login",
            "Close Epic Games Launcher and open a fresh sign-in session?",
            parent=self,
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
        name = simpledialog.askstring(
            "Rename profile",
            "Profile name:",
            initialvalue=profile.name,
            parent=self,
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
        if not messagebox.askyesno(
            "Delete profile",
            f"Delete the saved snapshot '{profile.name}'? This does not delete the Epic account.",
            parent=self,
        ):
            return
        try:
            self.service.delete_profile(profile.profile_id)
            self._refresh("Profile deleted.")
        except Exception as error:
            self._show_error(error)

    def _show_error(self, error: Exception) -> None:
        messagebox.showerror("Epic Profile Switcher", str(error), parent=self)