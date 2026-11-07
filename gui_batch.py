"""Окно batch-сборки нескольких проектов."""

from __future__ import annotations

import contextlib
import io
import json
import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Sequence

import main as cli
from batch import load_batch_manifest, save_batch_manifest
from validators import validate_bpm, validate_project_name


class JobDialog(tk.Toplevel):
    """Диалог добавления/редактирования одного проекта batch."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        initial: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("720x320")
        self.resizable(True, False)
        self.transient(master.winfo_toplevel())
        self.result: dict[str, Any] | None = None

        data = initial or {}
        self.name_var = tk.StringVar(value=str(data.get("name", "")))
        self.samples_var = tk.StringVar(value=str(data.get("samples", "")))
        self.midi_var = tk.StringVar(value=str(data.get("midi", "")))
        self.map_var = tk.StringVar(value=str(data.get("map", "")))
        self.bpm_var = tk.StringVar(
            value="" if data.get("bpm") is None else str(data.get("bpm"))
        )
        self.extended_var = tk.BooleanVar(value=bool(data.get("extended_notes")))

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._save())
        self.update_idletasks()
        self.grab_set()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text="Имя проекта").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(outer, textvariable=self.name_var).grid(
            row=0, column=1, columnspan=2, sticky="ew", pady=3
        )

        self._path_row(
            outer,
            1,
            "Папка с WAV",
            self.samples_var,
            "dir",
        )
        self._path_row(
            outer,
            2,
            "MIDI-файл",
            self.midi_var,
            "midi",
        )
        self._path_row(
            outer,
            3,
            "Карта --map",
            self.map_var,
            "map",
        )

        ttk.Label(outer, text="BPM (необязательно)").grid(
            row=4, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(outer, textvariable=self.bpm_var, width=12).grid(
            row=4, column=1, sticky="w", pady=3
        )

        ttk.Checkbutton(
            outer,
            text="Extended notes 0..127 (--extended-notes)",
            variable=self.extended_var,
        ).grid(row=5, column=1, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(outer)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Отмена", command=self._cancel).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(buttons, text="OK", command=self._save).pack(side="right")

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        kind: str,
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=3
        )
        ttk.Button(
            parent,
            text="Обзор…",
            command=lambda: self._browse(variable, kind),
        ).grid(row=row, column=2, padx=(8, 0), pady=3)

    def _browse(self, variable: tk.StringVar, kind: str) -> None:
        if kind == "dir":
            path = filedialog.askdirectory(parent=self)
        elif kind == "midi":
            path = filedialog.askopenfilename(
                parent=self,
                filetypes=[("MIDI", "*.mid *.midi"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askopenfilename(
                parent=self,
                filetypes=[("JSON map", "*.json"), ("All files", "*.*")],
            )
        if path:
            variable.set(path)

    def _save(self) -> None:
        try:
            name = validate_project_name(self.name_var.get())
        except Exception as exc:
            messagebox.showerror("Проект", str(exc), parent=self)
            return
        if not self.samples_var.get().strip():
            messagebox.showerror("Проект", "Укажите папку с WAV.", parent=self)
            return
        if not self.midi_var.get().strip():
            messagebox.showerror("Проект", "Укажите MIDI-файл.", parent=self)
            return
        bpm_text = self.bpm_var.get().strip()
        if bpm_text:
            try:
                validate_bpm(bpm_text)
            except Exception as exc:
                messagebox.showerror("Проект", str(exc), parent=self)
                return
        result: dict[str, Any] = {
            "name": name,
            "samples": self.samples_var.get().strip(),
            "midi": self.midi_var.get().strip(),
            "extended_notes": bool(self.extended_var.get()),
        }
        if self.map_var.get().strip():
            result["map"] = self.map_var.get().strip()
        if bpm_text:
            result["bpm"] = float(bpm_text)
        self.result = result
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class BatchWindow(tk.Toplevel):
    """Просмотр, редактирование и запуск batch-манифеста."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        template: str = "",
        output: str = "",
        bpm: str = "",
        samples: str = "",
        midi: str = "",
        name: str = "",
        sample_map: str = "",
        extended_notes: bool = False,
    ) -> None:
        super().__init__(master)
        self.title("MPC XPJ Builder — batch")
        self.geometry("1060x760")
        self.minsize(860, 620)

        self.manifest_path: Path | None = None
        self.jobs: list[dict[str, Any]] = []
        self.running = False
        self._alive = True
        self.queue: queue.Queue[tuple[int, str, str, bool]] = queue.Queue()
        self.defaults = {
            "samples": samples,
            "midi": midi,
            "name": name,
            "map": sample_map,
            "extended_notes": extended_notes,
        }

        self.template_var = tk.StringVar(value=template)
        self.output_var = tk.StringVar(value=output)
        self.bpm_var = tk.StringVar(value=bpm)
        self.verbose_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Добавьте проекты или загрузите манифест.")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        form = ttk.LabelFrame(self, text="Общие параметры", padding=8)
        form.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        form.columnconfigure(1, weight=1)
        self._path_row(form, 0, "Эталонный .xpj", self.template_var, "xpj")
        self._path_row(form, 1, "Папка экспорта", self.output_var, "dir")
        ttk.Label(form, text="BPM по умолчанию").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(form, textvariable=self.bpm_var, width=12).grid(
            row=2, column=1, sticky="w", pady=3
        )
        ttk.Checkbutton(
            form,
            text="Подробный лог (--verbose)",
            variable=self.verbose_var,
        ).grid(row=3, column=1, sticky="w", pady=(4, 0))

        jobs_frame = ttk.LabelFrame(self, text="Проекты", padding=6)
        jobs_frame.grid(row=1, column=0, sticky="nsew", padx=10)
        jobs_frame.columnconfigure(0, weight=1)
        jobs_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            jobs_frame,
            columns=("name", "samples", "midi", "map", "bpm", "extended"),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "name": "Проект",
            "samples": "WAV",
            "midi": "MIDI",
            "map": "Map",
            "bpm": "BPM",
            "extended": "Ext",
        }
        widths = {
            "name": 150,
            "samples": 250,
            "midi": 220,
            "map": 170,
            "bpm": 55,
            "extended": 50,
        }
        for key, title in headings.items():
            self.tree.heading(key, text=title)
            self.tree.column(key, width=widths[key], stretch=key in {"samples", "midi"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _event: self._edit_job())

        job_buttons = ttk.Frame(jobs_frame)
        job_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.add_button = ttk.Button(
            job_buttons, text="Добавить…", command=self._add_job
        )
        self.add_button.pack(side="left")
        self.edit_button = ttk.Button(
            job_buttons, text="Изменить…", command=self._edit_job
        )
        self.edit_button.pack(side="left", padx=6)
        self.delete_button = ttk.Button(
            job_buttons, text="Удалить", command=self._delete_job
        )
        self.delete_button.pack(side="left")

        log_frame = ttk.LabelFrame(self, text="Лог", padding=6)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            height=10,
            state="disabled",
            font=("Consolas", 9),
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.grid(row=3, column=0, sticky="ew")
        self.load_button = ttk.Button(
            bottom, text="Загрузить манифест…", command=self._load_manifest
        )
        self.load_button.pack(side="left")
        self.save_button = ttk.Button(
            bottom, text="Сохранить манифест", command=self._save_manifest
        )
        self.save_button.pack(side="left", padx=6)
        self.close_button = ttk.Button(
            bottom, text="Закрыть", command=self._on_close
        )
        self.close_button.pack(side="right")
        self.run_button = ttk.Button(
            bottom, text="Запустить batch", command=lambda: self._start(dry_run=False)
        )
        self.run_button.pack(side="right", padx=6)
        self.dry_button = ttk.Button(
            bottom, text="Проверить", command=lambda: self._start(dry_run=True)
        )
        self.dry_button.pack(side="right")
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side="right", padx=(0, 12)
        )

    def _path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        kind: str,
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=3
        )
        ttk.Button(
            parent,
            text="Обзор…",
            command=lambda: self._browse(variable, kind),
        ).grid(row=row, column=2, padx=(8, 0), pady=3)

    def _browse(self, variable: tk.StringVar, kind: str) -> None:
        if kind == "dir":
            path = filedialog.askdirectory(parent=self)
        else:
            path = filedialog.askopenfilename(
                parent=self,
                filetypes=[("XPJ project", "*.xpj"), ("All files", "*.*")],
            )
        if path:
            variable.set(path)

    def _refresh_jobs(self, select: int | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, job in enumerate(self.jobs):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    job.get("name", ""),
                    job.get("samples", ""),
                    job.get("midi", ""),
                    job.get("map", "") or "—",
                    "" if job.get("bpm") is None else job.get("bpm"),
                    "да" if job.get("extended_notes") else "",
                ),
            )
        if select is not None and 0 <= select < len(self.jobs):
            self.tree.selection_set(str(select))
            self.tree.focus(str(select))

    def _selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            index = int(selection[0])
        except ValueError:
            return None
        return index if 0 <= index < len(self.jobs) else None

    def _add_job(self) -> None:
        dialog = JobDialog(self, title="Новый проект batch", initial=self.defaults)
        result = self._show_dialog(dialog)
        if result is None:
            return
        self.jobs.append(result)
        self._refresh_jobs(select=len(self.jobs) - 1)
        self.status_var.set(f"Проектов в batch: {len(self.jobs)}")

    def _edit_job(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Batch", "Выберите проект в таблице.", parent=self)
            return
        dialog = JobDialog(
            self,
            title="Изменить проект batch",
            initial=self.jobs[index],
        )
        result = self._show_dialog(dialog)
        if result is None:
            return
        merged = dict(self.jobs[index])
        merged.update(result)
        self.jobs[index] = merged
        self._refresh_jobs(select=index)

    def _show_dialog(self, dialog: JobDialog) -> dict[str, Any] | None:
        dialog.wait_window()
        return dialog.result

    def _delete_job(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Batch", "Выберите проект в таблице.", parent=self)
            return
        del self.jobs[index]
        self._refresh_jobs(select=min(index, len(self.jobs) - 1) if self.jobs else None)
        self.status_var.set(f"Проектов в batch: {len(self.jobs)}")

    def _optional_bpm(self, raw: str) -> float | str | None:
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return text

    def _build_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.template_var.get().strip():
            payload["template"] = self.template_var.get().strip()
        if self.output_var.get().strip():
            payload["output"] = self.output_var.get().strip()
        bpm = self._optional_bpm(self.bpm_var.get())
        if bpm is not None:
            payload["bpm"] = bpm

        jobs: list[dict[str, Any]] = []
        for job in self.jobs:
            item: dict[str, Any] = {
                "name": job.get("name", ""),
                "samples": job.get("samples", ""),
                "midi": job.get("midi", ""),
            }
            for key in ("output", "template", "map"):
                value = job.get(key)
                if isinstance(value, str) and value.strip():
                    item[key] = value.strip()
            if job.get("bpm") not in (None, ""):
                item["bpm"] = self._optional_bpm(str(job.get("bpm")))
            if job.get("extended_notes"):
                item["extended_notes"] = True
            jobs.append(item)
        payload["jobs"] = jobs
        return payload

    def _save_manifest(self) -> bool:
        if not self.jobs:
            messagebox.showerror("Batch", "Добавьте хотя бы один проект.", parent=self)
            return False
        target = self.manifest_path
        if target is None:
            initial_dir = (
                self.output_var.get().strip()
                or str(Path.home())
            )
            selected = filedialog.asksaveasfilename(
                parent=self,
                title="Сохранить batch-манифест",
                defaultextension=".json",
                initialdir=initial_dir,
                initialfile="batch.json",
                filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            )
            if not selected:
                return False
            target = Path(selected)
        try:
            save_batch_manifest(target, self._build_payload())
        except Exception as exc:
            messagebox.showerror("Batch", str(exc), parent=self)
            return False
        self.manifest_path = target
        self.title(f"MPC XPJ Builder — batch — {target.name}")
        self._append_log(f"Манифест сохранён: {target}\n")
        return True

    def _load_manifest(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Открыть batch-манифест",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            load_batch_manifest(path)
        except Exception as exc:
            messagebox.showerror("Batch", str(exc), parent=self)
            return
        if not isinstance(payload, dict):
            messagebox.showerror("Batch", "Манифест должен быть JSON-объектом.", parent=self)
            return

        self.manifest_path = path
        self.template_var.set(str(payload.get("template", "")))
        self.output_var.set(str(payload.get("output", "")))
        self.bpm_var.set(
            "" if payload.get("bpm") is None else str(payload.get("bpm"))
        )
        raw_jobs = payload.get("jobs")
        self.jobs = [
            dict(job) for job in raw_jobs if isinstance(job, dict)
        ] if isinstance(raw_jobs, list) else []
        self._refresh_jobs(select=0 if self.jobs else None)
        self.title(f"MPC XPJ Builder — batch — {path.name}")
        self._clear_log()
        self._append_log(f"Загружен манифест: {path}\n")
        self.status_var.set(f"Проектов в batch: {len(self.jobs)}")

    def _start(self, *, dry_run: bool) -> None:
        if self.running:
            return
        if not self._save_manifest():
            return
        if self.manifest_path is None:
            return
        self._clear_log()
        mode = "Проверка batch" if dry_run else "Запуск batch"
        self._append_log(f"{mode}\n\n")
        args = ["--batch", str(self.manifest_path)]
        if dry_run:
            args.append("--dry-run")
        if self.verbose_var.get():
            args.append("--verbose")

        self.running = True
        self.status_var.set("Выполняется…")
        self._set_busy(True)
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
        if not self._alive:
            return
        try:
            code, output, error, dry_run = self.queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return

        self.running = False
        self._set_busy(False)
        if output:
            self._append_log(output)
        if error:
            self._append_log("\nSTDERR:\n" + error)
        if code == 0:
            if dry_run:
                self.status_var.set("Проверка завершена. Файлы не создавались.")
            else:
                self.status_var.set("Batch завершён.")
                messagebox.showinfo("Batch", "Batch успешно завершён.", parent=self)
        else:
            self.status_var.set(f"Ошибка. Код возврата: {code}.")
            first_line = (error or output or "Неизвестная ошибка").strip().splitlines()[0]
            messagebox.showerror("Batch", first_line, parent=self)
        self.after(100, self._poll)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.load_button,
            self.save_button,
            self.dry_button,
            self.run_button,
        ):
            button.configure(state=state)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        if self.running and not messagebox.askyesno(
            "Batch",
            "Batch ещё выполняется. Закрыть окно?",
            parent=self,
        ):
            return
        self._alive = False
        self.destroy()
