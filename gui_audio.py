"""Окно USB Audio: запись и мониторинг MPC Sample."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import audio_io


class AudioWindow(tk.Toplevel):
    """Запись/мониторинг USB-аудио MPC Sample."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.title("MPC XPJ Builder — USB Audio")
        self.geometry("820x620")
        self.minsize(720, 540)
        self.transient(master.winfo_toplevel())

        self.devices: tuple[audio_io.AudioDevice, ...] = ()
        self.input_map: dict[str, int] = {}
        self.output_map: dict[str, int | None] = {}
        self.session: audio_io.AudioSession | None = None
        self._after_id: str | None = None

        self.input_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value="Не мониторить")
        self.rate_var = tk.StringVar(value="44100")
        self.status_var = tk.StringVar(value="")
        self.level_var = tk.DoubleVar(value=0.0)
        self.time_var = tk.StringVar(value="0.0 s")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_devices()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        info = ttk.LabelFrame(outer, text="USB Audio", padding=8)
        info.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            info,
            text="MPC Sample → PC: запись WAV и мониторинг.",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            info,
            text=(
                "Выберите вход «Микрофон (MPC Sample Audio)». "
                "Для мониторинга выберите выход своих наушников/колонок, "
                "не выход MPC Sample — иначе получится петля. "
                "Если появляется Invalid sample rate — выберите другую частоту."
            ),
            wraplength=760,
            foreground="#444444",
        ).pack(anchor="w", pady=(4, 0))

        form = ttk.LabelFrame(outer, text="Параметры", padding=8)
        form.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Вход").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self.input_combo = ttk.Combobox(
            form, textvariable=self.input_var, state="readonly"
        )
        self.input_combo.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(form, text="Обновить", command=self.refresh_devices).grid(
            row=0, column=2, padx=(8, 0), pady=3
        )

        ttk.Label(form, text="Мониторить в").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self.output_combo = ttk.Combobox(
            form, textvariable=self.output_var, state="readonly"
        )
        self.output_combo.grid(row=1, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="Sample rate").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self.rate_combo = ttk.Combobox(
            form,
            textvariable=self.rate_var,
            values=("44100", "48000"),
            state="readonly",
            width=10,
        )
        self.rate_combo.grid(row=2, column=1, sticky="w", pady=3)

        state = ttk.LabelFrame(outer, text="Уровень", padding=8)
        state.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        state.columnconfigure(0, weight=1)
        self.level = ttk.Progressbar(
            state,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.level_var,
        )
        self.level.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        ttk.Label(state, textvariable=self.time_var).grid(
            row=1, column=0, sticky="w"
        )
        ttk.Label(state, textvariable=self.status_var).grid(
            row=1, column=1, sticky="e"
        )

        bottom = ttk.Frame(outer)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.record_button = ttk.Button(
            bottom, text="● Запись WAV…", command=self._record
        )
        self.record_button.pack(side="left")
        self.monitor_button = ttk.Button(
            bottom, text="▶ Монитор", command=self._monitor
        )
        self.monitor_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            bottom, text="■ Стоп", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left")
        ttk.Button(bottom, text="Закрыть", command=self._on_close).pack(
            side="right"
        )

    def refresh_devices(self) -> None:
        if self.session is not None and self.session.running:
            return
        try:
            self.devices = audio_io.list_devices()
        except Exception as exc:
            self.devices = ()
            self.input_map = {}
            self.output_map = {}
            self.input_combo.configure(values=())
            self.output_combo.configure(values=("Не мониторить",))
            self.input_var.set("")
            self.output_var.set("Не мониторить")
            self.status_var.set(str(exc))
            return

        inputs = [device for device in self.devices if device.is_input]
        outputs = [device for device in self.devices if device.is_output]
        self.input_map = {device.label: device.index for device in inputs}
        self.output_map = {
            device.label: device.index for device in outputs
        }
        self.input_combo.configure(values=list(self.input_map))
        self.output_combo.configure(
            values=["Не мониторить", *self.output_map.keys()]
        )

        default_input = audio_io.pick_mpc_input(self.devices)
        if default_input is not None:
            self.input_var.set(default_input.label)
        elif self.input_map:
            self.input_var.set(next(iter(self.input_map)))
        else:
            self.input_var.set("")

        self.output_var.set("Не мониторить")
        if default_input is not None:
            self.rate_var.set(
                "44100"
                if abs(default_input.default_samplerate - 44100) < 1
                else f"{int(default_input.default_samplerate)}"
            )
        self.status_var.set(
            f"Найдено входов: {len(inputs)}, выходов: {len(outputs)}."
        )

    def _selected_input(self) -> audio_io.AudioDevice | None:
        label = self.input_var.get().strip()
        index = self.input_map.get(label)
        if index is None:
            return None
        return next(
            (device for device in self.devices if device.index == index),
            None,
        )

    def _selected_output(self) -> audio_io.AudioDevice | None:
        label = self.output_var.get().strip()
        if label == "Не мониторить":
            return None
        index = self.output_map.get(label)
        if index is None:
            return None
        return next(
            (device for device in self.devices if device.index == index),
            None,
        )

    def _record(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить запись MPC Sample",
            defaultextension=".wav",
            initialfile="mpc-sample.wav",
            filetypes=[("WAV", "*.wav"), ("All files", "*.*")],
        )
        if not path:
            return
        self._start(record_path=Path(path))

    def _monitor(self) -> None:
        if self._selected_output() is None:
            messagebox.showinfo(
                "USB Audio",
                "Для мониторинга выберите выход наушников или колонок. "
                "«Не мониторить» записывает/показывает уровень без вывода звука.",
                parent=self,
            )
        self._start(record_path=None)

    def _start(self, *, record_path: Path | None) -> None:
        if self.session is not None and self.session.running:
            return
        input_device = self._selected_input()
        if input_device is None:
            messagebox.showerror(
                "USB Audio",
                "Выберите вход MPC Sample. Если списка нет, установите "
                "sounddevice и проверьте USB-подключение.",
                parent=self,
            )
            return
        try:
            sample_rate = int(self.rate_var.get())
        except ValueError:
            messagebox.showerror("USB Audio", "Некорректный sample rate.", parent=self)
            return
        output_device = self._selected_output()
        channels = 2 if input_device.max_input_channels >= 2 else 1
        if output_device is not None:
            available = output_device.max_output_channels
            if available < 1:
                messagebox.showerror(
                    "USB Audio", "У выбранного выхода нет каналов.", parent=self
                )
                return
            channels = min(channels, available)

        session = audio_io.AudioSession()
        session.start(
            input_device=input_device.index,
            output_device=output_device.index if output_device else None,
            sample_rate=sample_rate,
            channels=channels,
            wav_path=record_path,
        )
        self.session = session
        self.record_button.configure(state="disabled")
        self.monitor_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.input_combo.configure(state="disabled")
        self.output_combo.configure(state="disabled")
        self.rate_combo.configure(state="disabled")
        mode = (
            f"Запись: {record_path.name}"
            if record_path is not None
            else "Мониторинг"
        )
        self.status_var.set(f"{mode} · {sample_rate} Hz · {channels} ch")
        self._schedule_poll()

    def _stop(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        recorded = None
        if self.session is not None:
            recorded = self.session.recorded_path
            self.session.stop()
            self.session = None
        self.record_button.configure(state="normal")
        self.monitor_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.input_combo.configure(state="readonly")
        self.output_combo.configure(state="readonly")
        self.rate_combo.configure(state="readonly")
        self.level_var.set(0.0)
        self.time_var.set("0.0 s")
        if recorded is not None:
            self.status_var.set(f"Сохранено: {recorded}")
        else:
            self.status_var.set("Остановлено.")

    def _schedule_poll(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.after(100, self._poll)

    def _poll(self) -> None:
        self._after_id = None
        session = self.session
        if session is None:
            return
        if session.error is not None:
            error = session.error
            self._stop()
            messagebox.showerror("USB Audio", str(error), parent=self)
            return
        if not session.running:
            self._stop()
            return
        self.level_var.set(session.peak)
        self.time_var.set(f"{session.seconds:.1f} s")
        self._schedule_poll()

    def _on_close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        self._stop()
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        super().destroy()
