# LTX2.3 Video Dataset Editor

A desktop application for preparing video datasets:
- manual and automatic clip cutting,
- visual crop with constraints,
- video export + caption `.txt`,
- caption generation with `WD14` or `BLIP2`.

## Key Features

- Clip cutting with durations `5 / 10 / 15` seconds.
- `Auto clip` button for automatic slicing by selected duration.
- Clip length normalization to the `8n+1` frame rule.
- Output size constraints:
  - width and height must be multiples of `32`.
- Visual crop overlay on top of preview.
- Pre-crop resize (for easier crop selection on large videos).
- Export all clips into one selected output folder.
- Save caption for each clip as `.txt` with the same base name:
  - in the same folder as video,
  - or in `captions` subfolder.
- Two tagger modes:
  - `WD14 Tags`,
  - `BLIP2 Caption`.
- Drag-and-drop video into preview area.
- Flexible UI panels in `View`:
  - `Preview`, `Timeline`, `Crop`, `Caption`, `Logs`.
- Persistent user layout:
  - main window position/size,
  - `maximized` state,
  - panel visibility and arrangement.

## Requirements

- Python 3.10+
- FFmpeg:
  - `ffmpeg.exe`
  - `ffprobe.exe`

You can also use local binaries from the project `bin/` folder.
Download FFmpeg binaries: [https://ffbinaries.com/downloads](https://ffbinaries.com/downloads)

## Installation

```bash
python -m pip install -r requirements.txt
```

## Quick Start (Windows)

Use:

```bat
run_app.bat
```

The script:
- checks Python,
- installs/updates dependencies from `requirements.txt`,
- prepends local `bin` to `PATH` (if available),
- starts the application.

## Run from Console

```bash
python -m app.main
```

## Export

- `File -> Export` opens a separate export dialog.
- The export dialog closes automatically after successful export.
- Progress and messages are written to the `Logs` panel.

## Caption / Tagger

In the `Caption` panel:
- manual keywords,
- prefix for final caption line,
- generation for selected clip or all clips.

In `Settings`:
- `Redownload tagger models` re-downloads `WD14` and `BLIP2` models.

A waiting message is shown while models are being downloaded/initialized.

## Project Format

Projects are saved/loaded as `project.json` and include:
- source video,
- clip list,
- crop/resize parameters,
- caption/tagger settings,
- selected export settings.

## Tests

```bash
python -m pytest -q
```

