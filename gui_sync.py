"""Окно MIDI Clock Sync: PC — мастер, MPC Sample — слейв."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from midi_clock import ClockEngine, MidiDevice, MidiOutput
from validators import validate_bpm


class SyncWindow(tk.Toplevel):
    """Отправляет MIDI Clock/Start/Stop на выбранный MIDI-выход."""

    def __init__(self, master: tk.Misc, *, bpm: str = "120") -> None:
        super().__init__(master)
        self.title("MPC XPJ Builder — MIDI Sync")
        self.geometry("680x560")
        self.minsize(600, 500)
        self.transient(master.winfo_toplevel())

        self.output: MidiOutput | None = None
        self.engine: ClockEngine | None = None
        self.devices: tuple[MidiDevice, ...] = ()
        self.device_map: dict[str, int] = {}
        self._after_id: str | None = None

        self.device_var = tk.StringVar(value="")
        self.bpm_var = tk.StringVar(value=bpm)
        self.status_var = tk.StringVar(value="")
        self.pulse_var = tk.StringVar(value="Импульсов: 0")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_devices()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        info = ttk.LabelFrame(outer, text="Схема", padding=8)
        info.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            info,
            text="PC — мастер, MPC Sample — слейв (MIDI Clock).",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            info,
            text=(
                "На MPC Sample: SHIFT + PAD 8 → MIDI Config → MIDI Port = USB, "
                "MIDI Sync In = Midi Clock, MIDI Sync Out = Off."
            ),
            wraplength=620,
            foreground="#444444",
        ).pack(anchor="w", pady=(4, 0))

        form = ttk.LabelFrame(outer, text="Параметры", padding=8)
        form.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="MIDI-выход").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self.device_combo = ttk.Combobox(
            form,
            textvariable=self.device_var,
            state="readonly",
        )
        self.device_combo.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(form, text="Обновить", command=self.refresh_devices).grid(
            row=0, column=2, padx=(8, 0), pady=3
        )

        ttk.Label(form, text="BPM").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        tempo = ttk.Frame(form)
        tempo.grid(row=1, column=1, sticky="w", pady=3)
        ttk.Entry(tempo, textvariable=self.bpm_var, width=10).pack(side="left")
        ttk.Button(tempo, text="Применить", command=self._apply_bpm).pack(
            side="left", padx=6
        )

        ttk.Label(
            form,
            text=(
                "MIDI Clock — 24 импульса на четверть. Синхронизация не "
                "sample-accurate: возможен небольшой джиттер."
            ),
            wraplength=620,
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        state = ttk.LabelFrame(outer, text="Состояние", padding=8)
        state.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        state.columnconfigure(0, weight=1)
        self.indicator = tk.Label(
            state,
            text="● STOP",
            fg="#a00000",
            font=("Consolas", 20, "bold"),
        )
        self.indicator.grid(row=0, column=0, sticky="w")
        ttk.Label(state, textvariable=self.pulse_var).grid(
            row=0, column=1, sticky="e"
        )
        ttk.Label(
            state,
            text=(
                "Start отправляет Start + Clock. Stop отправляет Stop. "
                "При изменении BPM темп меняется на лету."
            ),
            wraplength=620,
            foreground="#666666",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        bottom = ttk.Frame(outer)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.start_button = ttk.Button(
            bottom, text="▶ Start", command=self._start
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            bottom, text="■ Stop", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(bottom, text="Закрыть", command=self._on_close).pack(
            side="right"
        )
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side="right", padx=(0, 12)
        )

    def refresh_devices(self) -> None:
        if self.engine is not None:
            return
        self.devices = MidiOutput.list_devices()
        displays = [f"{device.index}: {device.name}" for device in self.devices]
        self.device_map = {
            f"{device.index}: {device.name}": device.index
            for device in self.devices
        }
        self.device_combo.configure(values=displays)
        if displays:
            preferred = next(
                (
                    display
                    for display in displays
                    if "mpc" in display.casefold()
                ),
                displays[0],
            )
            self.device_var.set(preferred)
            self.status_var.set(f"Найдено MIDI-выходов: {len(displays)}")
        else:
            self.device_var.set("")
            self.status_var.set(
                "MIDI-устройства не найдены. Подключите MPC Sample по USB."
            )

    def _selected_device(self) -> int | None:
        display = self.device_var.get().strip()
        return self.device_map.get(display)

    def _start(self) -> None:
        if self.engine is not None and self.engine.running:
            return
        try:
            bpm = validate_bpm(self.bpm_var.get())
        except Exception as exc:
            messagebox.showerror("MIDI Sync", str(exc), parent=self)
            return
        device = self._selected_device()
        if device is None:
            messagebox.showerror(
                "MIDI Sync",
                "Выберите MIDI-выход. Если список пуст, проверьте USB-подключение "
                "и режим MIDI Port = USB на MPC Sample.",
                parent=self,
            )
            return

        output = MidiOutput()
        try:
            output.open(device)
            engine = ClockEngine(output, bpm)
            engine.start()
        except Exception as exc:
            output.close()
            messagebox.showerror("MIDI Sync", str(exc), parent=self)
            return

        self.output = output
        self.engine = engine
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.device_combo.configure(state="disabled")
        self.indicator.configure(text="● PLAY", fg="#008000")
        self.status_var.set(f"Clock → {self.device_var.get()} @ {bpm:g} BPM")
        self._schedule_poll()

    def _stop(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.engine is not None:
            self.engine.stop()
            self.engine = None
        if self.output is not None:
            self.output.close()
            self.output = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.device_combo.configure(state="readonly")
        self.indicator.configure(text="● STOP", fg="#a00000")
        self.status_var.set("Остановлено.")

    def _apply_bpm(self) -> None:
        try:
            bpm = validate_bpm(self.bpm_var.get())
        except Exception as exc:
            messagebox.showerror("MIDI Sync", str(exc), parent=self)
            return
        if self.engine is not None:
            self.engine.set_bpm(bpm)
            self.status_var.set(f"Темп изменён: {bpm:g} BPM")
        else:
            self.status_var.set(f"BPM: {bpm:g}")

    def _schedule_poll(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.after(200, self._poll)

    def _poll(self) -> None:
        self._after_id = None
        engine = self.engine
        if engine is None:
            return
        self.pulse_var.set(f"Импульсов: {engine.pulses}")
        error = engine.last_error
        if error is not None:
            self._stop()
            messagebox.showerror("MIDI Sync", str(error), parent=self)
            return
        if not engine.running:
            self._stop()
            return
        self._schedule_poll()

    def _on_close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        self._stop()
        super().destroy()


def sync_window(master: tk.Misc, *, bpm: str = "120") -> SyncWindow:
    """Создать окно sync."""
    return SyncWindow(master, bpm=bpm)
