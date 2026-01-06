import os
import sys
import time
try:
    from signal import pause  # Unix-only; optional
except Exception:
    pause = None

# On Windows, try to locate VLC so python-vlc can find libvlc.dll
def _setup_vlc_windows():
    if not sys.platform.startswith("win"):
        return False, []
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

_vlc_added, _vlc_tried, _vlc_dir, _vlc_dll = _setup_vlc_windows()

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
list_player = vlc_instance.media_list_player_new()
list_player.set_playback_mode(vlc.PlaybackMode(1))
media_player = vlc_instance.media_player_new()
media_player.set_fullscreen(True)
list_player.set_media_player(media_player)


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


def play_video(path_or_filename: str):
    path = resolve_video_path(path_or_filename)
    media_list = vlc_instance.media_list_new()
    media_list.add_media(path)
    list_player.set_media_list(media_list)
    list_player.play()
    print(f"Video started: {path}")


def exit_vlc():
    media_player.stop()
    print("Exit vlc")


def button_pressed_17():
    print("Button 17 was pressed!")
    play_video("Process.mp4")


def button_pressed_27():
    print("Button 27 was pressed!")
    play_video("Place.mp4")


def button_pressed_22():
    print("Button 22 was pressed!")
    play_video("Warning.mp4")


def button_pressed_4():
    print("Button 4 was pressed!")
    exit_vlc()


def keyboard_loop():
    if not sys.platform.startswith("win") or msvcrt is None:
        print("Keyboard loop not available on this platform.")
        return
    print("Keyboard mode (Windows): A=Process, B=Place, C=Warning, D=Stop, Q=Quit")
    while True:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            try:
                key = ch.decode("utf-8").lower()
            except Exception:
                continue
            if key == 'a':
                button_pressed_17()
            elif key == 'b':
                button_pressed_27()
            elif key == 'c':
                button_pressed_22()
            elif key == 'd':
                button_pressed_4()
            elif key == 'q':
                print("Quitting...")
                break
        time.sleep(0.03)


def main():
    if HAS_GPIO:
        # Define the GPIO pin connected to the button (e.g., pin 17)
        button17 = Button(17)
        button27 = Button(27)
        button22 = Button(22)
        button4 = Button(4)

        # Assign callbacks
        button17.when_pressed = button_pressed_17
        button27.when_pressed = button_pressed_27
        button22.when_pressed = button_pressed_22
        button4.when_pressed = button_pressed_4

        print("Waiting for GPIO button presses...")
        pause()  # Keep the script running indefinitely
    else:
        keyboard_loop()


if __name__ == "__main__":
    main()
 
