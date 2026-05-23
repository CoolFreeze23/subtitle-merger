# Subtitle Merger

A GUI tool for batch merging dual-language subtitles into styled `.ass` files, with MKV subtitle extraction, template management, and Plex-compatible output.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

## Features

- **Modern dark UI** powered by Sun Valley theme
- **Three input modes**: Folder mode, individual file mode, and ASS merge mode
- **Drag-and-drop** support for folders, files, and MKV videos
- **MKV subtitle extraction** – auto-detects language tracks via `ffprobe`/`ffmpeg`
- **Configurable language pair** – works with any two languages, not just English/Portuguese
- **ASS merge pipeline** – combines styles, applies layer separation, dynamic margin calculation
- **Sign/title handling** – preserves `\pos()` tags with options to shift or strip positioning
- **Customizable subtitle style** – text color, outline color, and font size reduction via Settings
- **Custom output filename** – configurable pattern with `{basename}` and `{lang}` tokens
- **Custom track title** – set any Plex-visible subtitle description
- **Template management** – save and load named `.ass` style templates
- **Plex-compatible output** – correct `Language:` header and custom title
- **Skip forced tracks** – filters out forced/signs-only subtitle tracks during MKV import
- **Auto-cleanup** – deletes intermediate files after conversion
- **Progress bar** – visual feedback during batch conversion (runs in background thread)
- **Open Output Folder** – one-click jump to results after conversion
- **Remembers state** – last used directories, window position, and settings persist
- **Keyboard shortcuts** – Ctrl+O, Ctrl+M, Ctrl+Enter, Ctrl+Comma, Delete
- **Duplicate style detection** – warns if merged ASS files have conflicting style names

## Requirements

### For the Python script
- Python 3.10+
- `tkinterdnd2` – `pip install tkinterdnd2`
- `sv_ttk` – `pip install sv_ttk` (optional, for dark theme)
- `ffmpeg` and `ffprobe` on PATH (for MKV extraction)

### For the standalone executable
- Just download `SubtitleMerger.exe` from [Releases](https://github.com/CoolFreeze23/subtitle-merger/releases) – no Python needed
- `ffmpeg` and `ffprobe` on PATH (for MKV extraction)

## Usage

```bash
# Run the Python script
python batch_2srt2ass.py

# Or just double-click SubtitleMerger.exe
```

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Browse MKV |
| `Ctrl+M` | Auto-Match |
| `Ctrl+Enter` | Convert All |
| `Ctrl+,` | Open Settings |
| `Delete` | Remove selected pair |

### Settings

Open **Settings** (gear icon or `Ctrl+,`) to configure:
- **Language pair** – top/bottom language name, ISO code, and detection tags
- **Bottom subtitle style** – text color, outline color, font size reduction (with color picker)
- **Output filename pattern** – e.g. `{basename}.{lang}.ass`
- **Track title** – the description shown in Plex

### Modes

| Mode | Use case |
|------|----------|
| **Folder** | Point to two folders (top + bottom language SRTs), auto-match by filename |
| **File** | Drag individual SRT files for one-off merges |
| **ASS Merge** | Merge two pre-existing `.ass` files (e.g. extracted from MKV) with full style preservation |

### MKV Workflow
1. Drag an `.mkv` file onto the MKV drop zone (or Ctrl+O to browse)
2. Language tracks are auto-detected based on your configured tags
3. Subtitles are extracted as `.ass` and loaded into ASS Merge mode
4. Click **Convert All** to produce the final merged file
5. Click **Open Output Folder** to view results

## Building the Executable

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name SubtitleMerger \
  --add-data "path/to/tkinterdnd2;tkinterdnd2" \
  --add-data "path/to/sv_ttk;sv_ttk" \
  batch_2srt2ass.py
```

## License

MIT
