"""Окно просмотра и безопасного редактирования существующего .xpj."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import project_editor
from validators import validate_bpm


class ProjectEditorWindow(tk.Toplevel):
    """Меняет только название и BPM, сохраняя остальные поля проекта."""

    def __init__(self, master: tk.Misc, *, path: Path) -> None:
        super().__init__(master)
        self.path = Path(path)
        self.header, self.payload, self.summary = project_editor.read_project(
            self.path
        )
        self.title_var = tk.StringVar(value=self.summary.title)
        self.bpm_var = tk.StringVar(value=f"{self.summary.bpm:g}")
        self.status_var = tk.StringVar(value="")

        self.title("MPC XPJ Builder — проект")
        self.geometry("920x620")
        self.minsize(760, 520)
        self.transient(master.winfo_toplevel())
        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        info = ttk.LabelFrame(outer, text="Проект", padding=8)
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(1, weight=1)
        self._info_row(info, 0, "Файл", str(self.path))
        self._info_row(
            info,
            1,
            "Прошивка",
            f"{self.summary.version} · {self.summary.platform}",
        )
        self._info_row(
            info,
            2,
            "Папка ресурсов",
            str(self.summary.data_dir) if self.summary.data_dir else "не найдена",
        )

        form = ttk.LabelFrame(outer, text="Редактирование", padding=8)
        form.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Название проекта").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(form, textvariable=self.title_var).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Label(form, text="BPM").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(form, textvariable=self.bpm_var, width=12).grid(
            row=1, column=1, sticky="w", pady=3
        )
        ttk.Label(
            form,
            text=(
                "Меняются только название и BPM. Остальные поля .xpj "
                "сохраняются как есть."
            ),
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        summary_frame = ttk.LabelFrame(outer, text="Содержимое", padding=8)
        summary_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)
        self.summary_text = tk.Text(
            summary_frame,
            height=10,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
        )
        self.summary_text.grid(row=0, column=0, sticky="nsew")
        self._refresh_summary()

        bottom = ttk.Frame(outer)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.copy_button = ttk.Button(
            bottom, text="Сохранить копию…", command=self._save_copy
        )
        self.copy_button.pack(side="left")
        self.overwrite_button = ttk.Button(
            bottom, text="Перезаписать с backup", command=self._overwrite
        )
        self.overwrite_button.pack(side="left", padx=6)
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="right")
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side="right", padx=(0, 12)
        )

    def _info_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        value: str,
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=2
        )
        ttk.Label(parent, text=value, wraplength=760).grid(
            row=row, column=1, sticky="w", pady=2
        )

    def _refresh_summary(self) -> None:
        summary = self.summary
        lines = [
            f"Название: {summary.title}",
            f"BPM: {summary.bpm:g}",
            f"Sequence: {len(summary.sequences)}   "
            f"Треки: {summary.tracks}   "
            f"Семплы: {summary.samples}   "
            f"Пады с семплами: {summary.pads}",
            f"WAV в папке ресурсов: {summary.data_wavs}",
            "",
            "Sequence:",
        ]
        for sequence in summary.sequences:
            bpm = "" if sequence.bpm is None else f"{sequence.bpm:g} BPM"
            lines.append(
                f"  {sequence.index + 1:02d}. {sequence.name} — "
                f"{sequence.bars} bar(s), {sequence.notes} note(s) {bpm}".rstrip()
            )
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")

    def _collect_metadata(self) -> tuple[str, float] | None:
        try:
            title = project_editor.validate_title(self.title_var.get())
            bpm = validate_bpm(self.bpm_var.get())
        except Exception as exc:
            messagebox.showerror("Проект", str(exc), parent=self)
            return None
        return title, bpm

    def _save_copy(self) -> None:
        metadata = self._collect_metadata()
        if metadata is None:
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить копию проекта",
            defaultextension=".xpj",
            initialdir=str(self.path.parent),
            initialfile=f"{self.path.stem} copy.xpj",
            filetypes=[("XPJ project", "*.xpj"), ("All files", "*.*")],
        )
        if not target:
            return
        payload = project_editor.apply_metadata(self.payload, *metadata)
        try:
            xpj_path, data_path = project_editor.save_project_copy(
                self.path,
                Path(target),
                self.header,
                payload,
            )
        except Exception as exc:
            messagebox.showerror("Сохранение", str(exc), parent=self)
            return
        self.status_var.set(f"Копия сохранена: {xpj_path.name}")
        messagebox.showinfo(
            "Копия сохранена",
            f"XPJ:\n{xpj_path}\n\n"
            f"ProjectData:\n{data_path if data_path else 'нет папки ресурсов'}",
            parent=self,
        )

    def _overwrite(self) -> None:
        metadata = self._collect_metadata()
        if metadata is None:
            return
        backup = project_editor.backup_path(self.path)
        if not messagebox.askyesno(
            "Перезаписать проект",
            f"Перезаписать:\n{self.path}\n\n"
            f"Перед записью будет создан backup:\n{backup}\n\nПродолжить?",
            parent=self,
        ):
            return
        payload = project_editor.apply_metadata(self.payload, *metadata)
        try:
            xpj_path, backup_path = project_editor.save_project_in_place(
                self.path,
                self.header,
                payload,
            )
        except Exception as exc:
            messagebox.showerror("Сохранение", str(exc), parent=self)
            return

        self.header, self.payload, self.summary = project_editor.read_project(
            self.path
        )
        self.title_var.set(self.summary.title)
        self.bpm_var.set(f"{self.summary.bpm:g}")
        self._refresh_summary()
        self.status_var.set(f"Сохранено. Backup: {backup_path.name}")
        messagebox.showinfo(
            "Проект сохранён",
            f"XPJ:\n{xpj_path}\n\nBackup:\n{backup_path}",
            parent=self,
        )
