import PyInstaller.__main__
import os
import shutil

def build_exe():
    """Build the executable using PyInstaller"""
    
    # Clean previous builds
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")
    
    # Check if model exists for bundling
    model_path = "vosk-model-small-en-us-0.15"
    add_data_args = []
    
    if os.path.exists(model_path):
        print(f"✅ Found VOSK model, will bundle with exe")
        add_data_args = [f'--add-data={model_path};{model_path}']
    else:
        print("ℹ️ VOSK model not found, will download on first run")
    
    PyInstaller.__main__.run([
        'nvidia_clip_that.py',
        '--onefile',
        '--name=NvidiaClipThat',
        '--icon=NONE',  # Add your icon path here if you have one
    '--additional-hooks-dir=hooks',
        *add_data_args,
        '--hidden-import=sounddevice',
        '--hidden-import=vosk',
        '--hidden-import=pyautogui',
    '--hidden-import=pystray',
    '--hidden-import=PIL',
    '--hidden-import=yaml',
    '--hidden-import=win32api',
    '--hidden-import=win32con',
    '--hidden-import=win32gui',
    '--noconsole',  # windowed app, runs in system tray
    ])
    
    print("✅ Build complete! Check the 'dist' folder for NvidiaClipThat.exe")

if __name__ == "__main__":
    build_exe()
