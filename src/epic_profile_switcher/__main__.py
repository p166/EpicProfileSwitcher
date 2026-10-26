"""Application entry point."""

from __future__ import annotations

from tkinter import messagebox

from .gui import MainWindow
from .protection import DpapiProtector
from .service import EpicProfileService


def main() -> int:
    try:
        service = EpicProfileService(protector=DpapiProtector())
    except Exception as error:
        messagebox.showerror("Epic Profile Switcher", str(error))
        return 1
    window = MainWindow(service)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())