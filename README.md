# Nvidia Clip That - Voice Activated Clipper

Voice-activated application that listens for "Nvidia clip that" and triggers Alt+F10 to capture gameplay clips.

## Features
- 🎙️ Voice activation using VOSK ASR
- 🎯 Handles common mishearings (nvideo, invidia, etc.)
- ⚡ Low latency response
- 🎮 Works with Nvidia Nvidia Overlay/Instant Replay
- 📥 Automatic model download on first run

## Setup

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Nvidia Overlay/instant replay:**
   - Ensure Alt+F10 is set as your clip hotkey in GeForce Experience

3. **Run the app:**
   - The VOSK model will be downloaded automatically on first run (39 MB)

## Usage

### Run from Python:
```bash
python nvidia_clip_that.py
```

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

## Troubleshooting
- **Model download fails:** The app will automatically download the model on first run. If it fails, check your internet connection
- **No audio input:** Check your microphone permissions
- **Clips not saving:** Verify Alt+F10 is configured in GeForce Experience
- **Clips not saving:** Verify Alt+F10 is configured in GeForce Experience
