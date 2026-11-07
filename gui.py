"""Tkinter GUI для mpc_xpj_builder."""

from __future__ import annotations

import contextlib
import io
import os
import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Sequence

import main as cli
from dnd import disable_file_drop, enable_file_drop, route_dropped
from gui_batch import BatchWindow
from gui_map import MapEditorWindow
from gui_projects import ProjectBrowserWindow
from settings import GuiSettings, load_settings, remember_recent, save_settings
from validators import MAX_BPM, MIN_BPM
from version import __version__


def build_cli_args(
    *,
    samples: str,
    midi: str,
    name: str,
    bpm: str,
    output: str,
    template: str,
    sample_map: str = "",
    dry_run: bool = False,
    verbose: bool = False,
    extended_notes: bool = False,
) -> list[str]:
    """Собрать argv для main.py с понятными ошибками формы."""
    project_name = name.strip()
    if not project_name:
        raise ValueError("Укажите имя проекта.")

    try:
        bpm_value = float(bpm)
    except ValueError as exc:
        raise ValueError("BPM должен быть числом.") from exc
    if not MIN_BPM <= bpm_value <= MAX_BPM:
        raise ValueError(f"BPM должен быть в диапазоне {MIN_BPM:g}..{MAX_BPM:g}.")

    if not samples.strip():
        raise ValueError("Укажите папку с семплами.")
    if not midi.strip():
        raise ValueError("Укажите MIDI-файл.")
    if not output.strip():
        raise ValueError("Укажите папку экспорта.")
    if not template.strip():
        raise ValueError("Укажите эталонный .xpj.")

    samples_path = Path(samples.strip())
    midi_path = Path(midi.strip())
    output_path = Path(output.strip())
    template_path = Path(template.strip())
    map_path = Path(sample_map.strip()) if sample_map.strip() else None

    if not samples_path.is_dir():
        raise ValueError("Папка с семплами не найдена.")
    if not midi_path.is_file():
        raise ValueError("MIDI-файл не найден.")
    if not template_path.is_file():
        raise ValueError("Эталонный .xpj не найден.")
    if map_path is not None and not map_path.is_file():
        raise ValueError("JSON-карта не найдена.")

    args = [
        "--samples",
        str(samples_path),
        "--midi",
        str(midi_path),
        "--name",
        project_name,
        "--bpm",
        f"{bpm_value:g}",
        "--output",
        str(output_path),
        "--template",
        str(template_path),
    ]
    if map_path is not None:
        args.extend(["--map", str(map_path)])
    if extended_notes:
        args.append("--extended-notes")
    if dry_run:
        args.append("--dry-run")
    if verbose:
        args.append("--verbose")
    return args


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.queue: queue.Queue[tuple[int, str, str, bool]] = queue.Queue()
        self.running = False
        self.dry_run = False
        self.map_editor: MapEditorWindow | None = None
        self.project_browser: ProjectBrowserWindow | None = None
        self.batch_window: BatchWindow | None = None

        saved = load_settings()
        self.recent_projects = list(saved.recent_projects)
        self.samples_var = tk.StringVar(value=saved.samples)
        self.midi_var = tk.StringVar(value=saved.midi)
        self.name_var = tk.StringVar(value=saved.name)
        self.bpm_var = tk.StringVar(value=saved.bpm)
        self.output_var = tk.StringVar(value=saved.output)
        self.template_var = tk.StringVar(value=saved.template)
        self.map_var = tk.StringVar(value=saved.sample_map)
        self.extended_var = tk.BooleanVar(value=saved.extended_notes)
        self.verbose_var = tk.BooleanVar(value=saved.verbose)
        self.recent_var = tk.StringVar(
            value=self.recent_projects[0] if self.recent_projects else ""
        )

        self._build_ui()
        enable_file_drop(self.root, self._handle_drop)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll)

    def _build_ui(self) -> None:
        self.root.title(f"MPC XPJ Builder {__version__}")
        self.root.geometry("920x680")
        self.root.minsize(760, 560)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(outer, text="Параметры проекта", padding=10)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        self._entry_row(form, 0, "Папка с WAV", self.samples_var, "dir")
        self._entry_row(form, 1, "MIDI-файл", self.midi_var, "midi")
        self._entry_row(form, 2, "Имя проекта", self.name_var, None)
        self._entry_row(form, 3, "BPM", self.bpm_var, None)
        self._entry_row(form, 4, "Папка экспорта", self.output_var, "dir")
        self._entry_row(form, 5, "Эталонный .xpj", self.template_var, "xpj")
        self._entry_row(form, 6, "Карта --map (необязательно)", self.map_var, "map")

        options = ttk.Frame(form)
        options.grid(row=7, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            options,
            text="Extended notes 0..127 (--extended-notes)",
            variable=self.extended_var,
        ).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(
            options,
            text="Подробный лог (--verbose)",
            variable=self.verbose_var,
        ).pack(side="left")

        ttk.Label(form, text="Последний проект").grid(
            row=8, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self.recent_combo = ttk.Combobox(
            form,
            textvariable=self.recent_var,
            values=self.recent_projects,
            state="readonly",
        )
        self.recent_combo.grid(row=8, column=1, sticky="ew", pady=3)
        ttk.Button(
            form,
            text="Открыть папку",
            command=self._open_recent,
        ).grid(row=8, column=2, padx=(8, 0), pady=3)

        ttk.Label(
            form,
            text="Можно перетащить в окно папку WAV, MIDI, .xpj или map.json",
            foreground="#666666",
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(4, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        for column in range(7):
            actions.columnconfigure(column, weight=1)

        self.plan_button = ttk.Button(
            actions,
            text="Проверить план",
            command=lambda: self._start(dry_run=True),
        )
        self.plan_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.export_button = ttk.Button(
            actions,
            text="Создать проект",
            command=lambda: self._start(dry_run=False),
        )
        self.export_button.grid(row=0, column=1, sticky="ew", padx=5)

        self.map_button = ttk.Button(
            actions,
            text="Карта семплов…",
            command=self._open_map_editor,
        )
        self.map_button.grid(row=0, column=2, sticky="ew", padx=5)

        self.projects_button = ttk.Button(
            actions,
            text="Проекты…",
            command=self._open_project_browser,
        )
        self.projects_button.grid(row=0, column=3, sticky="ew", padx=5)

        self.batch_button = ttk.Button(
            actions,
            text="Batch…",
            command=self._open_batch,
        )
        self.batch_button.grid(row=0, column=4, sticky="ew", padx=5)

        self.open_button = ttk.Button(
            actions,
            text="Открыть папку",
            command=self._open_output,
        )
        self.open_button.grid(row=0, column=5, sticky="ew", padx=5)

        self.clear_button = ttk.Button(
            actions,
            text="Очистить лог",
            command=self._clear_log,
        )
        self.clear_button.grid(row=0, column=6, sticky="ew", padx=(5, 0))

        log_frame = ttk.LabelFrame(outer, text="Лог", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            height=20,
            state="disabled",
            font=("Consolas", 9),
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        self.status_var = tk.StringVar(value="Готово. Заполните поля и нажмите «Проверить план».")
        ttk.Label(outer, textvariable=self.status_var).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )

    def _entry_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse: str | None,
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=3
        )
        if browse is None:
            ttk.Label(parent, text="").grid(row=row, column=2, padx=(8, 0))
            return

        button = ttk.Button(
            parent,
            text="Обзор…",
            command=lambda: self._browse(variable, browse),
        )
        button.grid(row=row, column=2, padx=(8, 0), pady=3)

    def _browse(self, variable: tk.StringVar, kind: str) -> None:
        if kind == "dir":
            path = filedialog.askdirectory()
        elif kind == "midi":
            path = filedialog.askopenfilename(
                filetypes=[("MIDI", "*.mid *.midi"), ("All files", "*.*")]
            )
        elif kind == "xpj":
            path = filedialog.askopenfilename(
                filetypes=[("XPJ project", "*.xpj"), ("All files", "*.*")]
            )
        elif kind == "map":
            path = filedialog.askopenfilename(
                filetypes=[("JSON map", "*.json"), ("All files", "*.*")]
            )
        else:
            path = ""
        if path:
            variable.set(path)

    def _set_busy(self, busy: bool) -> None:
        self.running = busy
        state = "disabled" if busy else "normal"
        for button in (
            self.plan_button,
            self.export_button,
            self.map_button,
            self.projects_button,
            self.batch_button,
            self.open_button,
            self.clear_button,
        ):
            button.configure(state=state)
        if busy:
            self.status_var.set("Выполняется…")

    def _start(self, *, dry_run: bool) -> None:
        if self.running:
            return
        try:
            args = build_cli_args(
                samples=self.samples_var.get(),
                midi=self.midi_var.get(),
                name=self.name_var.get(),
                bpm=self.bpm_var.get(),
                output=self.output_var.get(),
                template=self.template_var.get(),
                sample_map=self.map_var.get(),
                dry_run=dry_run,
                verbose=self.verbose_var.get(),
                extended_notes=self.extended_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Проверьте параметры", str(exc))
            return

        self.dry_run = dry_run
        self._clear_log()
        mode = "Проверка плана" if dry_run else "Экспорт проекта"
        self._append_log(f"{mode}\n\n")
        self._set_busy(True)
        self.status_var.set("Выполняется…")

        thread = threading.Thread(
            target=self._worker,
            args=(args, dry_run),
            daemon=True,
        )
        thread.start()

    def _worker(self, args: Sequence[str], dry_run: bool) -> None:
        output = io.StringIO()
        error = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = cli.main(list(args))
        except SystemExit as exc:
            code = int(exc.code) if isinstance(exc.code, int) else 1
        except Exception:
            code = 1
            error.write(traceback.format_exc())
        self.queue.put((code, output.getvalue(), error.getvalue(), dry_run))

    def _poll(self) -> None:
        try:
            code, output, error, dry_run = self.queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return

        self._set_busy(False)
        if output:
            self._append_log(output)
        if error:
            self._append_log("\nSTDERR:\n" + error)

        if code == 0:
            if dry_run:
                self.status_var.set("План готов. Файлы не создавались.")
            else:
                for line in output.splitlines():
                    if line.strip().startswith("XPJ:"):
                        created = line.split("XPJ:", 1)[1].strip()
                        if created:
                            self._remember_recent(created)
                            break
                self.status_var.set("Проект создан.")
                messagebox.showinfo("Готово", "Проект успешно создан.")
        else:
            self.status_var.set(f"Ошибка. Код возврата: {code}.")
            first_line = (error or output or "Неизвестная ошибка").strip().splitlines()[0]
            messagebox.showerror("Ошибка", first_line)
        self.root.after(100, self._poll)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_map_editor(self) -> None:
        if self.map_editor is not None and self.map_editor.winfo_exists():
            self.map_editor.lift()
            self.map_editor.focus_force()
            return
        self.map_editor = MapEditorWindow(
            self.root,
            samples_provider=lambda: self.samples_var.get(),
            template_provider=lambda: self.template_var.get(),
            on_saved=self._on_map_saved,
        )

    def _on_map_saved(self, path: Path) -> None:
        self.map_var.set(str(path))
        self.status_var.set(f"Карта применена: {path}")

    def _open_project_browser(self) -> None:
        if (
            self.project_browser is not None
            and self.project_browser.winfo_exists()
        ):
            self.project_browser.lift()
            self.project_browser.focus_force()
            return
        self.project_browser = ProjectBrowserWindow(
            self.root,
            folder_provider=lambda: self.output_var.get() or str(Path.cwd()),
            on_use_template=self._on_project_template,
        )

    def _on_project_template(self, path: Path) -> None:
        self.template_var.set(str(path))
        self.status_var.set(f"Эталон выбран: {path}")

    def _open_batch(self) -> None:
        if self.batch_window is not None and self.batch_window.winfo_exists():
            self.batch_window.lift()
            self.batch_window.focus_force()
            return
        self.batch_window = BatchWindow(
            self.root,
            template=self.template_var.get(),
            output=self.output_var.get(),
            bpm=self.bpm_var.get(),
            samples=self.samples_var.get(),
            midi=self.midi_var.get(),
            name=self.name_var.get(),
            sample_map=self.map_var.get(),
            extended_notes=self.extended_var.get(),
        )

    def _save_settings(self, *, show_error: bool) -> None:
        try:
            save_settings(
                GuiSettings(
                    samples=self.samples_var.get(),
                    midi=self.midi_var.get(),
                    name=self.name_var.get(),
                    bpm=self.bpm_var.get(),
                    output=self.output_var.get(),
                    template=self.template_var.get(),
                    sample_map=self.map_var.get(),
                    extended_notes=self.extended_var.get(),
                    verbose=self.verbose_var.get(),
                    recent_projects=tuple(self.recent_projects),
                )
            )
        except OSError as exc:
            if show_error:
                messagebox.showwarning(
                    "Настройки",
                    f"Не удалось сохранить настройки:\n{exc}",
                )

    def _on_close(self) -> None:
        self._save_settings(show_error=True)
        disable_file_drop(self.root)
        self.root.destroy()

    def _handle_drop(self, paths: list[str]) -> None:
        result = route_dropped(paths)
        changed: list[str] = []
        if result.samples is not None:
            self.samples_var.set(str(result.samples))
            changed.append("WAV-папка")
        if result.midi is not None:
            self.midi_var.set(str(result.midi))
            changed.append("MIDI")
        if result.template is not None:
            self.template_var.set(str(result.template))
            changed.append(".xpj")
        if result.sample_map is not None:
            self.map_var.set(str(result.sample_map))
            changed.append("map.json")
        if changed:
            self.status_var.set("Перетащено: " + ", ".join(changed))
        if result.unsupported:
            self.status_var.set(
                "Не поддержано: "
                + ", ".join(path.name for path in result.unsupported[:3])
            )

    def _remember_recent(self, path: str) -> None:
        self.recent_projects = list(remember_recent(self.recent_projects, path))
        self.recent_var.set(path)
        self.recent_combo.configure(values=self.recent_projects)
        self._save_settings(show_error=False)

    def _open_recent(self) -> None:
        raw = self.recent_var.get().strip()
        if not raw:
            messagebox.showinfo("Последние проекты", "Список пока пуст.")
            return
        path = Path(raw)
        if not path.is_file():
            self.recent_projects = [
                item for item in self.recent_projects if item != raw
            ]
            self.recent_combo.configure(values=self.recent_projects)
            self.recent_var.set(
                self.recent_projects[0] if self.recent_projects else ""
            )
            messagebox.showerror("Последние проекты", f"Файл не найден:\n{path}")
            return
        try:
            os.startfile(str(path.parent))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Не удалось открыть папку", str(exc))

    def _open_output(self) -> None:
        output = self.output_var.get().strip()
        if not output:
            messagebox.showerror("Папка экспорта", "Сначала укажите папку экспорта.")
            return
        path = Path(output)
        if not path.is_dir():
            messagebox.showerror("Папка экспорта", f"Папка не найдена:\n{path}")
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Не удалось открыть папку", str(exc))


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
