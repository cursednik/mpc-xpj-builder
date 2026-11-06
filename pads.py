"""Адресация падов MPC: банки A-H, 16 падов в банке."""

from __future__ import annotations

BANK_NAMES = "ABCDEFGH"
PADS_PER_BANK = 16
TOTAL_PADS = 128


def global_pad_index(bank: str, pad_number: int) -> int:
    """A1 -> 0, H16 -> 127."""
    bank = bank.strip().upper()
    if len(bank) != 1 or bank not in BANK_NAMES:
        raise ValueError(f"Неизвестный банк: {bank!r}.")
    if not 1 <= pad_number <= PADS_PER_BANK:
        raise ValueError("Pad должен быть в диапазоне 1..16.")
    return BANK_NAMES.index(bank) * PADS_PER_BANK + pad_number - 1


def bank_pad_label(pad_index: int) -> str:
    if not 0 <= pad_index < TOTAL_PADS:
        raise ValueError(f"Некорректный pad index: {pad_index}.")
    return f"{BANK_NAMES[pad_index // PADS_PER_BANK]}{pad_index % PADS_PER_BANK + 1}"


def parse_pad(value: str) -> int:
    """'A1'..'H16' -> 0..127."""
    text = value.strip().upper()
    if len(text) < 2:
        raise ValueError(f"Некорректный pad: {value!r}.")
    return global_pad_index(text[0], int(text[1:]))


def default_note_to_pad_full() -> dict[int, int]:
    """Наблюдённая карта MPC Sample для всех 128 падов."""
    note_to_pad: dict[int, int] = {}
    for pad in range(16):
        note_to_pad[36 + pad] = pad
    for pad in range(16, 92):
        note_to_pad[52 + (pad - 16)] = pad
    for pad in range(92, 127):
        note_to_pad[pad - 92] = pad
    note_to_pad[35] = 127
    return note_to_pad


def default_pad_to_note_full() -> dict[int, int]:
    return {pad: note for note, pad in default_note_to_pad_full().items()}
