# Nvidia Clip That - Voice Activated Clipper

Voice-activated application that listens for "Nvidia clip that" and triggers Alt+F10 to capture gameplay clips. It also supports "start recording" and "stop recording" voice commands mapped to Alt+F9 and plays configurable sound effects for each action.

## Setup

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Nvidia Overlay:**
   - Ensure Alt+F10 is set as your clip hotkey on the Nvidia Overlay and Instant Replay is enabled.

3. **Run the app:**
   - The VOSK model will be downloaded automatically on first run (~39 MB)

## Usage

### Run from Python:
```bash
python nvidia_clip_that.py
```
## Usage (.exe)

### Run the EXE:
Download the latest release from the Releases
https://github.com/SaphiraTeam/Nvidia-Clip-That/releases

### Build to EXE:
```bash
python build.py
```
The executable will be in the `dist` folder.

## Voice Commands
Say any of these to trigger a clip:
- "Nvidia clip that"
- "Nvidia clip it"
- Common mishearings are also supported

Recording control:
- "Nvidia start recording" → Alt+F9 (only if not already recording)
- "Nvidia stop recording" → Alt+F9 (only if currently recording)

## Troubleshooting
- **Model download fails:** The app will automatically download the model on first run. If it fails, check your internet connection
- **No audio input:** Check your microphone permissions
- **Clips not saving:** Verify Alt+F10 is configured on the Nvidia Overlay
- **Clips not saving:** Verify Alt+F10 is configured on the Nvidia Overlay

## Configuration

The app creates a `config.yml` next to the executable or script on first run. Options:

- `trigger_phrases`: list of phrases considered a match for clipping
- `threshold`: similarity threshold for final results
- `partial_threshold`: stricter similarity for partial results
- `hotkey`: hotkey for clipping (default `alt+f10`)
- `debounce_seconds`: minimum seconds between identical actions (default `2.0`)

Example:

```yml
trigger_phrases:
   - nvidia clip that
   - nvideo clip that
threshold: 0.85
partial_threshold: 0.9
hotkey: alt+f10
debounce_seconds: 2.0
```

## Sound Effects (SFX)

On first run, the app extracts an `sfx` folder alongside the exe/script containing:

- `Clip-Saved.wav`
- `Recording-Started.wav`
- `Recording-Stopped.wav`
- `Failed.wav`

You can replace these files with your own WAV/MP3 files; keep the filenames the same. The app will play them asynchronously when actions trigger.
