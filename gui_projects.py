"""Окно списка .xpj-проектов в папке."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from project_library import ProjectInfo, scan_projects


class ProjectBrowserWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        folder_provider: Callable[[], str],
        on_use_template: Callable[[Path], None],
    ) -> None:
        super().__init__(master)
        self.title("MPC XPJ Builder — проекты")
        self.geometry("980x520")
        self.minsize(760, 420)
        self.transient(master.winfo_toplevel())
        self.folder_provider = folder_provider
        self.on_use_template = on_use_template
        self.items: tuple[ProjectInfo, ...] = ()
        self.folder_var = tk.StringVar(value=folder_provider())
        self.status_var = tk.StringVar(value="")

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Папка:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.folder_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(top, text="Обзор…", command=self._browse).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(top, text="Обновить", command=self.refresh).grid(
            row=0, column=3
        )

        tree_frame = ttk.Frame(self, padding=(10, 0))
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("name", "bpm", "samples", "bars", "tracks", "modified", "file"),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "name": "Проект",
            "bpm": "BPM",
            "samples": "Samples",
            "bars": "Bars",
            "tracks": "Tracks",
            "modified": "Изменён",
            "file": "Файл",
        }
        widths = {
            "name": 170,
            "bpm": 70,
            "samples": 80,
            "bars": 60,
            "tracks": 65,
            "modified": 130,
            "file": 320,
        }
        for key, title in headings.items():
            self.tree.heading(key, text=title)
            self.tree.column(key, width=widths[key], stretch=key in {"name", "file"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._selection_changed())
        self.tree.bind("<Double-1>", lambda _event: self._open_folder())

        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.grid(row=2, column=0, sticky="ew")
        self.open_button = ttk.Button(
            bottom, text="Открыть папку", command=self._open_folder
        )
        self.open_button.pack(side="left")
        self.template_button = ttk.Button(
            bottom, text="Сделать эталоном", command=self._use_as_template
        )
        self.template_button.pack(side="left", padx=6)
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="right")
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side="right", padx=(0, 12)
        )
        self._set_buttons(False)

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.open_button.configure(state=state)
        self.template_button.configure(state=state)

    def _browse(self) -> None:
        path = filedialog.askdirectory(initialdir=self.folder_var.get() or None)
        if path:
            self.folder_var.set(path)
            self.refresh()

    def refresh(self) -> None:
        folder = Path(self.folder_var.get().strip())
        self.tree.delete(*self.tree.get_children())
        self.items = ()
        self._set_buttons(False)
        if not folder.is_dir():
            self.status_var.set("Папка не найдена.")
            return
        try:
            items = scan_projects(folder)
        except Exception as exc:
            messagebox.showerror("Проекты", str(exc), parent=self)
            self.status_var.set("Ошибка чтения папки.")
            return
        self.items = items
        errors = 0
        for index, item in enumerate(items):
            if item.error:
                errors += 1
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    item.name,
                    "" if item.bpm is None else f"{item.bpm:g}",
                    item.samples,
                    item.bars,
                    item.tracks,
                    item.modified_text,
                    item.path.name if item.error is None else f"{item.path.name} (ошибка)",
                ),
            )
        self.status_var.set(
            f"Проектов: {len(items)}" + (f", ошибок: {errors}" if errors else "")
        )

    def _selected(self) -> ProjectInfo | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return self.items[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def _selection_changed(self) -> None:
        item = self._selected()
        self._set_buttons(item is not None)
        if item is not None and item.error:
            self.status_var.set(f"Ошибка чтения: {item.error}")
        elif item is not None:
            self.status_var.set(str(item.path))

    def _open_folder(self) -> None:
        item = self._selected()
        if item is None:
            return
        try:
            os.startfile(str(item.path.parent))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Не удалось открыть папку", str(exc), parent=self)

    def _use_as_template(self) -> None:
        item = self._selected()
        if item is None:
            return
        if item.error:
            messagebox.showerror(
                "Эталон",
                "Этот .xpj не читается и не может быть эталоном.",
                parent=self,
            )
            return
        self.on_use_template(item.path)
        self.status_var.set(f"Эталон: {item.path.name}")
        messagebox.showinfo(
            "Эталон",
            f"Путь подставлен в поле шаблона:\n{item.path}",
            parent=self,
        )
