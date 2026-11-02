# Графы ComfyUI

Конвейер не собирает схемы ComfyUI на лету. Три схемы лежат готовыми в `workflows/`,
их пишет скрипт:

```
make graphs        # то же, что python3 scripts/make_graphs.py
```

Схемы повторяют встроенные шаблоны ComfyUI, в формате API:

| Файл | Что делает |
| --- | --- |
| `keyframe.json` | Z-Image Turbo, кадр по тексту |
| `keyframe-edit.json` | Qwen-Image-Edit 2509, кадр по тексту и портрету героя; модель `qwen-edit`, нужны веса `make models ONLY=character OPTIONAL=1` |
| `animate.json` | Wan 2.2 14B, клип из кадра; две ускоряющие LoRA lightx2v на 4 шага, затем RIFE удваивает частоту до 32 кадров в секунду |
| `animate-hd.json` | то же, но перед RIFE Real-ESRGAN увеличивает кадры в четыре раза, и они ужимаются до 1080 × 1920; модель `wan-2.2-hd`, нужны веса `make models ONLY=upscale OPTIONAL=1` |
| `score.json` | ACE-Step 1.5 AIO, инструментальная музыка в flac |

Размеры, шаги и длина клипа приходят из `.env` при каждом запуске, поэтому для них
перегенерировать схемы не нужно: [settings.md](settings.md). `make graphs` нужен, только
если меняется само устройство схемы: семплер, LoRA, шаг RIFE, новый блок.

## Слоты

Блоки, которые конвейер заполняет сам, помечены заголовком `@слот:вход`. Заголовок
`@prompt:text` значит «положить промпт во вход text этого блока». В одном заголовке может
быть несколько слотов через пробел, и один слот может стоять на нескольких блоках.

| Файл | Заголовок | Блок |
| --- | --- | --- |
| keyframe | `@prompt:text` | текст промпта |
| keyframe | `@width:width @height:height` | пустой латент |
| keyframe | `@seed:seed @steps:steps` | KSampler |
| keyframe-edit | `@prompt:prompt` | TextEncodeQwenImageEditPlus с промптом |
| keyframe-edit | `@image:image` | Load Image с портретом |
| keyframe-edit | `@width:width @height:height`, `@seed:seed @steps:steps` | как у keyframe |
| animate | `@image:image` | Load Image |
| animate | `@prompt:text` | текст промпта |
| animate | `@length:length @width:width @height:height` | WanImageToVideo |
| animate | `@seed:noise_seed @steps:steps @split:end_at_step` | первый KSamplerAdvanced |
| animate | `@seed:noise_seed @steps:steps @split:start_at_step @steps:end_at_step` | второй KSamplerAdvanced |
| animate-hd | те же слоты, что у animate | |
| score | `@tags:tags` | текстовый энкодер ACE-Step |
| score | `@seconds:value` | число, связанное с длиной латента и энкодера |
| score | `@seed:value` | число, связанное с семплером и энкодером |
| score | `@steps:steps` | KSampler |

Обязательны слоты промпта, seed, картинки, длины и тегов. Размеры и шаги необязательны:
схема, собранная руками без них, тоже заработает, просто эти настройки из `.env` к ней не
применятся.

При старте воркер проверяет слоты. Если заголовка не хватает или он указывает на вход,
которого у блока нет, воркер не запустится и назовёт схему и слот.

## Схемы для интерфейса

Рядом с графами конвейера лежат три схемы для редактора, в обычном формате ComfyUI:
`Новый ролик.json`, `Новая серия.json` и `Статус.json`. Они собраны из блоков Reelsmith и
видны в панели «Рабочие процессы» в папке `reelsmith`. Конвейер их не читает.

## Своя схема из редактора

1. Соберите или откройте схему в ComfyUI и добейтесь хорошего результата руками.
2. Переименуйте блоки, которые должен заполнять конвейер (правый клик → Title), по
   таблице выше.
3. Меню Рабочий процесс → Экспорт (API), сохраните в `workflows/` под нужным именем.
4. `make up`.

## Черновая модель

`animate-draft.json` это Wan 2.2 TI2V 5B на 24 кадра в секунду, с теми же слотами, что
`animate.json`. Он пока не генерируется. Веса: `make models ONLY=draft OPTIONAL=1`. Схема
собирается в редакторе из шаблона «Wan 2.2 5B» по шагам выше. Когда файл есть, в рецепте
можно указать модель `wan-5b`: она быстрее и дешевле, удобна для черновиков и
A/B-сравнений.
