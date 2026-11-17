"""Окно редактора карты семплов."""

from __future__ import annotations

import queue
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Sequence

import audio_preview
import kit_map
import map_presets
import project_editor
from errors import ValidationError
from midi_clock import (
    MidiDevice,
    MidiInput,
    MidiOutput,
    decode_note,
    note_off,
    note_on,
)

PAD_GRID_ROWS = 4


def pad_number_at(row: int, column: int) -> int:
    """Номер пада для позиции сетки: A1 внизу слева, A16 вверху справа."""
    return (PAD_GRID_ROWS - 1 - row) * 4 + column + 1


def preview_source(
    items: Sequence[kit_map.WavItem],
    assignments: dict[int, kit_map.PadAssignment],
    selected_relative: str | None,
    selected_pad: int | None,
    folder: Path | None,
) -> tuple[Path | None, str | None]:
    """Выбрать WAV для прослушивания: сначала выделение в списке, потом пад."""
    if selected_relative:
        for item in items:
            if item.relative == selected_relative:
                return item.path, item.relative
    if selected_pad is not None and folder is not None:
        assignment = assignments.get(selected_pad)
        if assignment is not None:
            path = folder / assignment.file
            if path.is_file():
                return path, assignment.file
    return None, None


class MapEditorWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        samples_provider: Callable[[], str] | None = None,
        template_provider: Callable[[], str] | None = None,
        on_saved: Callable[[Path], None] | None = None,
        project_path: Path | None = None,
    ) -> None:
        super().__init__(master)
        self.project_path = Path(project_path) if project_path else None
        self.project_header = None
        self.project_payload = None
        self.project_summary = None
        self.project_samples_dir: Path | None = None
        self.assignments: dict[int, kit_map.PadAssignment] = {}
        if self.project_path is not None:
            (
                self.project_header,
                self.project_payload,
                self.project_summary,
            ) = project_editor.read_project(self.project_path)
            self.project_samples_dir = self.project_summary.data_dir
            self.assignments = project_editor.read_pad_assignments(
                self.project_payload
            )
            self.title("MPC XPJ Builder — пады проекта")
        else:
            self.title("MPC XPJ Builder — карта семплов")
        self.geometry("1120x840")
        self.minsize(900, 700)
        self.transient(master.winfo_toplevel())
        self.samples_provider = samples_provider or (lambda: "")
        self.template_provider = template_provider or (lambda: "")
        self.on_saved = on_saved or (lambda path: None)

        self.items: tuple[kit_map.WavItem, ...] = ()
        self.pad_to_note: dict[int, int] = kit_map.default_pad_to_note()
        self.note_to_pad: dict[int, int] = {
            note: pad for pad, note in self.pad_to_note.items()
        }
        self.selected_pad: int | None = None
        self.pad_buttons: dict[int, tk.Button] = {}
        self.midi_devices: tuple[MidiDevice, ...] = ()
        self.midi_map: dict[str, int] = {}
        self.midi_input: MidiInput | None = None
        self.midi_queue: queue.Queue[int] = queue.Queue()
        self._midi_after: str | None = None
        self.midi_out_devices: tuple[MidiDevice, ...] = ()
        self.midi_out_map: dict[str, int] = {}
        self.midi_output: MidiOutput | None = None
        self._audition_after: str | None = None
        self._audition_note: int | None = None

        self.bank_var = tk.StringVar(value="A")
        self.pad_label_var = tk.StringVar(value="—")
        self.note_var = tk.StringVar(value="—")
        self.file_var = tk.StringVar(value="—")
        self.gain_var = tk.StringVar(value="1.0")
        self.pan_var = tk.StringVar(value="0.5")
        self.tune_var = tk.StringVar(value="0.0")
        self.loop_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Выберите пад и WAV.")
        self.preset_var = tk.StringVar(value="")
        self.midi_var = tk.StringVar(value="")
        self.midi_out_var = tk.StringVar(value="")
        self.audition_var = tk.BooleanVar(value=True)
        self.learn_var = tk.BooleanVar(value=False)
        self.midi_status_var = tk.StringVar(value="Pad MIDI выключен.")
        self.preview = audio_preview.AudioPreview()
        self._preview_after: str | None = None
        self._tkdnd_enabled = False

        self._build_ui()
        self._load_note_map()
        self.refresh()
        self._refresh_midi_devices()
        self._enable_pad_dnd()

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
            text="Все 128 падов доступны для загрузки семплов; MIDI-sequence может играть любые ноты при --extended-notes. WAV можно перетащить прямо на пад.",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        midi_frame = ttk.Frame(top)
        midi_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        midi_frame.columnconfigure(1, weight=1)
        ttk.Label(midi_frame, text="Pad MIDI:").grid(row=0, column=0, sticky="w")
        self.midi_combo = ttk.Combobox(
            midi_frame,
            textvariable=self.midi_var,
            state="readonly",
        )
        self.midi_combo.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(
            midi_frame, text="Обновить", command=self._refresh_midi_devices
        ).grid(row=0, column=2, sticky="e")
        self.midi_button = ttk.Button(
            midi_frame,
            text="▶ Слушать пады",
            command=self._toggle_midi,
        )
        self.midi_button.grid(row=0, column=3, sticky="e", padx=(8, 0))
        ttk.Label(midi_frame, text="Audition →").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self.midi_out_combo = ttk.Combobox(
            midi_frame,
            textvariable=self.midi_out_var,
            state="readonly",
        )
        self.midi_out_combo.grid(
            row=1, column=1, sticky="ew", padx=8, pady=(4, 0)
        )
        self.midi_out_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._close_midi_output()
        )
        ttk.Checkbutton(
            midi_frame,
            text="Audition",
            variable=self.audition_var,
        ).grid(row=1, column=2, sticky="e", pady=(4, 0))
        ttk.Checkbutton(
            midi_frame,
            text="MIDI Learn",
            variable=self.learn_var,
        ).grid(row=1, column=3, sticky="e", padx=(8, 0), pady=(4, 0))
        ttk.Label(
            midi_frame,
            textvariable=self.midi_status_var,
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

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
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
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
        ttk.Label(
            bank_frame,
            text="A1 внизу слева, A16 вверху справа",
            foreground="#666666",
        ).pack(side="right")

        grid = ttk.Frame(right)
        grid.grid(row=1, column=0, sticky="nsew")
        for row in range(4):
            grid.rowconfigure(row, weight=1)
            for column in range(4):
                grid.columnconfigure(column, weight=1)
                pad_number = pad_number_at(row, column)
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
        self.play_button = ttk.Button(
            buttons, text="▶ Прослушать", command=self._play_preview
        )
        self.play_button.pack(side="left", padx=(12, 0))
        self.stop_button = ttk.Button(
            buttons, text="■ Стоп", command=self._stop_preview
        )
        self.stop_button.pack(side="left", padx=(6, 0))

        edit_buttons = ttk.Frame(detail)
        edit_buttons.grid(
            row=6, column=0, columnspan=4, sticky="ew", pady=(6, 0)
        )
        self.update_button = ttk.Button(
            edit_buttons, text="Обновить параметры", command=self._update_params
        )
        self.update_button.pack(side="left")
        self.remove_button = ttk.Button(
            edit_buttons, text="Снять с пада", command=self._remove_assignment
        )
        self.remove_button.pack(side="left", padx=6)

        preset_bar = ttk.LabelFrame(self, text="Пресеты карт", padding=(8, 6))
        preset_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        preset_bar.columnconfigure(1, weight=1)
        ttk.Label(preset_bar, text="Пресет:").grid(row=0, column=0, sticky="w")
        self.preset_combo = ttk.Combobox(
            preset_bar,
            textvariable=self.preset_var,
            values=self._preset_names(),
            state="readonly",
        )
        self.preset_combo.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(
            preset_bar, text="Загрузить", command=self._load_preset
        ).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(
            preset_bar, text="Сохранить…", command=self._save_preset
        ).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(
            preset_bar, text="Удалить", command=self._delete_preset
        ).grid(row=0, column=4)

        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.grid(row=3, column=0, sticky="ew")
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
        if self.project_path is not None:
            ttk.Button(
                bottom,
                text="Сохранить в .xpj",
                command=self._save_project,
            ).pack(side="left", padx=(12, 0))
            ttk.Button(
                bottom,
                text="Копия .xpj…",
                command=self._save_project_copy,
            ).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="right")
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side="right", padx=(0, 12)
        )

    def _preset_names(self) -> list[str]:
        return [preset.name for preset in map_presets.list_presets()]

    def _refresh_presets(self, select: str | None = None) -> None:
        names = self._preset_names()
        self.preset_combo.configure(values=names)
        if select is not None:
            self.preset_var.set(select)
        elif self.preset_var.get() not in names:
            self.preset_var.set("")

    def _selected_preset(self) -> map_presets.MapPreset | None:
        name = self.preset_var.get().strip()
        if not name:
            return None
        for preset in map_presets.list_presets():
            if preset.name == name:
                return preset
        return None

    def _load_preset(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            messagebox.showinfo(
                "Пресеты",
                "Сначала выберите пресет в списке.",
                parent=self,
            )
            return
        try:
            assignments = map_presets.load_preset(preset, self.note_to_pad)
        except Exception as exc:
            messagebox.showerror("Пресет", str(exc), parent=self)
            return
        self.assignments = assignments
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()
        self.status_var.set(f"Загружен пресет: {preset.name}")

    def _save_preset(self) -> None:
        folder_name = Path(self.samples_label.cget("text")).name
        initial = self.preset_var.get().strip() or folder_name or "Моя карта"
        name = simpledialog.askstring(
            "Пресет карты",
            "Имя пресета:",
            initialvalue=initial,
            parent=self,
        )
        if name is None:
            return
        try:
            preset = map_presets.save_preset(name, self.assignments)
        except Exception as exc:
            messagebox.showerror("Пресет", str(exc), parent=self)
            return
        self._refresh_presets(preset.name)
        self.status_var.set(f"Пресет сохранён: {preset.name}")

    def _delete_preset(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            messagebox.showinfo(
                "Пресеты",
                "Сначала выберите пресет в списке.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Удалить пресет",
            f"Удалить пресет {preset.name!r}?",
            parent=self,
        ):
            return
        try:
            map_presets.delete_preset(preset)
        except Exception as exc:
            messagebox.showerror("Пресет", str(exc), parent=self)
            return
        self._refresh_presets()
        self.preset_var.set("")
        self.status_var.set(f"Пресет удалён: {preset.name}")

    def _samples_dir(self) -> Path | None:
        if self.project_path is not None:
            return self.project_samples_dir
        raw = self.samples_provider().strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_dir() else None

    def _load_note_map(self) -> None:
        if self.project_path is not None:
            template = self.project_path
        else:
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
        self._audition_pad(self.selected_pad)

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
        has_selection = bool(self.tree.selection())
        has_pad_sample = (
            self.selected_pad is not None
            and self.selected_pad in self.assignments
        )
        self.play_button.configure(
            state="normal" if (has_selection or has_pad_sample) else "disabled"
        )
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

    def _on_tree_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if self.tree.selection() != (row,):
            self.tree.selection_set(row)
        self._refresh_details()
        self._play_preview()

    def _play_preview(self) -> None:
        selection = self.tree.selection()
        selected_relative = selection[0] if selection else None
        path, label = preview_source(
            self.items,
            self.assignments,
            selected_relative,
            self.selected_pad,
            self._samples_dir(),
        )
        if path is None or label is None:
            messagebox.showinfo(
                "Прослушивание",
                "Выберите WAV в списке или пад с назначенным семплом.",
                parent=self,
            )
            return
        self._stop_preview()
        try:
            duration = self.preview.play(path)
        except Exception as exc:
            messagebox.showerror("Прослушивание", str(exc), parent=self)
            return

        self.status_var.set(f"▶ {label}")
        source_relative = selected_relative or label
        item_duration = next(
            (
                item.duration
                for item in self.items
                if item.relative == source_relative
            ),
            None,
        )
        seconds = duration or item_duration or 5.0
        self._preview_after = self.after(
            max(200, int(seconds * 1000) + 120),
            self._stop_preview,
        )

    def _stop_preview(self) -> None:
        if self._preview_after is not None:
            try:
                self.after_cancel(self._preview_after)
            except Exception:
                pass
            self._preview_after = None
        self.preview.stop()
        self.status_var.set("Прослушивание остановлено.")

    def destroy(self) -> None:
        self._stop_midi()
        self._close_midi_output()
        self._stop_preview()
        super().destroy()

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

    def _project_payload_with_assignments(self) -> dict | None:
        if self.project_payload is None:
            return None
        try:
            return project_editor.apply_pad_assignments(
                self.project_payload,
                self.assignments,
                self.project_samples_dir,
            )
        except Exception as exc:
            messagebox.showerror("Проект", str(exc), parent=self)
            return None

    def _reload_project(self) -> None:
        if self.project_path is None:
            return
        (
            self.project_header,
            self.project_payload,
            self.project_summary,
        ) = project_editor.read_project(self.project_path)
        self.project_samples_dir = self.project_summary.data_dir
        self.assignments = project_editor.read_pad_assignments(
            self.project_payload
        )
        self.refresh()

    def _save_project(self) -> None:
        if self.project_path is None or self.project_payload is None:
            return
        payload = self._project_payload_with_assignments()
        if payload is None:
            return
        try:
            _path, backup = project_editor.save_project_in_place(
                self.project_path,
                self.project_header,
                payload,
            )
        except Exception as exc:
            messagebox.showerror("Проект", str(exc), parent=self)
            return
        self._reload_project()
        self.status_var.set(f"Сохранено в .xpj. Backup: {backup.name}")
        messagebox.showinfo(
            "Проект",
            f"Пады сохранены в:\n{self.project_path}\n\nBackup:\n{backup}",
            parent=self,
        )

    def _save_project_copy(self) -> None:
        if self.project_path is None or self.project_payload is None:
            return
        payload = self._project_payload_with_assignments()
        if payload is None:
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить копию проекта",
            defaultextension=".xpj",
            initialdir=str(self.project_path.parent),
            initialfile=f"{self.project_path.stem} copy.xpj",
            filetypes=[("XPJ project", "*.xpj"), ("All files", "*.*")],
        )
        if not target:
            return
        try:
            xpj_path, data_path = project_editor.save_project_copy(
                self.project_path,
                Path(target),
                self.project_header,
                payload,
            )
        except Exception as exc:
            messagebox.showerror("Проект", str(exc), parent=self)
            return
        self.status_var.set(f"Копия сохранена: {xpj_path.name}")
        messagebox.showinfo(
            "Копия сохранена",
            f"XPJ:\n{xpj_path}\n\n"
            f"ProjectData:\n{data_path if data_path else 'нет папки ресурсов'}",
            parent=self,
        )

    def _ensure_midi_output(self) -> bool:
        if self.midi_output is not None:
            return True
        label = self.midi_out_var.get().strip()
        index = self.midi_out_map.get(label)
        if index is None:
            self.midi_status_var.set(
                "Выберите MIDI-выход для Audition."
            )
            return False
        output = MidiOutput()
        try:
            output.open(index)
        except Exception as exc:
            output.close()
            self.midi_status_var.set(f"Audition недоступен: {exc}")
            return False
        self.midi_output = output
        return True

    def _finish_audition(self) -> None:
        if self._audition_after is not None:
            try:
                self.after_cancel(self._audition_after)
            except Exception:
                pass
            self._audition_after = None
        if self.midi_output is not None and self._audition_note is not None:
            try:
                self.midi_output.send(note_off(self._audition_note))
            except Exception:
                pass
        self._audition_note = None

    def _close_midi_output(self) -> None:
        self._finish_audition()
        if self.midi_output is not None:
            self.midi_output.close()
            self.midi_output = None

    def _audition_pad(self, pad_index: int | None) -> None:
        if pad_index is None or not self.audition_var.get():
            return
        note = self.pad_to_note.get(pad_index)
        if note is None:
            return
        if not self._ensure_midi_output():
            return
        assert self.midi_output is not None
        try:
            self.midi_output.send(note_on(note, 100))
        except Exception as exc:
            self.midi_status_var.set(f"Audition недоступен: {exc}")
            self._close_midi_output()
            return
        self._finish_audition()
        self._audition_note = note
        self._audition_after = self.after(220, self._finish_audition)
        self.midi_status_var.set(f"Audition: note {note}")

    def _enable_pad_dnd(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES
        except Exception:
            return
        try:
            for pad_number, button in self.pad_buttons.items():
                button.drop_target_register(DND_FILES)
                button.dnd_bind(
                    "<<Drop>>",
                    lambda event, number=pad_number: self._handle_pad_drop(
                        event, number
                    ),
                )
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._handle_list_drop)
            self._tkdnd_enabled = True
        except Exception:
            self._tkdnd_enabled = False

    def _drop_paths(self, event) -> list[Path]:
        try:
            values = self.tk.splitlist(event.data)
        except Exception:
            values = [event.data]
        return [Path(str(value)) for value in values]

    def _handle_pad_drop(self, event, pad_number: int) -> str:
        paths = self._drop_paths(event)
        bank = self.bank_var.get().strip().upper() or "A"
        try:
            pad_index = kit_map.global_pad_index(bank, pad_number)
        except ValueError:
            return "copy"
        self._import_samples(paths, pad_index)
        return getattr(event, "action", "copy")

    def _handle_list_drop(self, event) -> str:
        self._import_samples(self._drop_paths(event), None)
        return getattr(event, "action", "copy")

    def _unique_target(self, source: Path, folder: Path) -> Path:
        target = folder / source.name
        try:
            if source.resolve() == target.resolve():
                return target
        except OSError:
            pass
        if target.exists():
            base = source.stem
            suffix = source.suffix
            counter = 2
            while True:
                candidate = folder / f"{base}_{counter}{suffix}"
                if not candidate.exists():
                    return candidate
                counter += 1
        return target

    def _import_samples(
        self,
        paths: list[Path],
        pad_index: int | None,
    ) -> None:
        wavs = [
            path
            for path in paths
            if path.is_file() and path.suffix.lower() == ".wav"
        ]
        if not wavs:
            self.status_var.set("Нужно перетащить WAV-файл.")
            return

        imported: list[str] = []
        if self.project_path is not None:
            if self.project_payload is None or self.project_samples_dir is None:
                messagebox.showerror(
                    "Пады",
                    "Не найдена папка ресурсов проекта.",
                    parent=self,
                )
                return
            for wav in wavs:
                try:
                    payload, relative = project_editor.import_sample(
                        self.project_payload,
                        self.project_samples_dir,
                        wav,
                    )
                except Exception as exc:
                    messagebox.showerror("Импорт WAV", str(exc), parent=self)
                    continue
                self.project_payload = payload
                imported.append(relative)
        else:
            folder = self._samples_dir()
            if folder is None:
                messagebox.showerror(
                    "Импорт WAV",
                    "Сначала выберите папку с WAV.",
                    parent=self,
                )
                return
            for wav in wavs:
                target = self._unique_target(wav, folder)
                try:
                    if target.resolve() != wav.resolve():
                        shutil.copy2(wav, target)
                except OSError as exc:
                    messagebox.showerror(
                        "Импорт WAV",
                        f"Не удалось скопировать {wav}: {exc}",
                        parent=self,
                    )
                    continue
                imported.append(target.relative_to(folder).as_posix())

        if not imported:
            return
        self.refresh()
        first = imported[0]
        if self.tree.exists(first):
            self.tree.selection_set(first)
            self.tree.see(first)
        if pad_index is not None:
            self._assign_relative_to_pad(first, pad_index)
            label = kit_map.bank_pad_label(pad_index)
            self.status_var.set(f"Импортировано: {first} → {label}")
            self.midi_status_var.set(
                f"WAV: {first} → {label}; сохраните проект."
            )
        else:
            self.status_var.set(f"Импортировано WAV: {len(imported)}")
        self._refresh_details()

    def _assign_relative_to_pad(self, relative: str, pad_index: int) -> None:
        params = self._read_params()
        if params is None:
            return
        gain, pan, tune, loop = params
        self.assignments[pad_index] = kit_map.PadAssignment(
            pad_index=pad_index,
            file=relative,
            gain=gain,
            pan=pan,
            tune=tune,
            loop=loop,
        )
        self._refresh_tree()
        self._refresh_pad_grid()
        self._refresh_details()

    def _refresh_midi_devices(self) -> None:
        if self.midi_input is not None or self.midi_output is not None:
            return
        self.midi_devices = MidiInput.list_devices()
        displays = [f"{device.index}: {device.name}" for device in self.midi_devices]
        self.midi_map = {
            f"{device.index}: {device.name}": device.index
            for device in self.midi_devices
        }
        self.midi_combo.configure(values=displays)
        if displays:
            preferred = next(
                (
                    display
                    for display in displays
                    if "mpc" in display.casefold()
                ),
                displays[0],
            )
            self.midi_var.set(preferred)
        else:
            self.midi_var.set("")

        self.midi_out_devices = MidiOutput.list_devices()
        out_displays = [
            f"{device.index}: {device.name}"
            for device in self.midi_out_devices
        ]
        self.midi_out_map = {
            f"{device.index}: {device.name}": device.index
            for device in self.midi_out_devices
        }
        self.midi_out_combo.configure(values=out_displays)
        if out_displays:
            preferred_out = next(
                (
                    display
                    for display in out_displays
                    if "mpc" in display.casefold()
                ),
                out_displays[0],
            )
            self.midi_out_var.set(preferred_out)
        else:
            self.midi_out_var.set("")

        if displays or out_displays:
            self.midi_status_var.set(
                f"MIDI: входов {len(displays)}, выходов {len(out_displays)}. "
                "На MPC: Pad MIDI Out = Always; для Audition — Pad MIDI In = On."
            )
        else:
            self.midi_status_var.set("MIDI-устройства не найдены.")

    def _toggle_midi(self) -> None:
        if self.midi_input is not None:
            self._stop_midi()
            return
        label = self.midi_var.get().strip()
        index = self.midi_map.get(label)
        if index is None:
            messagebox.showerror(
                "Pad MIDI",
                "Выберите MIDI-вход. На MPC включите Pad MIDI Out = Always.",
                parent=self,
            )
            return
        midi_input = MidiInput()
        try:
            midi_input.open(index, self._on_midi_message)
            midi_input.start()
        except Exception as exc:
            midi_input.close()
            messagebox.showerror("Pad MIDI", str(exc), parent=self)
            return
        self.midi_input = midi_input
        self.midi_button.configure(text="■ Стоп")
        self.midi_combo.configure(state="disabled")
        self.midi_status_var.set(f"Слушаю пады: {label}")
        self._midi_after = self.after(50, self._poll_midi)

    def _on_midi_message(self, message: int) -> None:
        self.midi_queue.put(message)

    def _poll_midi(self) -> None:
        self._midi_after = None
        while True:
            try:
                message = self.midi_queue.get_nowait()
            except queue.Empty:
                break
            note = decode_note(message)
            if note is not None:
                self._mirror_pad(*note)
        if self.midi_input is not None:
            self._midi_after = self.after(50, self._poll_midi)

    def _mirror_pad(self, note: int, velocity: int) -> None:
        pad = self.note_to_pad.get(note)
        if pad is None:
            self.midi_status_var.set(
                f"MIDI note {note} · velocity {velocity} (нет такого пада)"
            )
            return
        self.bank_var.set(
            kit_map.BANK_NAMES[pad // kit_map.PADS_PER_BANK]
        )
        self.selected_pad = pad
        learned: str | None = None
        if self.learn_var.get():
            selection = self.tree.selection()
            if selection:
                params = self._read_params()
                if params is not None:
                    gain, pan, tune, loop = params
                    relative = selection[0]
                    self.assignments[pad] = kit_map.PadAssignment(
                        pad_index=pad,
                        file=relative,
                        gain=gain,
                        pan=pan,
                        tune=tune,
                        loop=loop,
                    )
                    self._refresh_tree()
                    learned = relative
        self._refresh_pad_grid()
        self._refresh_details()
        label = kit_map.bank_pad_label(pad)
        self.status_var.set(
            f"MPC: {label} · note {note} · velocity {velocity}"
        )
        if learned is not None:
            self.midi_status_var.set(
                f"MIDI Learn: {learned} → {label}"
            )
        elif self.learn_var.get():
            self.midi_status_var.set(
                f"MIDI Learn: выбран {label}; выберите WAV в списке."
            )
        else:
            self.midi_status_var.set(f"Pad MIDI: {label} · note {note}")

    def _stop_midi(self) -> None:
        if self._midi_after is not None:
            try:
                self.after_cancel(self._midi_after)
            except Exception:
                pass
            self._midi_after = None
        if self.midi_input is not None:
            self.midi_input.stop()
            self.midi_input.close()
            self.midi_input = None
        self.midi_button.configure(text="▶ Слушать пады")
        self.midi_combo.configure(state="readonly")
        self.midi_status_var.set("Pad MIDI выключен.")
