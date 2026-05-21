# Subtitle Merger

A GUI tool for batch merging dual-language subtitles (English + Portuguese) into styled `.ass` files, with MKV subtitle extraction, template management, and Plex-compatible output.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

## Features

- **Three input modes**: Folder mode, individual file mode, and ASS merge mode
- **Drag-and-drop** support for folders, files, and MKV videos
- **MKV subtitle extraction** – auto-detects English and Portuguese tracks via `ffprobe`/`ffmpeg`
- **ASS merge pipeline** – combines styles, applies layer separation, dynamic margin calculation
- **Sign/title handling** – preserves `\pos()` tags with options to shift or strip positioning
- **Template management** – save and load named `.ass` style templates
- **Plex-compatible output** – `{name}.pt.ass` filenames with `Language: pt` and custom track title
- **Skip forced tracks** – filters out forced/signs-only subtitle tracks during MKV import
- **Auto-cleanup** – deletes intermediate files after conversion

## Requirements

### For the Python script
- Python 3.10+
- `tkinterdnd2` – `pip install tkinterdnd2`
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

### Modes

| Mode | Use case |
|------|----------|
| **Folder** | Point to two folders (English + Portuguese SRTs), auto-match by filename |
| **File** | Drag individual SRT files for one-off merges |
| **ASS Merge** | Merge two pre-existing `.ass` files (e.g. extracted from MKV) with full style preservation |

### MKV Workflow
1. Drag an `.mkv` file onto the MKV drop zone
2. English and Portuguese tracks are auto-detected
3. Subtitles are extracted as `.ass` and loaded into ASS Merge mode
4. Click **Convert All** to produce the final merged file

## Building the Executable

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name SubtitleMerger \
  --add-data "path/to/tkinterdnd2;tkinterdnd2" \
  batch_2srt2ass.py
```

## License

MIT
