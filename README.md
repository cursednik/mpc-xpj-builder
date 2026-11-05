# mpc_xpj_builder (prototype)

Консольный прототип сборки минимального drum-проекта для **Akai MPC Sample** из
папки WAV и одного Standard MIDI File.

## Важное ограничение

Формат `.xpj` закрытый. Без эталонного проекта нельзя гарантировать, что
синтезированный JSON откроется на конкретной прошивке. Поэтому инструмент:

- **читает** эталонный `.xpj` через `--inspect`;
- **клонирует** эталонный `.xpj` при экспорте (`--template`) и меняет только
  документированные поля: имя, BPM, samples, pad-назначения, sequence и notes;
- **не придумывает** неизвестные поля;
- **блокирует** реальный экспорт без `--template` с сообщением
  «Требуется эталонный .xpj от MPC Sample для заполнения схемы»;
- позволяет посмотреть план и ограничения через `--dry-run` даже без эталона.

Итоговая папка ресурсов: `<ProjectName>_[ProjectData]` — именно такой вариант
используют известные реализации для MPC Sample / MPC 3.x.

## Зависимости

Только стандартная библиотека Python 3.11+. Внешние пакеты не нужны.

## Как получить эталон

На MPC Sample создайте минимальный drum-проект (один drum-трек, одна sequence),
сохраните его и скопируйте полученный `.xpj` на компьютер. Этот файл должен быть
создан **той же прошивкой**, на которой потом будет открываться результат.

## Команды

Проверка эталона (исходный файл не изменяется):

```powershell
python main.py --inspect reference.xpj
```

После этого рядом появится `reference_pretty.json`.

План без создания файлов (можно запускать до получения эталона):

```powershell
python main.py `
  --samples "C:\Samples\Kit" `
  --midi "C:\MIDI\drums.mid" `
  --name "My Kit" `
  --bpm 120 `
  --output "C:\MPC Projects" `
  --dry-run --verbose
```

Реальный экспорт:

```powershell
python main.py `
  --samples "C:\Samples\Kit" `
  --midi "C:\MIDI\drums.mid" `
  --name "My Kit" `
  --bpm 120 `
  --output "C:\MPC Projects" `
  --template "C:\MPC Projects\reference.xpj" `
  --verbose
```

Экспорт с явной картой семплов:

```powershell
python main.py `
  --samples "C:\Samples\Kit" `
  --midi "C:\MIDI\drums.mid" `
  --name "My Kit" `
  --bpm 174 `
  --output "C:\MPC Projects" `
  --template "C:\MPC Projects\reference.xpj" `
  --map "C:\MPC Projects\my-kit-map.json" `
  --verbose
```

Результат:

```text
My Kit.xpj
My Kit_[ProjectData]\
    Kick_01.wav
    Snare_01.wav
    ...
```

## Карта семплов `--map`

Пример лежит в `examples/map.example.json`. Рекомендуемый формат:

```json
{
  "samples": [
    {
      "file": "kicks/kick.wav",
      "note": 36,
      "gain": 0.9,
      "pan": 0.5,
      "tune": 0.0,
      "loop": false
    },
    {
      "file": "snares/snare.wav",
      "note": 38,
      "gain": 1.0,
      "pan": 0.5
    }
  ]
}
```

Допустим и компактный формат:

```json
{
  "kick":  { "file": "kick.wav", "note": 36 },
  "snare": { "file": "snare.wav", "note": 38 }
}
```

Правила:

- `file` — путь относительно папки `--samples`; `..` и абсолютные пути запрещены;
- `note` — только `35..51`;
- `gain` — `0..1`;
- `pan` — `0..1`;
- `tune` — полутона, `-24..24` (дробные значения раскладываются в coarse/fine);
- `loop` — `bool`;
- один и тот же WAV можно назначить на несколько нот;
- WAV, не упомянутые в карте, игнорируются;
- дубли `note` запрещены.

## Правила назначения

- Поддерживаются только MIDI-ноты **35..51**.
- Максимум **128** WAV-файлов.
- WAV: RIFF/WAVE, PCM или IEEE float, mono/stereo, 8/16/24/32-bit PCM или
  32-bit float, 8–192 kHz.
- WAV-имена приводятся к ASCII `[A-Za-z0-9_]`, без пробелов; при конфликте
  добавляется `_01`, `_02`, ...
- Без `--map` семплы сортируются по относительному пути; уникальные ноты — по
  возрастанию. Первые N семплов назначаются N уникальным нотам, остальные —
  свободным падам.
- С `--map` используются только файлы из карты; лишние WAV игнорируются.
- Карта `MIDI note -> pad` берётся из `padNoteMap` эталонного проекта. Для
  dry-run без эталона используется наблюдаемая карта MPC Sample:
  `36..51 -> pad 1..16`, `35 -> pad 128`.
- Один MIDI-клип превращается в одну MPC sequence; `trackClipMaps` содержит одну
  строку с клипами всех сохранённых треков. Инфраструктурные треки
  (submix/output) из эталона сохраняются.

## Batch-режим `--batch`

Один JSON-манифест — несколько проектов. Пример: `examples/batch.example.json`.

```json
{
  "template": "D:\\MPC-Sample\\Projects\\reference.xpj",
  "output": "D:\\MPC-Sample\\Projects",
  "bpm": 174,
  "jobs": [
    {
      "name": "Kit A",
      "samples": "C:\\Samples\\Kit A",
      "midi": "C:\\MIDI\\kit-a.mid",
      "map": "C:\\Samples\\Kit A\\map.json"
    },
    {
      "name": "Kit B",
      "samples": "C:\\Samples\\Kit B",
      "midi": "C:\\MIDI\\kit-b.mid",
      "bpm": 160
    }
  ]
}
```

Запуск:

```powershell
python main.py --batch "C:\MPC Projects\batch.json" --dry-run
python main.py --batch "C:\MPC Projects\batch.json" --verbose
```

Правила:

- относительные пути в манифесте считаются от папки манифеста;
- `template`, `output`, `bpm` можно задать глобально и переопределить в job;
- `map` задаётся на уровне job;
- все job сначала проходят preflight;
- при ошибке preflight **ни один** проект не записывается;
- при ошибке записи уже созданные проекты не откатываются;
- дубли имён/целей запрещены.

## Коды возврата

| Код | Значение |
| ---: | --- |
| 0 | успех / dry-run |
| 2 | ошибка аргументов CLI |
| 3 | ошибка валидации входных данных |
| 4 | схема требует эталонный `.xpj` |
| 5 | ошибка файловой системы / записи |
| 1 | непредвиденная ошибка |

## Известные неизвестные

Список ведётся в `xpj_schema.py` (`unresolved_fields()`):

- версия и platform в заголовке;
- top-level UI/controller/mixer-поля (`data.*`);
- `programPads`, `base.*`, custom Q-Link и macro-scene поля;
- полная структура `drum.instruments[]` (synthSection, articulations,
  chopProperties, padEffects, modLinks, noteCounters, random seeds);
- `padNoteMap` и семантика pad index на конкретной прошивке;
- `loadImpl` и metadata семплов;
- служебные поля sequence/clip/event;
- `data.mixer`;
- версии схемы и точное имя ProjectData-папки.

Всё перечисленное сохраняется из `--template`, а не синтезируется.

## Калибровка по эталону 1.3.0.12

Проверено на реальном пустом проекте MPC Sample:

- `trackClipMaps` — ровно **одна строка**, внутри неё по одному клипу на каждый
  трек (`Drum`, `Out 1/2`, `Out 3/4`, `Submix 1`);
- у слоя `sampleEnd = 0`, а длина задаётся `sliceInfo.End = frames - 1`;
- `sliceIndex = 129`;
- `sampleName` и `sampleFile` — без расширения в имени семпла;
- `loadImpl` встречается как `0`, так и `1`;
- порядок клипов в строке сохраняется из эталона.

## Тесты

```powershell
python -m unittest discover -s tests -v
```

Покрыты: карта `--map`, конфликты/ошибки карты, batch-манифест и preflight,
running status и note-on velocity 0 в MIDI, tempo/time signature, dry-run,
экспорт с mapped-семплами, `sampleEnd`, `sliceInfo.End`, gain/pan/tune/loop и
игнорирование лишних WAV. Всего 24 теста.

## Статус проверки

Код компилируется и проверен на синтетических WAV/MIDI, реальном эталонном
`.xpj` и реальных семплах (чтение, dry-run, экспорт, повторный `--inspect`).
Проверка загрузки на физическом MPC Sample в этом окружении выполнялась только
косвенно: проект собран из эталонного `.xpj` той же прошивки.

## Источники наблюдений

- `kurtjcu/MPC-project-file-definitions` — публичная база полей MPC 3.x `.xpj`.
- `tarikcampos/MPC-Sample-Toolkit` и `WorldLinkStudio/mpcsample` — открытые
  реализации, подтверждавшие загрузку проектов на MPC Sample.
- Локальный эталонный `.xpj` целевой прошивки — единственный источник истины
  для полей, помеченных как неизвестные.

