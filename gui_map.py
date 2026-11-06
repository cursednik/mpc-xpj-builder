"""Окно редактора карты семплов."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import kit_map


class MapEditorWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        samples_provider: Callable[[], str],
        template_provider: Callable[[], str],
        on_saved: Callable[[Path], None],
    ) -> None:
        super().__init__(master)
        self.title("MPC XPJ Builder — карта семплов")
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.transient(master.winfo_toplevel())
        self.samples_provider = samples_provider
        self.template_provider = template_provider
        self.on_saved = on_saved

        self.items: tuple[kit_map.WavItem, ...] = ()
        self.assignments: dict[int, kit_map.PadAssignment] = {}
        self.pad_to_note: dict[int, int] = kit_map.default_pad_to_note()
        self.note_to_pad: dict[int, int] = {
            note: pad for pad, note in self.pad_to_note.items()
        }
        self.selected_pad: int | None = None
        self.pad_buttons: dict[int, tk.Button] = {}

        self.bank_var = tk.StringVar(value="A")
        self.pad_label_var = tk.StringVar(value="—")
        self.note_var = tk.StringVar(value="—")
        self.file_var = tk.StringVar(value="—")
        self.gain_var = tk.StringVar(value="1.0")
        self.pan_var = tk.StringVar(value="0.5")
        self.tune_var = tk.StringVar(value="0.0")
        self.loop_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Выберите пад и WAV.")

        self._build_ui()
        self._load_note_map()
        self.refresh()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Папка семплов:").grid(row=0, column=0, sticky="w")
        self.samples_label = ttk.Label(top, text="—")
        self.samples_label.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(top, text="Обновить", command=self.refresh).grid(
            row=0, column=2, sticky="e"
        )
        ttk.Label(
            top,
            text="Все 128 падов доступны для загрузки семплов; MIDI-sequence может играть любые ноты при --extended-notes.",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew", padx=10)

        left = ttk.LabelFrame(paned, text="WAV-файлы", padding=6)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            left,
            columns=("file", "info", "status"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("file", text="Файл")
        self.tree.heading("info", text="Формат")
        self.tree.heading("status", text="Назначение")
        self.tree.column("file", width=260, stretch=True)
        self.tree.column("info", width=190, stretch=False)
        self.tree.column("status", width=150, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._refresh_details())
        self.tree.bind("<Double-1>", lambda _event: self._assign_selected_wav())
        paned.add(left, weight=1)

        right = ttk.Frame(paned)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        paned.add(right, weight=1)

        bank_frame = ttk.Frame(right)
        bank_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bank_frame, text="Банк:").pack(side="left")
        bank = ttk.Combobox(
            bank_frame,
            textvariable=self.bank_var,
            values=list(kit_map.BANK_NAMES),
            width=4,
            state="readonly",
        )
        bank.pack(side="left", padx=6)
        bank.bind("<<ComboboxSelected>>", lambda _event: self._bank_changed())

        grid = ttk.Frame(right)
        grid.grid(row=1, column=0, sticky="nsew")
        for row in range(4):
            grid.rowconfigure(row, weight=1)
            for column in range(4):
                grid.columnconfigure(column, weight=1)
                pad_number = row * 4 + column + 1
                button = tk.Button(
                    grid,
                    text=f"{pad_number}",
                    width=14,
                    height=4,
                    font=("Segoe UI", 8),
                    relief="ridge",
                    command=lambda n=pad_number: self._select_bank_pad(n),
                )
                button.grid(row=row, column=column, sticky="nsew", padx=2, pady=2)
                self.pad_buttons[pad_number] = button

        detail = ttk.LabelFrame(right, text="Параметры пада", padding=8)
        detail.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        detail.columnconfigure(1, weight=1)

        ttk.Label(detail, text="Pad:").grid(row=0, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.pad_label_var).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(detail, text="Note:").grid(row=1, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.note_var).grid(
            row=1, column=1, sticky="w"
        )
        ttk.Label(detail, text="Файл:").grid(row=2, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.file_var).grid(
            row=2, column=1, sticky="w"
        )

        ttk.Label(detail, text="Gain:").grid(row=3, column=0, sticky="w")
        ttk.Spinbox(
            detail, from_=0.0, to=1.0, increment=0.01,
            textvariable=self.gain_var, width=8
        ).grid(row=3, column=1, sticky="w")
        ttk.Label(detail, text="Pan:").grid(row=3, column=2, sticky="e", padx=(12, 4))
        ttk.Spinbox(
            detail, from_=0.0, to=1.0, increment=0.01,
            textvariable=self.pan_var, width=8
        ).grid(row=3, column=3, sticky="w")

        ttk.Label(detail, text="Tune:").grid(row=4, column=0, sticky="w")
        ttk.Spinbox(
            detail, from_=-24.0, to=24.0, increment=0.1,
            textvariable=self.tune_var, width=8
        ).grid(row=4, column=1, sticky="w")
        ttk.Checkbutton(
            detail, text="Loop", variable=self.loop_var
        ).grid(row=4, column=2, columnspan=2, sticky="w", padx=(12, 0))

        buttons = ttk.Frame(detail)
        buttons.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.assign_button = ttk.Button(
            buttons, text="Назначить выбранный WAV", command=self._assign_selected_wav
        )
        self.assign_button.pack(side="left")
        self.update_button = ttk.Button(
            buttons, text="Обновить параметры", command=self._update_params
        )
        self.update_button.pack(side="left", padx=6)
        self.remove_button = ttk.Button(
            buttons, text="Снять с пада", command=self._remove_assignment
        )
        self.remove_button.pack(side="left")

        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.grid(row=2, column=0, sticky="ew")
        ttk.Button(bottom, text="Автоназначить", command=self._auto_assign).pack(
            side="left"
        )
        ttk.Button(bottom, text="Заполнить свободные", command=self._fill_free).pack(
            side="left", padx=6
        )
        ttk.Button(bottom, text="Загрузить map.json", command=self._load_map).pack(
            side="left"
        )
        ttk.Button(bottom, text="Сохранить map.json", command=self._save_map).pack(
            side="left", padx=6
        )
        ttk.Button(bottom, text="Сохранить и применить", command=self._save_and_apply).pack(
            side="left"
        )
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="right")
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side="right", padx=(0, 12)
        )

    def _samples_dir(self) -> Path | None:
        raw = self.samples_provider().strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_dir() else None

    def _load_note_map(self) -> None:
        template_raw = self.template_provider().strip()
        template = Path(template_raw) if template_raw else None
        self.pad_to_note, error = kit_map.pad_to_note_from_template(template)
        self.note_to_pad = {note: pad for pad, note in self.pad_to_note.items()}
        if error:
            self.status_var.set(
                "Не удалось прочитать padNoteMap шаблона; используется стандартная карта."
            )

    def refresh(self) -> None:
        self._load_note_map()
        folder = self._samples_dir()
        if folder is None:
            self.samples_label.configure(text="не выбрана")
            self.items = ()
            self.tree.delete(*self.tree.get_children())
            self._refresh_pad_grid()
            self._refresh_details()
            self.status_var.set("Выберите папку с семплами в главном окне.")
            return

        self.samples_label.configure(text=str(folder))
        try:
            self.items = kit_map.scan_wav_items(folder)
        except Exception as exc:
            messagebox.showerror("WAV", str(exc), parent=self)
            self.items = ()
            self.tree.delete(*self.tree.get_children())
            self._refresh_pad_grid()
            self._refresh_details()
            return

        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set(f"Найдено WAV: {len(self.items)}")

    def _assignment_by_file(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for pad_index, assignment in self.assignments.items():
            label = kit_map.bank_pad_label(pad_index)
            note = self.pad_to_note.get(pad_index)
            suffix = f" / {note}" if note is not None else ""
            result.setdefault(assignment.file, []).append(f"{label}{suffix}")
        return result

    def _refresh_tree(self) -> None:
        selected = self.tree.selection()
        selected_id = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        by_file = self._assignment_by_file()
        for item in self.items:
            status = ", ".join(by_file.get(item.relative, [])) or "—"
            self.tree.insert(
                "",
                "end",
                iid=item.relative,
                values=(item.relative, item.info, status),
            )
        if selected_id and self.tree.exists(selected_id):
            self.tree.selection_set(selected_id)

    def _bank_changed(self) -> None:
        bank = self.bank_var.get().strip().upper()
        if bank in kit_map.BANK_NAMES:
            self.selected_pad = kit_map.BANK_NAMES.index(bank) * kit_map.PADS_PER_BANK
        self._refresh_pad_grid()
        self._refresh_details()

    def _select_bank_pad(self, pad_number: int) -> None:
        bank = self.bank_var.get().strip().upper() or "A"
        try:
            self.selected_pad = kit_map.global_pad_index(bank, pad_number)
        except ValueError as exc:
            messagebox.showerror("Pad", str(exc), parent=self)
            return
        self._refresh_pad_grid()
        self._refresh_details()

    def _refresh_pad_grid(self) -> None:
        bank = self.bank_var.get().strip().upper() or "A"
        if bank not in kit_map.BANK_NAMES:
            bank = "A"
            self.bank_var.set(bank)
        bank_index = kit_map.BANK_NAMES.index(bank)
        for pad_number, button in self.pad_buttons.items():
            pad_index = bank_index * kit_map.PADS_PER_BANK + pad_number - 1
            note = self.pad_to_note.get(pad_index)
            label = f"{bank}{pad_number}"
            assignment = self.assignments.get(pad_index)
            sample = Path(assignment.file).stem[:14] if assignment else "—"
            note_text = f"note {note}" if note is not None else "no note"
            button.configure(
                text=f"{label}\n{note_text}\n{sample}",
                state="normal",
                relief="sunken" if self.selected_pad == pad_index else "ridge",
                bg="#dbeafe" if self.selected_pad == pad_index else "SystemButtonFace",
            )

    def _refresh_details(self) -> None:
        if self.selected_pad is None:
            self.pad_label_var.set("—")
            self.note_var.set("—")
            self.file_var.set("—")
            self.assign_button.configure(state="disabled")
            self.update_button.configure(state="disabled")
            self.remove_button.configure(state="disabled")
            return

        pad_index = self.selected_pad
        note = self.pad_to_note.get(pad_index)
        assignment = self.assignments.get(pad_index)
        self.pad_label_var.set(kit_map.bank_pad_label(pad_index))
        self.note_var.set("—" if note is None else str(note))
        if assignment is None:
            self.file_var.set("—")
            self.gain_var.set("1.0")
            self.pan_var.set("0.5")
            self.tune_var.set("0.0")
            self.loop_var.set(False)
            self.update_button.configure(state="disabled")
            self.remove_button.configure(state="disabled")
        else:
            self.file_var.set(assignment.file)
            self.gain_var.set(f"{assignment.gain:g}")
            self.pan_var.set(f"{assignment.pan:g}")
            self.tune_var.set(f"{assignment.tune:g}")
            self.loop_var.set(assignment.loop)
            self.update_button.configure(state="normal")
            self.remove_button.configure(state="normal")
        self.assign_button.configure(state="normal")

    def _read_params(self) -> tuple[float, float, float, bool] | None:
        try:
            gain = float(self.gain_var.get())
            pan = float(self.pan_var.get())
            tune = float(self.tune_var.get())
        except ValueError:
            messagebox.showerror("Параметры", "Gain/Pan/Tune должны быть числами.", parent=self)
            return None
        if not 0.0 <= gain <= 1.0:
            messagebox.showerror("Параметры", "Gain должен быть 0..1.", parent=self)
            return None
        if not 0.0 <= pan <= 1.0:
            messagebox.showerror("Параметры", "Pan должен быть 0..1.", parent=self)
            return None
        if not -24.0 <= tune <= 24.0:
            messagebox.showerror("Параметры", "Tune должен быть -24..24.", parent=self)
            return None
        return gain, pan, tune, bool(self.loop_var.get())

    def _assign_selected_wav(self) -> None:
        if self.selected_pad is None:
            messagebox.showinfo("Pad", "Сначала выберите pad.", parent=self)
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("WAV", "Сначала выберите WAV-файл.", parent=self)
            return
        relative = selection[0]
        params = self._read_params()
        if params is None:
            return
        gain, pan, tune, loop = params
        self.assignments[self.selected_pad] = kit_map.PadAssignment(
            pad_index=self.selected_pad,
            file=relative,
            gain=gain,
            pan=pan,
            tune=tune,
            loop=loop,
        )
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set(
            f"Назначено: {relative} → {kit_map.bank_pad_label(self.selected_pad)}"
        )

    def _update_params(self) -> None:
        if self.selected_pad is None:
            return
        existing = self.assignments.get(self.selected_pad)
        if existing is None:
            return
        params = self._read_params()
        if params is None:
            return
        gain, pan, tune, loop = params
        self.assignments[self.selected_pad] = kit_map.PadAssignment(
            pad_index=self.selected_pad,
            file=existing.file,
            gain=gain,
            pan=pan,
            tune=tune,
            loop=loop,
        )
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set("Параметры обновлены.")

    def _remove_assignment(self) -> None:
        if self.selected_pad is None:
            return
        if self.assignments.pop(self.selected_pad, None) is not None:
            self._refresh_tree()
            self._refresh_pad_grid()
            self._refresh_details()
            self.status_var.set("Назначение снято.")

    def _auto_assign(self) -> None:
        before = len(self.assignments)
        result = kit_map.auto_assign(self.items, self.assignments, self.note_to_pad)
        count = len(result) - before
        if count <= 0:
            messagebox.showinfo(
                "Автоназначение",
                "Новых совпадений не найдено.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Автоназначение",
            f"Назначить {count} семпл(ов) по именам файлов?",
            parent=self,
        ):
            return
        self.assignments = result
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set(f"Автоназначено: {count}")

    def _fill_free(self) -> None:
        before = len(self.assignments)
        result = kit_map.auto_assign(
            self.items,
            self.assignments,
            self.note_to_pad,
            fill_free=True,
        )
        count = len(result) - before
        if count <= 0:
            messagebox.showinfo(
                "Свободные пады",
                "Свободных падов или семплов не осталось.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Свободные пады",
            f"Занять {count} свободных падов оставшимися WAV?",
            parent=self,
        ):
            return
        self.assignments = result
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set(f"Занято падов: {count}")

    def _load_map(self) -> None:
        folder = self._samples_dir()
        initial = str(folder) if folder is not None else str(Path.cwd())
        path = filedialog.askopenfilename(
            parent=self,
            initialdir=initial,
            filetypes=[("JSON map", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.assignments = kit_map.load_kit_map(
                Path(path), self.note_to_pad
            )
        except Exception as exc:
            messagebox.showerror("Карта", str(exc), parent=self)
            return
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set(f"Загружено назначений: {len(self.assignments)}")

    def _validate_for_save(self) -> bool:
        if not self.assignments:
            messagebox.showerror("Карта", "Карта пуста.", parent=self)
            return False
        known = {item.relative for item in self.items}
        missing = sorted(
            assignment.file
            for assignment in self.assignments.values()
            if assignment.file not in known
        )
        if missing:
            messagebox.showerror(
                "Карта",
                "В папке нет файлов из карты:\n" + "\n".join(missing[:10]),
                parent=self,
            )
            return False
        return True

    def _save_map(self, *, apply: bool = False) -> None:
        if not self._validate_for_save():
            return
        folder = self._samples_dir()
        initial = str(folder) if folder is not None else str(Path.cwd())
        path = filedialog.asksaveasfilename(
            parent=self,
            initialdir=initial,
            initialfile="map.json",
            defaultextension=".json",
            filetypes=[("JSON map", "*.json")],
        )
        if not path:
            return
        try:
            kit_map.save_kit_map(Path(path), self.assignments)
        except Exception as exc:
            messagebox.showerror("Карта", str(exc), parent=self)
            return
        self.status_var.set(f"Сохранено: {path}")
        if apply:
            self.on_saved(Path(path))
            messagebox.showinfo(
                "Карта",
                "Карта сохранена и подставлена в поле --map.",
                parent=self,
            )

    def _save_and_apply(self) -> None:
        self._save_map(apply=True)
