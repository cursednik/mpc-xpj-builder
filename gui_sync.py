"""Окно MIDI Clock Sync: PC ↔ MPC Sample."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from midi_clock import ClockEngine, ClockMonitor, MidiDevice, MidiInput, MidiOutput
from validators import validate_bpm


class SyncWindow(tk.Toplevel):
    """MIDI Clock в обе стороны: PC-мастер или MPC-мастер."""

    def __init__(self, master: tk.Misc, *, bpm: str = "120") -> None:
        super().__init__(master)
        self.title("MPC XPJ Builder — MIDI Sync")
        self.geometry("760x620")
        self.minsize(680, 560)
        self.transient(master.winfo_toplevel())

        self.output: MidiOutput | None = None
        self.engine: ClockEngine | None = None
        self.input: MidiInput | None = None
        self.monitor: ClockMonitor | None = None
        self.devices: tuple[MidiDevice, ...] = ()
        self.device_map: dict[str, int] = {}
        self._after_id: str | None = None

        self.mode_var = tk.StringVar(value="pc")
        self.device_label_var = tk.StringVar(value="MIDI-выход")
        self.device_var = tk.StringVar(value="")
        self.bpm_var = tk.StringVar(value=bpm)
        self.status_var = tk.StringVar(value="")
        self.pulse_var = tk.StringVar(value="Импульсов: 0")
        self.incoming_var = tk.StringVar(value="BPM: —")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_devices()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        info = ttk.LabelFrame(outer, text="Схема", padding=8)
        info.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            info,
            text="MIDI Clock: PC и MPC Sample могут быть мастером по очереди.",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            info,
            text=(
                "На MPC Sample: SHIFT + PAD 8 → MIDI Config → MIDI Port = USB. "
                "Для PC-мастера: MIDI Sync In = Midi Clock, Sync Out = Off. "
                "Для MPC-мастера: MIDI Sync Out = Midi Clock, Sync In = Off."
            ),
            wraplength=700,
            foreground="#444444",
        ).pack(anchor="w", pady=(4, 0))

        mode = ttk.LabelFrame(outer, text="Режим", padding=8)
        mode.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.pc_radio = ttk.Radiobutton(
            mode,
            text="PC → MPC (PC мастер)",
            variable=self.mode_var,
            value="pc",
            command=self._mode_changed,
        )
        self.pc_radio.pack(side="left")
        self.mpc_radio = ttk.Radiobutton(
            mode,
            text="MPC → PC (MPC мастер)",
            variable=self.mode_var,
            value="mpc",
            command=self._mode_changed,
        )
        self.mpc_radio.pack(side="left", padx=16)

        form = ttk.LabelFrame(outer, text="Параметры", padding=8)
        form.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, textvariable=self.device_label_var).grid(
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

        self.bpm_row = ttk.Frame(form)
        self.bpm_row.grid(
            row=1, column=0, columnspan=3, sticky="w", pady=3
        )
        ttk.Label(self.bpm_row, text="BPM мастера").pack(side="left")
        ttk.Entry(self.bpm_row, textvariable=self.bpm_var, width=10).pack(
            side="left", padx=8
        )
        ttk.Button(
            self.bpm_row, text="Применить", command=self._apply_bpm
        ).pack(side="left")

        ttk.Label(
            form,
            text=(
                "MIDI Clock — 24 импульса на четверть. Синхронизация не "
                "sample-accurate: возможен небольшой джиттер."
            ),
            wraplength=700,
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        state = ttk.LabelFrame(outer, text="Состояние", padding=8)
        state.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        state.columnconfigure(0, weight=1)
        self.indicator = tk.Label(
            state,
            text="● STOP",
            fg="#a00000",
            font=("Consolas", 20, "bold"),
        )
        self.indicator.grid(row=0, column=0, sticky="w")
        ttk.Label(state, textvariable=self.pulse_var).grid(
            row=0, column=1, sticky="e", padx=(0, 16)
        )
        ttk.Label(state, textvariable=self.incoming_var).grid(
            row=0, column=2, sticky="e"
        )
        ttk.Label(
            state,
            text=(
                "PC-мастер: Start отправляет Start + Clock, Stop отправляет Stop. "
                "MPC-мастер: приложение слушает Clock и показывает BPM."
            ),
            wraplength=700,
            foreground="#666666",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        bottom = ttk.Frame(outer)
        bottom.grid(row=4, column=0, sticky="ew", pady=(10, 0))
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

    def _running(self) -> bool:
        return bool(
            (self.engine is not None and self.engine.running)
            or self.input is not None
        )

    def refresh_devices(self) -> None:
        if self._running():
            return
        pc_mode = self.mode_var.get() == "pc"
        self.devices = (
            MidiOutput.list_devices() if pc_mode else MidiInput.list_devices()
        )
        displays = [f"{device.index}: {device.name}" for device in self.devices]
        self.device_map = {
            f"{device.index}: {device.name}": device.index
            for device in self.devices
        }
        self.device_combo.configure(values=displays)
        noun = "выходов" if pc_mode else "входов"
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
            self.status_var.set(f"Найдено MIDI-{noun}: {len(displays)}")
        else:
            self.device_var.set("")
            self.status_var.set(
                f"MIDI-{noun} не найдены. Подключите MPC Sample по USB."
            )

    def _selected_device(self) -> int | None:
        display = self.device_var.get().strip()
        return self.device_map.get(display)

    def _mode_changed(self) -> None:
        pc_mode = self.mode_var.get() == "pc"
        self.device_label_var.set("MIDI-выход" if pc_mode else "MIDI-вход")
        self.start_button.configure(
            text="▶ Start" if pc_mode else "▶ Слушать"
        )
        if pc_mode:
            self.bpm_row.grid(
                row=1, column=0, columnspan=3, sticky="w", pady=3
            )
        else:
            self.bpm_row.grid_remove()
        self.incoming_var.set("BPM: —")
        self.indicator.configure(text="● STOP", fg="#a00000")
        self.pulse_var.set("Импульсов: 0")
        self.refresh_devices()

    def _start(self) -> None:
        if self._running():
            return
        if self.mode_var.get() == "pc":
            self._start_pc()
        else:
            self._start_mpc()

    def _start_pc(self) -> None:
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
        self._enter_running()
        self.indicator.configure(text="● PLAY", fg="#008000")
        self.status_var.set(f"Clock → {self.device_var.get()} @ {bpm:g} BPM")
        self._schedule_poll()

    def _start_mpc(self) -> None:
        device = self._selected_device()
        if device is None:
            messagebox.showerror(
                "MIDI Sync",
                "Выберите MIDI-вход. Если список пуст, проверьте USB-подключение "
                "и режим MIDI Port = USB на MPC Sample.",
                parent=self,
            )
            return

        input_device = MidiInput()
        monitor = ClockMonitor()
        try:
            input_device.open(device, monitor.feed)
            input_device.start()
        except Exception as exc:
            input_device.close()
            messagebox.showerror("MIDI Sync", str(exc), parent=self)
            return

        self.input = input_device
        self.monitor = monitor
        self._enter_running()
        self.indicator.configure(text="● WAIT", fg="#b36b00")
        self.status_var.set("Ожидание Start/Clock от MPC Sample…")
        self._schedule_poll()

    def _enter_running(self) -> None:
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.device_combo.configure(state="disabled")
        self.pc_radio.configure(state="disabled")
        self.mpc_radio.configure(state="disabled")
        self.pulse_var.set("Импульсов: 0")

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
        if self.input is not None:
            self.input.stop()
            self.input.close()
            self.input = None
        if self.monitor is not None:
            self.monitor.reset()
            self.monitor = None

        self.start_button.configure(state="normal")
        self.start_button.configure(
            text="▶ Start" if self.mode_var.get() == "pc" else "▶ Слушать"
        )
        self.stop_button.configure(state="disabled")
        self.device_combo.configure(state="readonly")
        self.pc_radio.configure(state="normal")
        self.mpc_radio.configure(state="normal")
        self.indicator.configure(text="● STOP", fg="#a00000")
        self.incoming_var.set("BPM: —")
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
        if engine is not None:
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
            return

        monitor = self.monitor
        if monitor is None:
            return
        bpm = monitor.bpm
        self.pulse_var.set(f"Импульсов: {monitor.pulses}")
        self.incoming_var.set(
            "BPM: —" if bpm is None else f"BPM: {bpm:.1f}"
        )
        if monitor.running:
            self.indicator.configure(text="● PLAY", fg="#008000")
            if bpm is not None:
                self.status_var.set(f"MPC → PC: {bpm:.1f} BPM")
            else:
                self.status_var.set("MPC → PC: PLAY")
        else:
            self.indicator.configure(text="● WAIT", fg="#b36b00")
            self.status_var.set("Ожидание Start/Clock от MPC Sample…")
        self._schedule_poll()

    def _on_close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        self._stop()
        super().destroy()


def sync_window(master: tk.Misc, *, bpm: str = "120") -> SyncWindow:
    """Создать окно sync."""
    return SyncWindow(master, bpm=bpm)
