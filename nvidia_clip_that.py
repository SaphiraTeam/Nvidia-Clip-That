import sys
import os
import json
import queue
import threading
import urllib.request
import zipfile
import shutil
import traceback
from difflib import SequenceMatcher

import sounddevice as sd
import vosk
import pyautogui
import yaml
import pystray
from PIL import Image, ImageDraw

# Download model from https://alphacephei.com/vosk/models
# Recommended: vosk-model-small-en-us-0.15
MODEL_PATH = "vosk-model-small-en-us-0.15"

DEFAULT_CONFIG = {
    'trigger_phrases': [
        'nvidia clip that',
        'nvideo clip that',
        'nvidia clip it',
        'nvideo clip it',
        'nvidia clip dat',
        'nvidia klip that',
        'invidia clip that'
    ],
    'threshold': 0.85,
    'partial_threshold': 0.90,
    'hotkey': 'alt+f10',
}


def resource_path(rel_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller bundle.
    If bundled with --onefile, assets are unpacked to sys._MEIPASS.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath('.')
    return os.path.join(base_path, rel_path)


def app_dir() -> str:
    """Directory for persistent app data (next to exe/script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(app_dir(), 'config.yml')


class NvidiaClipper:
    def __init__(self):
        self.q = queue.Queue()
        self.model = None
        self.device = None
        self.samplerate = None
        self.stop_event = threading.Event()
        self.listener_thread = None
        self.icon = None  # pystray.Icon

        # Configurable items
        self.trigger_phrases = list(DEFAULT_CONFIG['trigger_phrases'])
        self.threshold = float(DEFAULT_CONFIG['threshold'])
        self.partial_threshold = float(DEFAULT_CONFIG['partial_threshold'])
        self.hotkey = str(DEFAULT_CONFIG['hotkey'])
        self.hotkey_keys = [k.strip() for k in self.hotkey.split('+') if k.strip()]

        # Ensure config exists and load
        self.ensure_config()
        self.load_config()

    def similarity_check(self, text: str, threshold: float | None = None) -> bool:
        """Check if the spoken text matches any trigger phrase."""
        text = text.lower().strip()
        if not text:
            return False
        if threshold is None:
            threshold = self.threshold

        for phrase in self.trigger_phrases:
            ratio = SequenceMatcher(None, text, phrase).ratio()
            if ratio >= threshold:
                return True

        # Also check if text contains the key words in order
        words = text.split()
        if len(words) >= 3:
            # Check for "nvidia/nvideo" and "clip" and "that/it/dat"
            has_nvidia = any(w in ['nvidia', 'nvideo', 'invidia'] for w in words)
            has_clip = 'clip' in words or 'klip' in words
            has_that = any(w in ['that', 'it', 'dat'] for w in words)
            if has_nvidia and has_clip and has_that:
                return True
        return False

    def trigger_clip(self):
        """Trigger the configured hotkey to capture a clip."""
        try:
            pyautogui.hotkey(*self.hotkey_keys)
        except Exception:
            pass

    def audio_callback(self, indata, frames, time_info, status):
        """This is called from a separate thread for each audio block."""
        if status:
            # Log audio status warnings/errors
            try:
                with open(os.path.join(app_dir(), 'error.log'), 'a', encoding='utf-8') as f:
                    f.write(f"sounddevice status: {status}\n")
            except Exception:
                pass
        self.q.put(bytes(indata))

    def download_model(self) -> bool:
        """Download and extract VOSK model automatically into app_dir."""
        model_url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        zip_path = os.path.join(app_dir(), "vosk-model.zip")

        try:
            # Download with progress to console if visible
            def download_progress(block_num, block_size, total_size):
                downloaded = block_num * block_size
                percent = 0 if total_size == 0 else min(downloaded * 100 / total_size, 100)
                bar_length = 40
                filled = int(bar_length * percent / 100)
                bar = '█' * filled + '░' * (bar_length - filled)
                msg = f"\rDownloading VOSK model [{bar}] {percent:.1f}%"
                try:
                    sys.stdout.write(msg)
                    sys.stdout.flush()
                except Exception:
                    pass

            urllib.request.urlretrieve(model_url, zip_path, reporthook=download_progress)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(app_dir())

            # Clean up zip file
            os.remove(zip_path)
            return True
        except Exception:
            try:
                with open(os.path.join(app_dir(), 'error.log'), 'a', encoding='utf-8') as f:
                    f.write("Model download failed:\n" + traceback.format_exc() + "\n")
            except Exception:
                pass
            return False

    def initialize_model(self) -> bool:
        """Initialize VOSK model."""
        # Resolve model path appropriately for bundled/non-bundled
        bundled_model_path = resource_path(MODEL_PATH)
        model_path = bundled_model_path if os.path.exists(bundled_model_path) else os.path.join(app_dir(), MODEL_PATH)

        if not os.path.exists(model_path):
            # Attempt to download into app_dir
            if not self.download_model():
                return False
            # After download in app dir, use local folder
            model_path = os.path.join(app_dir(), MODEL_PATH)

        self.model = vosk.Model(model_path)
        return True

    def initialize_audio(self) -> bool:
        """Initialize audio device."""
        try:
            device_info = sd.query_devices(self.device, 'input')
            self.samplerate = int(device_info['default_samplerate'])
            return True
        except Exception:
            try:
                with open(os.path.join(app_dir(), 'error.log'), 'a', encoding='utf-8') as f:
                    f.write("Audio init failed:\n" + traceback.format_exc() + "\n")
            except Exception:
                pass
            return False

    def listening_loop(self):
        """Main recognition loop running in a background thread."""
        try:
            with sd.RawInputStream(samplerate=self.samplerate, blocksize=8000,
                                   device=self.device, dtype='int16',
                                   channels=1, callback=self.audio_callback):
                rec = vosk.KaldiRecognizer(self.model, self.samplerate)
                while not self.stop_event.is_set():
                    try:
                        data = self.q.get(timeout=0.1)
                        if rec.AcceptWaveform(data):
                            result = json.loads(rec.Result())
                            text = result.get('text', '')
                            if text and self.similarity_check(text):
                                threading.Thread(target=self.trigger_clip, daemon=True).start()
                        else:
                            partial = json.loads(rec.PartialResult())
                            partial_text = partial.get('partial', '')
                            if partial_text and self.similarity_check(partial_text, threshold=self.partial_threshold):
                                threading.Thread(target=self.trigger_clip, daemon=True).start()
                    except queue.Empty:
                        pass
        except Exception:
            # Log to file in app dir
            try:
                with open(os.path.join(app_dir(), 'error.log'), 'a', encoding='utf-8') as f:
                    f.write("Listening loop crashed:\n" + traceback.format_exc() + "\n")
            except Exception:
                pass

    def start_listening(self) -> bool:
        if not self.initialize_model():
            return False
        if not self.initialize_audio():
            return False
        self.stop_event.clear()
        self.listener_thread = threading.Thread(target=self.listening_loop, daemon=True)
        self.listener_thread.start()
        return True

    def stop_listening(self):
        self.stop_event.set()
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=2.0)
        self.listener_thread = None

    # Config helpers
    def ensure_config(self):
        path = config_path()
        if not os.path.exists(path):
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(DEFAULT_CONFIG, f, sort_keys=False)
            except PermissionError:
                # Fallback to user home if no permission
                home_path = os.path.join(os.path.expanduser('~'), 'Nvidia-Clip-That-config.yml')
                with open(home_path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(DEFAULT_CONFIG, f, sort_keys=False)
            except Exception:
                pass

    def load_config(self):
        path = config_path()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            self.trigger_phrases = list(cfg.get('trigger_phrases', DEFAULT_CONFIG['trigger_phrases']))
            self.threshold = float(cfg.get('threshold', DEFAULT_CONFIG['threshold']))
            self.partial_threshold = float(cfg.get('partial_threshold', DEFAULT_CONFIG['partial_threshold']))
            self.hotkey = str(cfg.get('hotkey', DEFAULT_CONFIG['hotkey']))
            self.hotkey_keys = [k.strip() for k in self.hotkey.split('+') if k.strip()]
        except Exception:
            # Keep defaults on error
            pass

    def open_config(self, icon=None, item=None):  # pystray callback signature
        path = config_path()
        try:
            if sys.platform.startswith('win'):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(['xdg-open', path])
        except Exception:
            pass

    def reload_config(self, icon=None, item=None):  # pystray callback signature
        self.load_config()

    def exit_app(self, icon=None, item=None):  # pystray callback signature
        try:
            if self.icon:
                self.icon.visible = False
        except Exception:
            pass
        self.stop_listening()
        if self.icon:
            self.icon.stop()

    # Tray icon
    def create_icon_image(self, size=64, color=(0, 170, 255)):
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Simple circle with a triangle (play) to represent clipping
        r = size // 2 - 4
        center = (size // 2, size // 2)
        draw.ellipse([(center[0]-r, center[1]-r), (center[0]+r, center[1]+r)], outline=color, width=4)
        tri = [(size*0.42, size*0.35), (size*0.42, size*0.65), (size*0.7, size*0.5)]
        draw.polygon(tri, fill=color)
        return img

    def run_tray(self):
        # Start listening in background
        self.start_listening()
        menu = pystray.Menu(
            pystray.MenuItem('Open config', self.open_config),
            pystray.MenuItem('Reload config', self.reload_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Exit', self.exit_app)
        )
        image = self.create_icon_image()
        tooltip = 'NVIDIA Clip That — listening for trigger phrases'
        self.icon = pystray.Icon('NvidiaClipThat', image, tooltip, menu)
        self.icon.run()


def main():
    clipper = NvidiaClipper()
    clipper.run_tray()


if __name__ == '__main__':
    main()
