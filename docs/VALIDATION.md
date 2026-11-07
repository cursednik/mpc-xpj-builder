# Hardware validation

## 2026-11-06 — PSX DnB Kit

Устройство: MPC Sample.

Проверено:

- проект `PSX DnB Kit.xpj` открывается на устройстве;
- все **32** one-shot семпла присутствуют и загружаются;
- проект использует пады `A1–B16`;
- карта назначена через pad-based `--map`;
- MIDI-ноты 36–67 записаны с `--extended-notes`;
- `[ProjectData]` содержит 32 WAV.

Результат: успех.

## 2026-11-06 — дополнительные проверки

- `XPJ Test Long` — успех, длинный one-shot звучит целиком.
- `XPJ Test 128` — успех: A1 = `sample_001`, H16 = `00_note_35`.
- `XPJ Test Loop` — loop в проекте включён, но MPC не играет его как loop
  сразу после загрузки. Если выключить и снова включить loop в UI — работает.
  Проект был пересохранён MPC с рабочим loop; сравнение показало:
  - loop-поля слоя (`loop`, `loopMode`, `loopStart`, `loopEnd`,
    `layerLoopModeOverridesSliceLoopMode`, `sliceInfo.LoopMode`) **идентичны**;
  - WAV-файл **побайтово идентичен**;
  - изменились только UI/маршрутизация/quantiser-поля, не связанные с loop.

  Дополнительные варианты с `triggerMode = 2/3` и разным `layer.loop` были
  проверены на устройстве: все три играют loop сразу после загрузки.
  Следовательно, ключ — не `layer.loop`, а `triggerMode`. Выбран вариант,
  совпадающий с пересохранённым MPC проектом:
  - `instrument.triggerMode = 3`;
  - `layer.loop = false`;
  - `layer.loopMode = 1`;
  - `layer.layerLoopModeOverridesSliceLoopMode = true`;
  - `sliceInfo.LoopMode = 1`;
  - `sliceInfo.LoopCrossfadeLength = -1`.
  Исправление внесено в `xpj_schema.py`.

## 2026-11-06 — финальная проверка loop

Проект `XPJ Loop Final` (сгенерирован уже исправленным кодом) проверен на
MPC Sample: loop играет сразу после загрузки, ручное переключение не нужно.

Статус loop-фикса: подтверждён.

## Осталось проверить

- sequence с нотами банка B (52–67) — фактическое звучание всех 32 падов;
- несколько sequence в одном проекте (v1.1.0) — отображение и воспроизведение
  на устройстве;
- конфликты имён и длинные имена.
