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
import time

import sounddevice as sd
import vosk
import pyautogui
import yaml
import pystray
from PIL import Image, ImageDraw
from playsound3 import playsound



MODEL_PATH = "vosk-model-small-en-us-0.15"
SFX_DIR_NAME = "sfx"
SFX_FILES = {
    'clip': 'Clip-Saved.wav',
    'start': 'Recording-Started.wav',
    'stop': 'Recording-Stopped.wav',
    # Optional failure/feedback sound. Place `Failed.wav` in the `sfx/` folder to use it.
    'failed': 'Failed.wav',
    'already_recording': 'Failed.wav',
    'not_recording': 'Failed.wav',
}  

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
    'start_phrases': [
        'nvidia start recording',
        'nvideo start recording',
        'invidia start recording',
        'nvidia begin recording',
        'nvidia start the recording',
    ],
    'stop_phrases': [
        'nvidia stop recording',
        'nvideo stop recording',
        'invidia stop recording',
        'nvidia end recording',
        'nvidia stop the recording',
    ],
    'threshold': 0.85,
    'partial_threshold': 0.90,
    'hotkey': 'alt+f10',
    'debounce_seconds': 2.0,
    'stop_mode': 'toggle_unsafe',  
    'console_logging': True,
}


def resource_path(rel_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller bundle.
    If bundled with --onefile, assets are unpacked to sys._MEIPASS.
    """
    try:
        
        base_path = sys._MEIPASS  
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
        self.icon = None  
        self.is_recording = False
        self.partial_clip_fired = False
        self.last_action_times = {'clip': 0.0, 'start': 0.0, 'stop': 0.0}

        
        self.trigger_phrases = list(DEFAULT_CONFIG['trigger_phrases'])
        self.threshold = float(DEFAULT_CONFIG['threshold'])
        self.partial_threshold = float(DEFAULT_CONFIG['partial_threshold'])
        self.hotkey = str(DEFAULT_CONFIG['hotkey'])
        self.hotkey_keys = [k.strip() for k in self.hotkey.split('+') if k.strip()]
        self.debounce_seconds = float(DEFAULT_CONFIG.get('debounce_seconds', 2.0))
        self.start_phrases = list(DEFAULT_CONFIG['start_phrases'])
        self.stop_phrases = list(DEFAULT_CONFIG['stop_phrases'])
        self.stop_mode = str(DEFAULT_CONFIG.get('stop_mode', 'toggle_unsafe'))
        self.console_logging = bool(DEFAULT_CONFIG.get('console_logging', True))

        
        self.ensure_config()
        self.load_config()
        self.extract_default_sfx()

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

        
        words = text.split()
        if len(words) >= 3:
            
            has_nvidia = any(w in ['nvidia', 'nvideo', 'invidia'] for w in words)
            has_clip = 'clip' in words or 'klip' in words
            has_that = any(w in ['that', 'it', 'dat'] for w in words)
            if has_nvidia and has_clip and has_that:
                return True
        return False

    def parse_intent(self, text: str) -> str | None:
        t = text.lower().strip()
        if not t:
            return None
        words = t.split()
        nvidia_like = any(w in ['nvidia', 'nvideo', 'invidia'] for w in words)

        if nvidia_like and (('clip' in words or 'klip' in words) and any(w in ['that', 'it', 'dat'] for w in words)):
            return 'clip'
        if nvidia_like and (('start' in words or 'begin' in words) and any(w.startswith('record') for w in words)):
            return 'start'
        if nvidia_like and (('stop' in words or 'end' in words or 'halt' in words) and any(w.startswith('record') for w in words)):
            return 'stop'

        if SequenceMatcher(None, t, 'nvidia start recording').ratio() >= self.threshold:
            return 'start'
        if SequenceMatcher(None, t, 'nvidia stop recording').ratio() >= self.threshold:
            return 'stop'
        
        for phrase in self.start_phrases:
            if SequenceMatcher(None, t, phrase).ratio() >= self.threshold:
                return 'start'
        for phrase in self.stop_phrases:
            if SequenceMatcher(None, t, phrase).ratio() >= self.threshold:
                return 'stop'
        if self.similarity_check(t):
            return 'clip'
        return None

    def trigger_clip(self):
        """Trigger the configured hotkey to capture a clip."""
        try:
            pyautogui.hotkey(*self.hotkey_keys)
            self.play_sfx('clip')
        except Exception:
            pass

    def start_recording(self):
        """Start recording using Alt+F9 if not already recording."""
        try:
            if not self.is_recording:
                pyautogui.hotkey('alt', 'f9')
                self.is_recording = True
                self.play_sfx('start')
            else:
                if self.console_logging and not getattr(sys, 'frozen', False):
                    try:
                        print("Already recording — no action taken.")
                    except Exception:
                        pass
                # Play an informative sound so the user knows start was ignored
                self.play_sfx('already_recording')
        except Exception:
            pass

    def stop_recording(self):
        """Stop recording using Alt+F9 if currently recording.
        Does nothing if not currently recording to avoid accidentally starting recording.
        """
        try:
            if not self.is_recording:
                if self.console_logging and not getattr(sys, 'frozen', False):
                    try:
                        print("Not recording — no action taken.")
                    except Exception:
                        pass
                # Play an informative sound so the user knows stop was ignored
                self.play_sfx('not_recording')
                return
            pyautogui.hotkey('alt', 'f9')
            self.is_recording = False
            self.play_sfx('stop')
        except Exception:
            pass

    def sfx_output_dir(self) -> str:
        return os.path.join(app_dir(), SFX_DIR_NAME)

    def extract_default_sfx(self):
        out_dir = self.sfx_output_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
            for fname in SFX_FILES.values():
                dst = os.path.join(out_dir, fname)
                if not os.path.exists(dst):
                    src = resource_path(os.path.join(SFX_DIR_NAME, fname))
                    if os.path.exists(src):
                        shutil.copyfile(src, dst)
        except Exception:
            pass

    def play_sfx(self, kind: str):
        fname = SFX_FILES.get(kind)
        if not fname:
            return
        path = os.path.join(self.sfx_output_dir(), fname)
        if os.path.exists(path):
            try:
                playsound(path, block=False)
            except Exception:
                pass
            return
        if kind in ('already_recording', 'not_recording', 'failed'):
            candidates = ['failed', 'start', 'stop', 'clip']
        else:
            candidates = ['clip', 'start', 'stop', 'failed']
        for c in candidates:
            cfname = SFX_FILES.get(c)
            if not cfname:
                continue
            cpath = os.path.join(self.sfx_output_dir(), cfname)
            if os.path.exists(cpath):
                try:
                    playsound(cpath, block=False)
                except Exception:
                    pass
                return
        if self.console_logging and not getattr(sys, 'frozen', False):
            try:
                print(f"No SFX found for '{kind}' (looked for '{fname}').")
            except Exception:
                pass

    def can_trigger(self, kind: str) -> bool:
        now = time.time()
        last = self.last_action_times.get(kind, 0.0)
        if now - last >= self.debounce_seconds:
            self.last_action_times[kind] = now
            return True
        return False

    def audio_callback(self, indata, frames, time_info, status):
        """This is called from a separate thread for each audio block."""
        if status:
            
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

            
            os.remove(zip_path)
            try:
                # Move to new line (progress uses \r) and show a clear completion message
                sys.stdout.write("\n")
                sys.stdout.flush()
                print("VOSK model downloaded and ready.")
            except Exception:
                pass
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
        
        bundled_model_path = resource_path(MODEL_PATH)
        model_path = bundled_model_path if os.path.exists(bundled_model_path) else os.path.join(app_dir(), MODEL_PATH)

        if not os.path.exists(model_path):
            
            if not self.download_model():
                return False
            
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
                            
                            self.partial_clip_fired = False
                            if text and self.console_logging and not getattr(sys, 'frozen', False):
                                try:
                                    print(f"[final] {text}")
                                except Exception:
                                    pass
                            if text:
                                intent = self.parse_intent(text)
                                if intent and self.console_logging and not getattr(sys, 'frozen', False):
                                    try:
                                        print(f"-> intent: {intent}")
                                    except Exception:
                                        pass
                                if intent == 'clip':
                                    if self.can_trigger('clip'):
                                        threading.Thread(target=self.trigger_clip, daemon=True).start()
                                elif intent == 'start':
                                    if self.can_trigger('start'):
                                        threading.Thread(target=self.start_recording, daemon=True).start()
                                elif intent == 'stop':
                                    if self.can_trigger('stop'):
                                        threading.Thread(target=self.stop_recording, daemon=True).start()
                        else:
                            partial = json.loads(rec.PartialResult())
                            partial_text = partial.get('partial', '')
                            if partial_text and self.console_logging and not getattr(sys, 'frozen', False):
                                try:
                                    print(f"[partial] {partial_text}")
                                except Exception:
                                    pass
                            if partial_text and self.similarity_check(partial_text, threshold=self.partial_threshold):
                                if not self.partial_clip_fired and self.can_trigger('clip'):
                                    self.partial_clip_fired = True
                                    threading.Thread(target=self.trigger_clip, daemon=True).start()
                    except queue.Empty:
                        pass
        except Exception:
            
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
        if self.console_logging and not getattr(sys, 'frozen', False):
            try:
                print("Ready, listening for trigger phrases.")
            except Exception:
                pass
        return True

    def stop_listening(self):
        self.stop_event.set()
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=2.0)
        self.listener_thread = None

    
    def ensure_config(self):
        path = config_path()
        if not os.path.exists(path):
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(DEFAULT_CONFIG, f, sort_keys=False)
            except PermissionError:
                
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
            self.start_phrases = list(cfg.get('start_phrases', DEFAULT_CONFIG.get('start_phrases', [])))
            self.stop_phrases = list(cfg.get('stop_phrases', DEFAULT_CONFIG.get('stop_phrases', [])))
            self.threshold = float(cfg.get('threshold', DEFAULT_CONFIG['threshold']))
            self.partial_threshold = float(cfg.get('partial_threshold', DEFAULT_CONFIG['partial_threshold']))
            self.hotkey = str(cfg.get('hotkey', DEFAULT_CONFIG['hotkey']))
            self.hotkey_keys = [k.strip() for k in self.hotkey.split('+') if k.strip()]
            self.debounce_seconds = float(cfg.get('debounce_seconds', DEFAULT_CONFIG.get('debounce_seconds', 2.0)))
            self.stop_mode = str(cfg.get('stop_mode', DEFAULT_CONFIG.get('stop_mode', 'toggle_unsafe')))
            self.console_logging = bool(cfg.get('console_logging', DEFAULT_CONFIG.get('console_logging', True)))
        except Exception:
            
            pass

    def open_config(self, icon=None, item=None):  
        path = config_path()
        try:
            if sys.platform.startswith('win'):
                os.startfile(path)  
            else:
                import subprocess
                subprocess.Popen(['xdg-open', path])
        except Exception:
            pass

    def reload_config(self, icon=None, item=None):  
        self.load_config()

    def exit_app(self, icon=None, item=None):  
        try:
            if self.icon:
                self.icon.visible = False
        except Exception:
            pass
        self.stop_listening()
        if self.icon:
            self.icon.stop()

    
    def create_icon_image(self, size=64, color=(0, 170, 255)):
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        r = size // 2 - 4
        center = (size // 2, size // 2)
        draw.ellipse([(center[0]-r, center[1]-r), (center[0]+r, center[1]+r)], outline=color, width=4)
        tri = [(size*0.42, size*0.35), (size*0.42, size*0.65), (size*0.7, size*0.5)]
        draw.polygon(tri, fill=color)
        return img

    def run_tray(self):
        
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

    def _test_simulate_intents(self):
        
        self.last_action_times = {'clip': 0.0, 'start': 0.0, 'stop': 0.0}
        self.partial_clip_fired = False
        self.debounce_seconds = 1.0
        calls = []
        def mock_clip():
            calls.append('clip')
        def mock_start():
            calls.append('start')
        def mock_stop():
            calls.append('stop')
        
        self.trigger_clip = mock_clip
        self.start_recording = mock_start
        self.stop_recording = mock_stop
        
        for _ in range(5):
            if not self.partial_clip_fired and self.can_trigger('clip'):
                self.partial_clip_fired = True
                self.trigger_clip()
        
        self.partial_clip_fired = False
        
        time.sleep(1.1)
        if self.can_trigger('clip'):
            self.trigger_clip()
        
        if self.can_trigger('start'):
            self.start_recording()
        
        if self.can_trigger('start'):
            self.start_recording()
        
        time.sleep(1.1)
        if self.can_trigger('stop'):
            self.stop_recording()
        return calls

    def _test_simulate_stop_modes(self):
        self.last_action_times = {'clip': 0.0, 'start': 0.0, 'stop': 0.0}
        self.debounce_seconds = 0.0
        fired = []
        def mock_hotkey(*args, **kwargs):
            fired.append('alt+f9')
        
        import types
        self._orig_pyautogui_hotkey = getattr(pyautogui, 'hotkey', None)
        pyautogui.hotkey = lambda *a, **k: mock_hotkey()
        try:
            
            self.stop_mode = 'strict'
            self.is_recording = False
            if self.can_trigger('stop'):
                self.stop_recording()
            
            self.stop_mode = 'toggle_unsafe'
            # simulate that recording is currently active when testing toggle behavior
            self.is_recording = True
            if self.can_trigger('stop'):
                self.stop_recording()
        finally:
            if self._orig_pyautogui_hotkey:
                pyautogui.hotkey = self._orig_pyautogui_hotkey
        return fired


def main():
    clipper = NvidiaClipper()
    clipper.run_tray()


if __name__ == '__main__':
    main()
