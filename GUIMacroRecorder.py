import tkinter as tk
from tkinter import messagebox, font, filedialog
import threading
import time
from pynput import mouse, keyboard
import sys
import ctypes
import pickle
from io import BytesIO

# The following libraries are required for the system tray icon feature.
# You can install them using: pip install pystray Pillow
try:
    from PIL import Image, ImageTk
    from pystray import MenuItem as item, Icon as icon
    TRAY_SUPPORTED = True
except ImportError:
    TRAY_SUPPORTED = False

# --- DPI Awareness (Windows Specific) ---
try:
    if sys.platform == "win32":
        ctypes.windll.user32.SetProcessDPIAware()
except AttributeError:
    pass

# --- Icon File ---
# The application will look for an icon file named "app_icon.ico" in the same directory.
ICON_FILE = "app_icon.ico"

# --- Globals ---
recorded_events = []
is_recording = False
is_playing = False
start_time = 0
SETTINGS_FILE = "recorder_settings.dat"
tray_icon = None

# --- Hotkey Configuration ---
hotkey_listener = None
# Default hotkeys
hotkeys = {
    'record': '<f9>',
    'play': '<f10>',
}
# A temporary listener for when we are setting a new hotkey
setting_hotkey_listener = None
pressed_keys = set()


# --- Event Recording Functions ---

def on_move(x, y):
    """Callback function to record mouse movement."""
    if is_recording:
        elapsed = time.monotonic() - start_time
        recorded_events.append((elapsed, 'move', (x, y)))

def on_click(x, y, button, pressed):
    """Callback function to record mouse clicks."""
    if is_recording:
        elapsed = time.monotonic() - start_time
        action = 'press' if pressed else 'release'
        recorded_events.append((elapsed, 'click', (x, y, button, action)))

def on_scroll(x, y, dx, dy):
    """Callback function to record mouse scrolling."""
    if is_recording:
        elapsed = time.monotonic() - start_time
        recorded_events.append((elapsed, 'scroll', (x, y, dx, dy)))

def on_key_press(key):
    """Callback function to record key presses."""
    if is_recording:
        elapsed = time.monotonic() - start_time
        recorded_events.append((elapsed, 'key_press', key))

def on_key_release(key):
    """Callback function to record key releases."""
    if is_recording:
        elapsed = time.monotonic() - start_time
        recorded_events.append((elapsed, 'key_release', key))

# --- Core Logic ---

def record_thread_func():
    """
    This function runs in a separate thread to listen for and record mouse and keyboard events.
    """
    global is_recording, start_time, recorded_events
    
    recorded_events = []
    start_time = time.monotonic()
    is_recording = True
    
    mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
    keyboard_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)
    
    mouse_listener.start()
    keyboard_listener.start()
    
    update_status("Recording... Press 'Stop' or F9 to finish.")
    record_button.config(state=tk.DISABLED)
    play_button.config(state=tk.DISABLED)
    stop_button.config(state=tk.NORMAL)
    save_button.config(state=tk.DISABLED)
    load_button.config(state=tk.DISABLED)
    
    while is_recording:
        time.sleep(0.1)
        
    mouse_listener.stop()
    keyboard_listener.stop()
    
    # The problematic logic that tried to remove the last click has been removed.
    # To end a recording accurately, the user should use the hotkey, which doesn't
    # add a final, unwanted event to the recording list. This preserves any
    # intentional pauses at the end of the action sequence.
            
    update_status(f"Recording stopped. {len(recorded_events)} events captured.")
    record_button.config(state=tk.NORMAL)
    load_button.config(state=tk.NORMAL)
    if recorded_events:
        play_button.config(state=tk.NORMAL)
        save_button.config(state=tk.NORMAL)
    stop_button.config(state=tk.DISABLED)


def play_thread_func():
    """
    This function runs in a separate thread to play back the recorded events.
    """
    global is_playing
    
    if not recorded_events:
        messagebox.showinfo("No Recording", "There are no actions to play. Please record or load first.")
        return

    is_playing = True
    
    mouse_controller = mouse.Controller()
    keyboard_controller = keyboard.Controller()

    # Get the playback speed from the GUI control
    speed = speed_multiplier.get()
    if speed <= 0: # Safety check to prevent division by zero or negative speed
        speed = 1
    
    update_status(f"Playing back at {speed}x speed... Press F10 to stop.")
    record_button.config(state=tk.DISABLED)
    play_button.config(state=tk.DISABLED)
    stop_button.config(state=tk.NORMAL)
    save_button.config(state=tk.DISABLED)
    load_button.config(state=tk.DISABLED)

    should_loop = loop_var.get()
    
    loop_count = 0
    
    while is_playing:
        loop_count += 1
        playback_start_time = time.monotonic()
        
        for i, event in enumerate(recorded_events):
            if not is_playing:
                update_status(f"Playback stopped by user at event {i+1}/{len(recorded_events)}.")
                break
                
            event_time, event_type, details = event
            
            # Key change: Scale the event's timestamp by the speed multiplier
            # This determines when the event *should* occur in the accelerated timeline.
            accelerated_event_time = event_time / speed
            
            current_time_offset = time.monotonic() - playback_start_time
            sleep_time = accelerated_event_time - current_time_offset

            if sleep_time > 0:
                time.sleep(sleep_time)

            if not is_playing: # Check again after sleeping, in case the user stopped it.
                break

            if event_type == 'move':
                mouse_controller.position = (details[0], details[1])
            elif event_type == 'click':
                x, y, button, action = details
                mouse_controller.position = (x, y)
                if action == 'press':
                    mouse_controller.press(button)
                else:
                    mouse_controller.release(button)
            elif event_type == 'scroll':
                x, y, dx, dy = details
                mouse_controller.position = (x, y)
                mouse_controller.scroll(dx, dy)
            elif event_type == 'key_press':
                keyboard_controller.press(details)
            elif event_type == 'key_release':
                keyboard_controller.release(details)
        else:
            # Only continue looping if should_loop is True AND is_playing is still True
            if should_loop and is_playing:
                update_status(f"Looping playback... Loop #{loop_count}")
                continue
        
        break

    if is_playing:
        update_status(f"Playback finished. {len(recorded_events)} events executed over {loop_count} loop(s).")

    is_playing = False
    
    record_button.config(state=tk.NORMAL)
    play_button.config(state=tk.NORMAL)
    stop_button.config(state=tk.DISABLED)
    save_button.config(state=tk.NORMAL if recorded_events else tk.DISABLED)
    load_button.config(state=tk.NORMAL)

# --- Hotkey and UI Functions ---

def toggle_record():
    """Starts or stops recording based on current state."""
    if is_recording:
        stop_action()
    else:
        # Prevent starting a new recording if playback is happening
        if not is_playing:
            start_recording()

def toggle_play():
    """Starts or stops playback based on current state."""
    if is_playing:
        stop_action()
    else:
        # Prevent starting playback if recording is happening
        if not is_recording:
            start_playing()

def emergency_stop_func():
    """Immediately stops any ongoing action."""
    global is_recording, is_playing
    if is_playing or is_recording:
        is_recording = False
        is_playing = False
        print("EMERGENCY STOP ACTIVATED")
        root.after(0, lambda: update_status("EMERGENCY STOPPED!"))

def start_recording():
    threading.Thread(target=record_thread_func, daemon=True).start()

def start_playing():
    threading.Thread(target=play_thread_func, daemon=True).start()

def stop_action():
    global is_recording, is_playing
    if is_recording:
        is_recording = False
    if is_playing:
        is_playing = False

def save_recording():
    if not recorded_events:
        messagebox.showwarning("No Data", "There is nothing to save.")
        return
    filepath = filedialog.asksaveasfilename(
        defaultextension=".rec",
        filetypes=[("Recording Files", "*.rec"), ("All Files", "*.*")],
        title="Save Recording"
    )
    if not filepath: return
    try:
        with open(filepath, 'wb') as f:
            pickle.dump(recorded_events, f)
        update_status(f"Recording saved to {filepath}")
    except Exception as e:
        messagebox.showerror("Save Error", f"Failed to save file: {e}")

def load_recording():
    global recorded_events
    filepath = filedialog.askopenfilename(
        filetypes=[("Recording Files", "*.rec"), ("All Files", "*.*")],
        title="Load Recording"
    )
    if not filepath: return
    try:
        with open(filepath, 'rb') as f:
            recorded_events = pickle.load(f)
        update_status(f"Loaded {len(recorded_events)} events from {filepath}")
        play_button.config(state=tk.NORMAL)
        save_button.config(state=tk.NORMAL)
    except Exception as e:
        messagebox.showerror("Load Error", f"Failed to load file: {e}")

def update_status(message):
    status_label.config(text=message)

# --- Settings Persistence ---

def save_settings():
    """Saves the current hotkey configuration to a file."""
    try:
        with open(SETTINGS_FILE, 'wb') as f:
            pickle.dump(hotkeys, f)
    except Exception as e:
        # Silently fail, as this isn't a critical error to show to the user.
        print(f"Error saving settings: {e}")

def load_settings():
    """Loads hotkey configuration from a file if it exists."""
    global hotkeys
    try:
        with open(SETTINGS_FILE, 'rb') as f:
            loaded_hotkeys = pickle.load(f)
            # A simple check to ensure the loaded data is in the expected format
            if isinstance(loaded_hotkeys, dict) and 'record' in loaded_hotkeys and 'play' in loaded_hotkeys:
                hotkeys = loaded_hotkeys
    except FileNotFoundError:
        # This is expected on the first run, so we just use the defaults.
        pass
    except Exception as e:
        # If the file is corrupted or unreadable, defaults will be used.
        print(f"Error loading settings: {e}")


# --- Hotkey Settings Window ---

def get_key_str(key):
    """Formats a key object into a string for display."""
    if isinstance(key, keyboard.Key):
        return key.name.capitalize()
    elif isinstance(key, keyboard.KeyCode):
        return key.char
    return str(key)

def format_hotkey_string(keys):
    """Formats a set of keys into a pynput-compatible hotkey string."""
    # pynput format is <modifier>+<modifier>+<key>
    modifiers = {'ctrl_l', 'ctrl_r', 'alt_l', 'alt_gr', 'shift_l', 'shift_r', 'cmd'}
    
    sorted_keys = sorted([k.name if hasattr(k, 'name') else k.char for k in keys if k is not None])
    
    mod_str = "+".join(f"<{k.replace('_l','').replace('_r','') }>" for k in sorted_keys if k in modifiers)
    key_str = "".join(k for k in sorted_keys if k not in modifiers)

    if mod_str and key_str:
        return f"{mod_str}+{key_str}"
    elif key_str:
        # For single keys like F9, format them correctly
        if len(key_str) > 1:
            return f"<{key_str}>"
        return key_str
    return ""


def on_setting_press(key):
    pressed_keys.add(key)

def on_setting_release(key, action_type, button_to_update, window):
    global setting_hotkey_listener
    hotkey_str = format_hotkey_string(pressed_keys)
    
    if hotkey_str:
        hotkeys[action_type] = hotkey_str
        display_str = hotkey_str.replace('<', '').replace('>', ' ').replace('+', ' + ').title()
        button_to_update.config(text=display_str)
        update_hotkey_listeners()
        save_settings() # Save settings whenever a change is made
    
    pressed_keys.clear()
    if setting_hotkey_listener:
        setting_hotkey_listener.stop()
        setting_hotkey_listener = None
    window.grab_set() # Regain focus

def listen_for_hotkey(action_type, button_to_update, window):
    global setting_hotkey_listener
    button_to_update.config(text="Press a key...")
    pressed_keys.clear()
    # Release focus to listen globally
    window.grab_release()

    setting_hotkey_listener = keyboard.Listener(
        on_press=on_setting_press,
        on_release=lambda key: on_setting_release(key, action_type, button_to_update, window)
    )
    setting_hotkey_listener.start()

def open_hotkey_settings():
    settings_window = tk.Toplevel(root)
    settings_window.title("Hotkey Settings")
    settings_window.geometry("350x150")
    settings_window.configure(bg=BG_COLOR)
    settings_window.resizable(False, False)
    settings_window.grab_set() # Modal window
    # Set the same icon for the settings window
    try:
        # This will only work on Windows with an .ico file
        if sys.platform == "win32":
            settings_window.iconbitmap(ICON_FILE)
    except tk.TclError:
        # Silently fail if the icon cannot be set
        pass


    tk.Label(settings_window, text="Record/Stop:", bg=BG_COLOR, fg=FG_COLOR, font=button_font).grid(row=0, column=0, padx=10, pady=10, sticky='w')
    record_hotkey_btn = tk.Button(settings_window, text=hotkeys['record'].replace('<', '').replace('>', ' ').title(), font=button_font, width=15)
    record_hotkey_btn.grid(row=0, column=1, padx=10, pady=10)
    record_hotkey_btn.config(command=lambda: listen_for_hotkey('record', record_hotkey_btn, settings_window))

    tk.Label(settings_window, text="Playback/Stop:", bg=BG_COLOR, fg=FG_COLOR, font=button_font).grid(row=1, column=0, padx=10, pady=10, sticky='w')
    play_hotkey_btn = tk.Button(settings_window, text=hotkeys['play'].replace('<', '').replace('>', ' ').title(), font=button_font, width=15)
    play_hotkey_btn.grid(row=1, column=1, padx=10, pady=10)
    play_hotkey_btn.config(command=lambda: listen_for_hotkey('play', play_hotkey_btn, settings_window))

# --- System Tray and Icon Functions ---

def setup_icon():
    """Sets the application icon for the main window and taskbar."""
    try:
        # For Windows, iconbitmap is the most reliable way to set the window icon.
        if sys.platform == "win32":
            root.iconbitmap(ICON_FILE)
        # For other platforms, try using iconphoto with Pillow.
        else:
            if TRAY_SUPPORTED:
                icon_image = Image.open(ICON_FILE)
                # Keep a reference to prevent garbage collection
                root.icon_photo = ImageTk.PhotoImage(icon_image)
                root.iconphoto(True, root.icon_photo)
    except Exception as e:
        print(f"Could not load application icon '{ICON_FILE}': {e}")

def quit_window(icon, item):
    """Callback to properly close the application from the tray."""
    global hotkey_listener
    if hotkey_listener:
        hotkey_listener.stop()
    icon.stop()
    root.destroy()

def show_window(icon, item):
    """Callback to show the main window from the tray."""
    icon.stop()
    root.after(0, root.deiconify)
    root.after(0, root.attributes, '-topmost', 1)
    root.after(100, root.attributes, '-topmost', 0)


def hide_window():
    """Hides the main window and shows the system tray icon."""
    if not TRAY_SUPPORTED:
        on_closing() # Fallback to normal close if tray libs are missing
        return
        
    global tray_icon
    root.withdraw()
    try:
        image = Image.open(ICON_FILE)
        menu = (item('Show', show_window, default=True), item('Quit', quit_window))
        tray_icon = icon("Input Recorder", image, "Input Recorder", menu)
        
        # Run the icon in a separate thread so it doesn't block the GUI
        threading.Thread(target=tray_icon.run, daemon=True).start()
    except Exception as e:
        print(f"Failed to create tray icon from '{ICON_FILE}': {e}")
        # If tray icon fails, quit the app to avoid being stuck in a hidden state.
        on_closing()


def on_closing():
    """Handles application shutdown."""
    global hotkey_listener
    if hotkey_listener:
        hotkey_listener.stop()
    root.destroy()

# --- Initial Setup ---

def update_hotkey_listeners():
    global hotkey_listener
    if hotkey_listener:
        hotkey_listener.stop()

    hotkey_map = {
        hotkeys['record']: toggle_record,
        hotkeys['play']: toggle_play,
        '<ctrl>+<shift>+x': emergency_stop_func
    }
    hotkey_listener = keyboard.GlobalHotKeys(hotkey_map)
    hotkey_listener.start()
    print(f"Hotkeys updated: Record={hotkeys['record']}, Play={hotkeys['play']}")
    # Update info label
    info_label.config(text=f"Record Hotkey: {hotkeys['record'].upper()} | Play Hotkey: {hotkeys['play'].upper()}")

# --- GUI Setup ---
root = tk.Tk()
root.title("Input Recorder")
root.geometry("450x420") # Increased height for the new widget
root.resizable(False, False)
root.configure(bg="#2E2E2E")

# Fonts and Colors
title_font = font.Font(family="Helvetica", size=16, weight="bold")
button_font = font.Font(family="Helvetica", size=12)
status_font = font.Font(family="Helvetica", size=10, slant="italic")
BG_COLOR = "#2E2E2E"
FG_COLOR = "#FFFFFF"
BUTTON_BG = "#4A4A4A"
BUTTON_FG = "#FFFFFF"
ACCENT_COLOR = "#007ACC"

main_frame = tk.Frame(root, bg=BG_COLOR, padx=20, pady=20)
main_frame.pack(expand=True, fill=tk.BOTH)

title_label = tk.Label(main_frame, text="Mouse & Keyboard Recorder", font=title_font, bg=BG_COLOR, fg=FG_COLOR)
title_label.pack(pady=(0, 10))

# Info Label
info_label = tk.Label(main_frame, text="", font=status_font, bg=BG_COLOR, fg="#C0C0C0")
info_label.pack(pady=(0,10))

# --- Main Controls ---
button_frame = tk.Frame(main_frame, bg=BG_COLOR)
button_frame.pack(pady=5)
record_button = tk.Button(button_frame, text="Record", command=start_recording, font=button_font, bg=BUTTON_BG, fg=BUTTON_FG, width=8, relief=tk.FLAT, padx=5, pady=5)
record_button.grid(row=0, column=0, padx=5)
play_button = tk.Button(button_frame, text="Play", command=start_playing, state=tk.DISABLED, font=button_font, bg=BUTTON_BG, fg=BUTTON_FG, width=8, relief=tk.FLAT, padx=5, pady=5)
play_button.grid(row=0, column=1, padx=5)
stop_button = tk.Button(button_frame, text="Stop", command=stop_action, state=tk.DISABLED, font=button_font, bg=ACCENT_COLOR, fg=BUTTON_FG, width=8, relief=tk.FLAT, padx=5, pady=5)
stop_button.grid(row=0, column=2, padx=5)

# --- File Operations ---
file_frame = tk.Frame(main_frame, bg=BG_COLOR)
file_frame.pack(pady=10)
save_button = tk.Button(file_frame, text="Save", command=save_recording, state=tk.DISABLED, font=button_font, bg=BUTTON_BG, fg=BUTTON_FG, width=8, relief=tk.FLAT, padx=5, pady=5)
save_button.pack(side=tk.LEFT, padx=5)
load_button = tk.Button(file_frame, text="Load", command=load_recording, font=button_font, bg=BUTTON_BG, fg=BUTTON_FG, width=8, relief=tk.FLAT, padx=5, pady=5)
load_button.pack(side=tk.LEFT, padx=5)
hotkey_button = tk.Button(file_frame, text="Hotkeys", command=open_hotkey_settings, font=button_font, bg=BUTTON_BG, fg=BUTTON_FG, width=8, relief=tk.FLAT, padx=5, pady=5)
hotkey_button.pack(side=tk.LEFT, padx=5)

# --- Playback Options ---
options_frame = tk.Frame(main_frame, bg=BG_COLOR)
options_frame.pack(pady=10, fill=tk.X)

# Loop Checkbox
loop_var = tk.BooleanVar()
loop_checkbox = tk.Checkbutton(options_frame, text="Loop Playback", variable=loop_var, font=status_font, bg=BG_COLOR, fg=FG_COLOR, selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=FG_COLOR, borderwidth=0, highlightthickness=0)
loop_checkbox.pack()

# Speed Control Frame
speed_frame = tk.Frame(options_frame, bg=BG_COLOR)
speed_frame.pack(pady=(5,0))

speed_label_text = tk.Label(speed_frame, text="Playback Speed:", font=status_font, bg=BG_COLOR, fg=FG_COLOR)
speed_label_text.pack(side=tk.LEFT, padx=(0, 5))

speed_multiplier = tk.IntVar(value=1)

# Label to display the current speed value (e.g., "1x")
speed_value_label = tk.Label(speed_frame, text=f"{speed_multiplier.get()}x", font=status_font, bg=BG_COLOR, fg=FG_COLOR, width=3, anchor='w')

# Scale widget to select the speed
speed_scale = tk.Scale(speed_frame, from_=1, to=10, orient=tk.HORIZONTAL, variable=speed_multiplier,
                       bg=BG_COLOR, fg=FG_COLOR, troughcolor=BUTTON_BG, highlightthickness=0, showvalue=0,
                       command=lambda val: speed_value_label.config(text=f"{int(val)}x"))
speed_scale.pack(side=tk.LEFT)
speed_value_label.pack(side=tk.LEFT, padx=(5, 0))


# --- Status and Info ---
status_label = tk.Label(main_frame, text="Ready. Press 'Record' or 'Load' to start.", font=status_font, bg=BG_COLOR, fg="#C0C0C0", wraplength=400)
status_label.pack(pady=(10, 0), fill=tk.X)
emergency_label = tk.Label(main_frame, text="Emergency Stop Hotkey: Ctrl+Shift+X", font=status_font, bg=BG_COLOR, fg="#FFA500")
emergency_label.pack(side=tk.BOTTOM, pady=(10, 0))

# --- Main Loop ---
if __name__ == "__main__":
    setup_icon() # Set the custom icon
    # Set the action for closing the window (the 'X' button)
    if TRAY_SUPPORTED:
        root.protocol('WM_DELETE_WINDOW', hide_window) 
    else:
        root.protocol('WM_DELETE_WINDOW', on_closing)
        
    load_settings() # Load settings on startup
    update_hotkey_listeners()
    root.mainloop()