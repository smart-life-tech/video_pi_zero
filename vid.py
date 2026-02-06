import os
import sys
import time
import threading
try:
    from signal import pause  # Unix-only; optional
except Exception:
    pause = None

# Tkinter for GUI (Windows embedding and Pi fullscreen backdrop)
try:
    import tkinter as tk
except ImportError:
    tk = None

# On Windows, try to locate VLC so python-vlc can find libvlc.dll
def _setup_vlc_windows():
    if not sys.platform.startswith("win"):
        # On Pi/Linux, skip Windows setup but return 4-tuple for unpacking compatibility
        return False, [], None, None
    candidates = []
    tried = []
    # Highest priority: explicit folder via CLI or env
    for arg in sys.argv[1:]:
        if arg.lower().startswith("--vlc-dir="):
            candidates.append(arg.split("=", 1)[1].strip('"'))
            break
    for env_name in ("VLC_PATH", "LIBVLC_PATH", "VLC_HOME"):
        p = os.environ.get(env_name)
        if p:
            candidates.append(p)
    # User-reported path fallback
    user_path = r"C:\Users\USER\Documents\VLC"
    candidates.append(user_path)
    # CLI override --vlc-dir=PATH
    for arg in sys.argv[1:]:
        if arg.lower().startswith("--vlc-dir="):
            candidates.append(arg.split("=", 1)[1].strip('"'))
            break
    # Common install locations
    candidates += [
        os.path.join(os.environ.get("ProgramFiles", r"C:\\Program Files"), "VideoLAN", "VLC"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)"), "VideoLAN", "VLC"),
    ]
    # Registry: HKLM/HKCU Software\\VideoLAN\\VLC (InstallDir), including Wow6432Node
    try:
        import winreg  # type: ignore
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VideoLAN\VLC"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\VideoLAN\VLC"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\VideoLAN\VLC"),
        ]
        for root, sub in reg_paths:
            try:
                with winreg.OpenKey(root, sub) as k:
                    try:
                        install_dir, _ = winreg.QueryValueEx(k, "InstallDir")
                        if install_dir:
                            candidates.insert(0, install_dir)
                    except FileNotFoundError:
                        pass
            except FileNotFoundError:
                continue
    except Exception:
        pass
    added = False
    selected = None
    selected_dll = None
    for base in candidates:
        if not base:
            continue
        tried.append(base)
        dll_path = os.path.join(base, "libvlc.dll")
        if os.path.isdir(base) and os.path.isfile(dll_path):
            try:
                # Python 3.8+: ensure the directory is in the DLL search path
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(base)
                # Also prepend to PATH for any plugin lookups
                os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")
                plugins = os.path.join(base, "plugins")
                if os.path.isdir(plugins):
                    os.environ["VLC_PLUGIN_PATH"] = plugins
                added = True
                selected = base
                selected_dll = dll_path
                break
            except Exception:
                continue
    return added, tried, selected, selected_dll

if sys.platform.startswith("win"):
    _vlc_added, _vlc_tried, _vlc_dir, _vlc_dll = _setup_vlc_windows()
else:
    # Skip Windows-specific setup entirely on Pi/Linux
    _vlc_added, _vlc_tried, _vlc_dir, _vlc_dll = (False, [], None, None)

try:
    import vlc
except FileNotFoundError as e:
    import struct, platform
    arch = f"Python {platform.python_version()} {struct.calcsize('P')*8}-bit on {platform.system()}"
    msg = (
        "python-vlc couldn't find libvlc.dll.\n"
        f"- Python/VLC arch: {arch}\n"
        "- Install VLC matching Python's bitness (64-bit Python -> 64-bit VLC).\n"
        "- Options to fix:\n"
        "  1) Install VLC and re-run, or\n"
        "  2) Set env var VLC_PATH to VLC folder (with libvlc.dll), or\n"
        "  3) Run: python vid.py --vlc-dir=\"C:\\Program Files\\VideoLAN\\VLC\"\n"
        "- Searched paths:\n  " + "\n  ".join(_vlc_tried)
    )
    print(msg)
    try:
        import vlc
    except FileNotFoundError:
        # Fallback: temporarily switch CWD to VLC dir so ".\\libvlc.dll" resolves
        if sys.platform.startswith("win") and _vlc_dir and os.path.isdir(_vlc_dir):
            _old_cwd = os.getcwd()
            try:
                os.chdir(_vlc_dir)
                import vlc  # retry import with CWD at VLC folder
            except FileNotFoundError:
                # Will report detailed diagnostics below
                pass
            finally:
                os.chdir(_old_cwd)
        # If still not imported, print diagnostics and raise
        if 'vlc' not in sys.modules:
            import struct, platform
            arch = f"Python {platform.python_version()} {struct.calcsize('P')*8}-bit on {platform.system()}"
            msg = (
                "python-vlc couldn't find libvlc.dll.\n"
                f"- Python/VLC arch: {arch}\n"
                "- Install VLC matching Python's bitness (64-bit Python -> 64-bit VLC).\n"
                "- Options to fix:\n"
                "  1) Install VLC and re-run, or\n"
                "  2) Set env var VLC_PATH to VLC folder (with libvlc.dll), or\n"
                "  3) Run: python vid.py --vlc-dir=\"C:\\Program Files\\VideoLAN\\VLC\"\n"
                "- Searched paths:\n  " + "\n  ".join(_vlc_tried)
            )
            print(msg)
            raise
    except OSError as e:
        # Commonly WinError 193 when VLC/Python bitness mismatch (e.g., 32-bit VLC with 64-bit Python)
        if getattr(e, "winerror", None) == 193 and sys.platform.startswith("win"):
            import struct, platform

            def _pe_machine(path: str):
                try:
                    with open(path, "rb") as f:
                        f.seek(0x3C)
                        offset = int.from_bytes(f.read(4), "little")
                        f.seek(offset + 4)
                        machine = int.from_bytes(f.read(2), "little")
                    return machine
                except Exception:
                    return None

            def _machine_str(machine):
                return {0x14c: "x86", 0x8664: "x64", 0x1c0: "ARM"}.get(machine, hex(machine) if machine else "unknown")

            dll_arch = _machine_str(_pe_machine(_vlc_dll)) if _vlc_dll else "unknown"
            py_arch = f"Python {platform.python_version()} {struct.calcsize('P')*8}-bit on {platform.system()}"
            msg = (
                "libvlc.dll was found but failed to load (likely bitness mismatch).\n"
                f"- Python arch: {py_arch}\n"
                f"- libvlc.dll arch: {dll_arch} (from {_vlc_dll or 'unknown'})\n"
                "- Action: install matching VLC (64-bit Python -> 64-bit VLC) and point --vlc-dir to it.\n"
                "- Currently tried paths:\n  " + "\n  ".join(_vlc_tried)
            )
            print(msg)
        raise

# Detect platform capabilities
HAS_GPIO = False
if not sys.platform.startswith("win"):
    try:
        from gpiozero import Button
        HAS_GPIO = True
    except Exception:
        HAS_GPIO = False
else:
    try:
        import msvcrt  # Windows console keyboard
    except Exception:
        msvcrt = None

# Initialize VLC
vlc_instance = vlc.Instance()
media_player = vlc_instance.media_player_new()
# Fullscreen on Pi; windowed on Windows for Tkinter embedding
if not sys.platform.startswith("win"):
    media_player.set_fullscreen(True)  # Pi/Linux: use VLC fullscreen
else:
    media_player.set_fullscreen(False)  # Windows: embed in Tkinter window
list_player = vlc_instance.media_list_player_new()
list_player.set_media_player(media_player)
list_player.set_playback_mode(vlc.PlaybackMode(0))  # Loop mode

# Pre-load all video media objects for instant switching
def _preload_videos():
    """Load all video paths once at startup and add to list_player for seamless switching."""
    video_map = {}
    media_list = vlc_instance.media_list_new()
    video_files = [
        "Process_step_1.mp4",
        "Process_step_2.mp4",
        "Guide_steps.mp4",
        "Warning.mp4",
        "Process_step_3.mp4",
    ]
    
    for idx, filename in enumerate(video_files):
        path = resolve_video_path(filename)
        try:
            media = vlc_instance.media_new(path)
            media_list.add_media(media)
            video_map[filename] = idx
            print(f"Preloaded [{idx}]: {filename} -> {path}")
        except Exception as e:
            print(f"Failed to preload {filename}: {e}")
    
    list_player.set_media_list(media_list)
    return video_map

# Resolve paths first, then preload
def resolve_video_path(filename: str) -> str:
    """Resolve a video path across environments (Windows test, Pi runtime).

    Tries, in order:
    - As-provided (relative/absolute)
    - ./Videos/<filename> relative to current working directory
    - /home/helmwash/Videos/<filename> (Pi default)
    Returns the first existing path, otherwise returns the original filename.
    """
    candidates = [
        filename,
        os.path.join(os.getcwd(), "Videos", filename),
        os.path.join("/home/helmwash/Videos", filename),
    ]
    
    for p in candidates:
        if os.path.exists(p):
            return p
    return filename

# Startup check: confirm required video files are present and readable
def check_startup_videos():
    required = [
        "Process_step_1.mp4",
        "Process_step_2.mp4",
        "Guide_steps.mp4",
        "Warning.mp4",
        "Process_step_3.mp4",
    ]
    missing = []
    for name in required:
        path = resolve_video_path(name)
        exists = os.path.exists(path)
        readable = os.access(path, os.R_OK) if exists else False
        if not exists:
            print(f"Warning: {name} not found (resolved path: {path})")
            missing.append(name)
        elif not readable:
            print(f"Warning: {name} not readable (path: {path})")
            missing.append(name)
        else:
            print(f"Startup check OK: {name} -> {path}")
    return missing

# Call after vlc_instance is ready
_missing = check_startup_videos()
if _missing:
    print("Startup check: missing/unreadable videos: " + ", ".join(_missing))
video_indices = _preload_videos()


def init_video_window():
    """Create a borderless fullscreen black window. 
    On Windows: embed VLC via hwnd. On Pi: use as backdrop for VLC fullscreen."""
    if tk is None:
        return None
    
    try:
        root = tk.Tk()
        root.title("Video Player")
        root.configure(bg="black")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        # Ensure the window covers the entire screen without borders
        root.overrideredirect(True)
        # Bind Escape key to quit (backup method)
        root.bind("<Escape>", lambda e: root.destroy())
        
        # On Windows: embed VLC into the window via hwnd
        if sys.platform.startswith("win"):
            hwnd = root.winfo_id()
            try:
                media_player.set_hwnd(hwnd)
            except Exception as e:
                print(f"Failed to set VLC hwnd: {e}")
        
        return root
    except Exception as e:
        print(f"Warning: Could not create fullscreen window: {e}")
        print("Continuing with VLC fullscreen only (no Tkinter backdrop)...")
        return None


def play_video(path_or_filename: str):
    """Jump to a preloaded video by filename. Seamless, no glitch."""
    if path_or_filename not in video_indices:
        print(f"Error: {path_or_filename} not found in preloaded videos")
        return
    idx = video_indices[path_or_filename]
    # Pause current playback to keep vout, then jump and seek to 0 for clean switch
    if list_player.is_playing():
        media_player.pause()
    list_player.play_item_at_index(idx)
    try:
        media_player.set_time(0)
    except Exception:
        pass
    media_player.play()
    print(f"Switched to: {path_or_filename}")


def exit_vlc():
    list_player.stop()
    print("Exit vlc")


def button_pressed_17():
    print("Button 17 was pressed!")
    play_video("Process_step_2.mp4")


def button_pressed_27():
    print("Button 27 was pressed!")
    play_video("Guide_steps.mp4")


def button_pressed_22():
    print("Button 22 was pressed!")
    play_video("Warning.mp4")


def button_pressed_4():
    print("Button 4 was pressed!")
    play_video("Process_step_1.mp4")


def button_pressed_18():
    print("Button 18 was pressed!")
    play_video("Process_step_3.mp4")


def keyboard_loop(root=None):
    if not sys.platform.startswith("win"):
        print("Keyboard mode not available on this platform.")
        return
    
    # Try to use global keyboard listener (works in fullscreen)
    try:
        import keyboard
        print("Keyboard mode (Windows, global listener): A=Step1, B=Step2, C=Guide, D=Warning, E=Step3, Q/Esc=Quit")
        print("DEBUG: keyboard module loaded. Press any key (should print below)...")
        _quit_flag = False
        
        def on_key(event):
            nonlocal _quit_flag
            key_name = event.name.lower()
            print(f"DEBUG: Key pressed: '{key_name}' (type: {event.event_type})")
            
            if key_name == 'a':
                print("DEBUG: Detected A - playing Step 1")
                button_pressed_4()
            elif key_name == 'b':
                print("DEBUG: Detected B - playing Step 2")
                button_pressed_17()
            elif key_name == 'c':
                print("DEBUG: Detected C - playing Guide")
                button_pressed_27()
            elif key_name == 'd':
                print("DEBUG: Detected D - playing Warning")
                button_pressed_22()
            elif key_name == 'e':
                print("DEBUG: Detected E - playing Step 3")
                button_pressed_18()
            elif key_name in ('q', 'esc'):
                print("Quitting...")
                _quit_flag = True
                if root is not None:
                    try:
                        root.quit()
                        root.destroy()
                    except Exception:
                        pass
        
        keyboard.on_press(on_key)
        print("Press A/B/C/D/E or Q/Esc to quit. Listening globally (even in fullscreen)...")
        
        # Keep running until Q is pressed
        while not _quit_flag:
            time.sleep(0.1)
        keyboard.unhook_all()
    except ImportError:
        # Fallback to msvcrt if keyboard module not available
        print("Note: 'keyboard' module not installed. Keyboard input only works when console has focus.")
        print("Install it with: pip install keyboard")
        print("Keyboard mode (Windows, console only): A=Process, B=Place, C=Warning, D=Stop, Q=Quit")
        if msvcrt is None:
            return
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                try:
                    key = ch.decode("utf-8").lower()
                except Exception:
                    continue
                if key == 'a':
                    button_pressed_4()
                elif key == 'b':
                    button_pressed_17()
                elif key == 'c':
                    button_pressed_27()
                elif key == 'd':
                    button_pressed_22()
                elif key == 'e':
                    button_pressed_18()
                elif key == 'q':
                    print("Quitting...")
                    break
            time.sleep(0.03)


def main():
    if HAS_GPIO:
        # Define GPIO buttons
        button4 = Button(4)
        button17 = Button(17)
        button27 = Button(27)
        button22 = Button(22)
        button18 = Button(18)

        # Assign callbacks
        button4.when_pressed = button_pressed_4
        button17.when_pressed = button_pressed_17
        button27.when_pressed = button_pressed_27
        button22.when_pressed = button_pressed_22
        button18.when_pressed = button_pressed_18

        # Create black fullscreen window on Pi
        root = init_video_window()
        if root is not None:
            print("Waiting for GPIO button presses (with black fullscreen)...")
            try:
                root.mainloop()
            except KeyboardInterrupt:
                pass
        else:
            # Fallback if window not created
            print("Waiting for GPIO button presses...")
            pause()  # Keep the script running indefinitely
    else:
        # Windows: create window and run keyboard listener in background
        root = init_video_window()
        t = threading.Thread(target=lambda: keyboard_loop(root), daemon=True)
        t.start()
        if root is not None:
            try:
                root.mainloop()
            except KeyboardInterrupt:
                pass
        else:
            # Fallback if window not created
            keyboard_loop(None)


if __name__ == "__main__":
    main()
 
