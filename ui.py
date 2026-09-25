"""Compact, dark desktop interface for Tori Download."""
import os
import queue
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font, messagebox, simpledialog

BG = '#0e1823'
PANEL = '#172532'
ROW = '#1b2b39'
HEAD = '#101f2b'
LINE = '#304454'
TEXT = '#f2f7fa'
MUTED = '#a6bac7'
BLUE = '#5ac4dc'
GREEN = '#49d2a0'
GOLD = '#efc476'
RED = '#ef8190'


def category(filename):
    ext = Path(filename).suffix.lower()
    if ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv'}: return 'Video'
    if ext in {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg'}: return 'Audio'
    if ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.iso'}: return 'Compressed'
    if ext in {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv'}: return 'Document'
    if ext in {'.exe', '.msi', '.apk', '.dmg'}: return 'Application'
    return 'Misc'


def size_text(n):
    for unit, scale in [('GB', 1073741824), ('MB', 1048576), ('KB', 1024)]:
        if n >= scale: return f'{n / scale:.2f} {unit}'
    return f'{n} B'


def time_text(seconds):
    seconds = int(seconds)
    if seconds >= 3600: return f'{seconds//3600}h {(seconds%3600)//60}m'
    if seconds >= 60: return f'{seconds//60}m {seconds%60}s'
    return f'{seconds}s'


def run(api):
    root = tk.Tk()
    root.title('Tori Download Manager')
    root.geometry('1166x690')
    root.minsize(810, 460)
    root.configure(bg=BG)
    tray_actions = queue.Queue()
    tray_icon = None
    if os.name == 'nt':
        try:
            import pystray
            from PIL import Image
            assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
            picture = Image.open(assets / 'tori-logo.png').convert('RGBA')
            tray_icon = pystray.Icon('Tori Download', picture, 'Tori Download', menu=pystray.Menu(
                pystray.MenuItem('Open Tori', lambda _icon, _item: tray_actions.put('show'), default=True),
                pystray.MenuItem('Quit Tori', lambda _icon, _item: tray_actions.put('quit'))))
            import threading
            tray_ready = threading.Event()
            def tray_setup(icon):
                icon.visible = True
                tray_ready.set()
            threading.Thread(target=tray_icon.run, args=(tray_setup,), daemon=True).start()
            if not tray_ready.wait(5):
                raise RuntimeError('The system tray icon did not start')
        except (ImportError, OSError, RuntimeError) as exc:
            if tray_icon:
                try: tray_icon.stop()
                except (RuntimeError, OSError): pass
            tray_icon = None
            messagebox.showwarning('Tori background mode',
                                   f'System tray is unavailable. Install the Python requirements or rebuild the EXE: {exc}', parent=root)
    try:
        assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
        icon = tk.PhotoImage(file=str(assets / 'tori-logo.png')).subsample(7)
        root.iconphoto(True, icon)
    except (tk.TclError, OSError):
        pass
    # On supported Windows builds, request the same dark native caption as the app.
    if os.name == 'nt':
        try:
            import ctypes
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), 4)
        except (OSError, AttributeError):
            pass

    selected = None
    visible = []
    scroll_row = 0
    active_category = 'All Downloads'
    sort_key = 'last_try'
    sort_desc = True
    hint_until = 0
    hint = ''
    nav_buttons = {}
    content_font = font.Font(root, family='Segoe UI', size=9)
    header_font = font.Font(root, family='Segoe UI', size=9, weight='bold')
    categories = [('All Downloads', 0), ('Video', 1), ('Audio', 1),
                  ('Compressed', 1), ('Document', 1), ('Application', 1),
                  ('Misc', 1), ('Complete', 0), ('Incomplete', 0)]

    def alert(exc):
        messagebox.showerror('Tori Download', str(exc), parent=root)

    def notice(text, seconds=4):
        nonlocal hint, hint_until
        hint = text
        hint_until = time.monotonic() + seconds
        draw()

    def require_job():
        job = current_job()
        if not job: notice('Select a file in the table first.')
        return job

    def current_job():
        return api.get_job(selected) if selected is not None else None

    def add():
        url = simpledialog.askstring('New URL', 'Paste a direct HTTP(S) file link:', parent=root)
        if not url: return
        try:
            name = simpledialog.askstring('File name', 'Save as:', initialvalue=api.safe_name(url), parent=root)
            if name is None: return
            folder = filedialog.askdirectory(title='Save this download in', initialdir=str(api.DEST), parent=root)
            if folder:
                api.enqueue(url.strip(), name, folder)
                pick('All Downloads')
                notice('Download added. Open Settings to change the browser save folder.')
        except (ValueError, OSError) as exc: alert(exc)

    def resume():
        job = require_job()
        if not job: return
        if job['status'] == 'completed': return notice('This file has already finished. Right-click to open its folder.')
        if job['status'] == 'downloading': return notice('This file is already downloading.')
        if job['status'] in ('failed', 'cancelled'): api.retry(job['id'])
        else: api.start(job['id'])
        notice('Starting or resuming download…')

    def stop():
        job = require_job()
        if not job: return
        if job['status'] not in ('queued', 'downloading'): return notice('Only an active download can be stopped.')
        api.stop_job(selected, 'paused')
        notice('Download paused. Use Resume to continue.')

    def delete():
        job = require_job()
        if not job: return
        if not messagebox.askyesno('Remove download',
            f"Remove {job['filename']} from the list?\nAn unfinished .part file will also be deleted.\nA completed file stays on disk.", parent=root): return
        try:
            api.remove_job(selected)
            notice('Removed from the list.')
        except RuntimeError as exc: alert(exc)

    def rename():
        job = require_job()
        if not job: return
        value = simpledialog.askstring('Rename file', 'File name:', initialvalue=job['filename'], parent=root)
        if value:
            try:
                api.rename_job(job['id'], value)
                notice('Filename changed on disk and in the list.')
            except (ValueError, RuntimeError, OSError) as exc: alert(exc)

    def choose_folder():
        folder = filedialog.askdirectory(title='Default save folder for browser downloads',
                                         initialdir=str(api.DEST), parent=root)
        if folder:
            try:
                api.set_download_folder(folder)
                notice(f'New browser downloads will save in {api.DEST}')
            except (ValueError, OSError) as exc: alert(exc)

    def open_folder():
        job = current_job()
        folder = Path(job['folder']) if job and job.get('folder') else api.DEST
        if os.name == 'nt':
            try: os.startfile(folder)
            except OSError as exc: alert(exc)

    def extension_path():
        path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'extension'
        if not path.is_dir():
            path = Path(sys.executable).resolve().parent / 'extension' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent / 'extension'
        return path

    def panel(title, subtitle, height=290):
        window = tk.Toplevel(root, bg=BG)
        window.title(title)
        window.geometry(f'530x{height}')
        window.resizable(False, False)
        window.transient(root)
        tk.Label(window, text=title, bg=BG, fg=BLUE, font=('Segoe UI Semibold', 18)).pack(anchor='w', padx=24, pady=(20, 5))
        tk.Label(window, text=subtitle, bg=BG, fg=MUTED, font=('Segoe UI', 10),
                 wraplength=480, justify='left').pack(anchor='w', padx=24, pady=(0, 14))
        return window

    def panel_button(window, label, command, color=BLUE):
        tk.Button(window, text=label, command=command, bg=color, fg='#0a1b28',
                  activebackground='#d0edff', relief='flat', borderwidth=0, padx=14,
                  pady=8, font=('Segoe UI Semibold', 10), cursor='hand2').pack(anchor='w', padx=24, pady=5)

    def settings():
        window = panel('Settings', 'Default save folder and Windows sign-in startup. Existing files keep their own folder.', 350)
        tk.Label(window, text=str(api.DEST), bg=PANEL, fg=TEXT, font=('Segoe UI', 10),
                 wraplength=470, anchor='w', padx=10, pady=8).pack(fill='x', padx=24, pady=(0, 12))
        panel_button(window, 'Choose default folder', lambda: (window.destroy(), choose_folder()))
        panel_button(window, 'Open current save folder', lambda: (window.destroy(), open_default_folder()), GREEN)
        if os.name == 'nt':
            import startup
            auto = tk.BooleanVar(value=startup.startup_enabled(api.SETTINGS, api.STARTUP_DEFAULT))
            def update_startup():
                try:
                    startup.sync_startup(api.SETTINGS, auto.get(),
                                         default=api.STARTUP_DEFAULT, run_name=api.STARTUP_NAME)
                    notice('Start with Windows updated. Sign out and back in to test.')
                except OSError as exc:
                    auto.set(not auto.get())
                    alert(exc)
            tk.Checkbutton(window, text='Start Tori when I sign in to Windows', variable=auto,
                           command=update_startup, bg=BG, fg=TEXT, selectcolor=PANEL,
                           activebackground=BG, activeforeground=TEXT,
                           font=('Segoe UI', 10)).pack(anchor='w', padx=24, pady=(10, 0))

    def open_default_folder():
        if os.name == 'nt':
            try: os.startfile(api.DEST)
            except OSError as exc: alert(exc)

    def browsers():
        path = extension_path()
        window = panel('Browser connection',
                       ('Connector is running on this PC.' if api.server_ready else 'The local connector is unavailable.') +
                       '\nLoad the extension folder once in edge://extensions or chrome://extensions. Enable Developer mode, then choose Load unpacked. The extension popup shows ON or OFF.')
        panel_button(window, 'Open extension folder',
                     lambda: os.startfile(path) if os.name == 'nt' and path.is_dir()
                     else messagebox.showinfo('Extension folder', str(path), parent=window), GREEN)
        panel_button(window, 'Copy extension folder path',
                     lambda: (root.clipboard_clear(), root.clipboard_append(str(path)), notice('Extension folder path copied.')), BLUE)

    def quit_app():
        if not root.winfo_viewable():
            root.deiconify()
        if api.controls and not messagebox.askyesno('Quit Tori',
                'Downloads are active. Quit and pause them? You can resume after reopening Tori.', parent=root):
            return
        api.abort_offers()
        if tray_icon:
            tray_icon.stop()
        root.destroy()

    def show_window():
        root.deiconify()
        root.lift()
        root.focus_force()

    def on_window_close():
        if tray_icon:
            root.withdraw()
        else:
            quit_app()

    root.protocol('WM_DELETE_WINDOW', on_window_close)
    def process_tray_actions():
        try:
            while True:
                action = tray_actions.get_nowait()
                if action == 'show': show_window()
                elif action == 'quit':
                    quit_app()
                    return
        except queue.Empty:
            pass
        root.after(150, process_tray_actions)
    process_tray_actions()

    toolbar = tk.Frame(root, bg=HEAD, height=62)
    toolbar.pack(fill='x', side='top')
    toolbar.pack_propagate(False)

    def toolbar_icon(canvas, kind, color):
        line = lambda *coords, **kw: canvas.create_line(*coords, fill=color, width=2.1, capstyle='round', joinstyle='round', **kw)
        if kind == 'add':
            canvas.create_oval(6, 5, 30, 29, outline=color, width=2)
            line(18, 11, 18, 23); line(12, 17, 24, 17)
        elif kind == 'resume':
            canvas.create_oval(6, 5, 30, 29, outline=color, width=2)
            canvas.create_polygon(15, 11, 15, 23, 24, 17, fill=color, outline='')
        elif kind == 'stop':
            canvas.create_oval(6, 5, 30, 29, outline=color, width=2)
            canvas.create_rectangle(14, 13, 22, 21, fill=color, outline='')
        elif kind == 'delete':
            line(11, 11, 25, 11); line(14, 8, 22, 8)
            line(12, 13, 14, 26, 22, 26, 24, 13)
            line(17, 16, 17, 22); line(21, 16, 21, 22)
        elif kind == 'settings':
            line(8, 10, 28, 10); line(8, 17, 28, 17); line(8, 24, 28, 24)
            for x, y in ((14, 10), (23, 17), (17, 24)):
                canvas.create_oval(x-3, y-3, x+3, y+3, outline=color, fill=HEAD, width=2)
        elif kind == 'browsers':
            canvas.create_rectangle(6, 7, 27, 24, outline=color, width=2)
            line(7, 13, 26, 13)
            canvas.create_oval(10, 9, 12, 11, fill=color, outline='')
            canvas.create_oval(15, 9, 17, 11, fill=color, outline='')
            line(14, 28, 30, 28, 30, 16)
        elif kind == 'about':
            canvas.create_oval(7, 5, 29, 29, outline=color, width=2)
            canvas.create_oval(17, 10, 19, 12, fill=color, outline='')
            line(18, 16, 18, 24)
        elif kind == 'quit':
            canvas.create_arc(7, 7, 29, 29, start=130, extent=280, style='arc', outline=color, width=2)
            line(18, 5, 18, 18)

    def tool(label, kind, color, command, side='left'):
        cell = tk.Frame(toolbar, bg=HEAD, width=76, height=60, cursor='hand2')
        cell.pack(side=side, padx=1)
        cell.pack_propagate(False)
        tile = tk.Canvas(cell, width=36, height=34, bg=HEAD, highlightthickness=0, cursor='hand2')
        tile.pack(pady=(2, 0))
        toolbar_icon(tile, kind, color)
        caption = tk.Label(cell, text=label, bg=HEAD, fg=MUTED, font=('Segoe UI', 9), cursor='hand2')
        caption.pack()
        for widget in (cell, tile, caption):
            widget.bind('<Button-1>', lambda _event, action=command: action())
            widget.bind('<Enter>', lambda _event, caption=caption: caption.config(fg='white'))
            widget.bind('<Leave>', lambda _event, caption=caption: caption.config(fg=MUTED))

    tool('New URL', 'add', BLUE, add)
    tool('Resume', 'resume', GREEN, resume)
    tool('Stop', 'stop', GOLD, stop)
    tool('Delete', 'delete', RED, delete)
    tool('Quit', 'quit', RED, quit_app, 'right')
    tool('About', 'about', BLUE, lambda: messagebox.showinfo('About Tori', 'Tori Download Manager 0.22\nPersonal Windows testing build\nDirect HTTP(S) files\nNo artificial speed limit', parent=root), 'right')
    tool('Browsers', 'browsers', '#a994ff', browsers, 'right')
    tool('Settings', 'settings', GOLD, settings, 'right')

    overview = tk.Frame(root, bg=BG, height=90)
    overview.pack(fill='x', padx=14, pady=(10, 8))
    overview.pack_propagate(False)
    title_area = tk.Frame(overview, bg=BG)
    title_area.pack(side='left', fill='y', padx=(5, 28))
    tk.Label(title_area, text='Tori Download', bg=BG, fg=TEXT,
             font=('Segoe UI Semibold', 20)).pack(anchor='w')
    tk.Label(title_area, text='Your downloads, all in one place', bg=BG, fg=MUTED,
             font=('Segoe UI', 9)).pack(anchor='w', pady=(1, 0))
    summary = {}
    for key, label, accent in (('active', 'ACTIVE', BLUE), ('completed', 'COMPLETED', GREEN),
                               ('attention', 'NEEDS ATTENTION', RED)):
        card = tk.Frame(overview, bg=PANEL, highlightthickness=1, highlightbackground=LINE,
                        width=148, height=70)
        card.pack(side='left', padx=(0, 9))
        card.pack_propagate(False)
        tk.Label(card, text=label, bg=PANEL, fg=MUTED,
                 font=('Segoe UI Semibold', 8)).pack(anchor='w', padx=13, pady=(8, 0))
        value = tk.Label(card, text='0', bg=PANEL, fg=accent,
                         font=('Segoe UI Semibold', 19))
        value.pack(anchor='w', padx=13)
        summary[key] = value

    area = tk.Frame(root, bg=BG, highlightthickness=1, highlightbackground=LINE)
    area.pack(fill='both', expand=True, padx=10, pady=(0, 8))
    nav = tk.Frame(area, bg=PANEL, width=174, highlightthickness=1, highlightbackground=LINE)
    nav.pack(side='left', fill='y')
    nav.pack_propagate(False)

    def pick(name):
        nonlocal active_category, scroll_row
        active_category = name
        scroll_row = 0
        for key, (frame, icon, label) in nav_buttons.items():
            shade = '#31536d' if key == name else PANEL
            frame.config(bg=shade)
            icon.config(bg=shade)
            label.config(bg=shade, fg='white' if key == name else MUTED)
        refresh()

    category_colors = {'All Downloads': BLUE, 'Video': '#d5a8ff', 'Audio': '#78caff',
                       'Compressed': GOLD, 'Document': '#9fcaff', 'Application': '#b7a8ff',
                       'Misc': MUTED, 'Complete': GREEN, 'Incomplete': RED}

    def nav_icon(canvas, name, color):
        def line(*coords): canvas.create_line(*coords, fill=color, width=1.7, capstyle='round', joinstyle='round')
        if name in ('All Downloads', 'Complete', 'Incomplete'):
            canvas.create_polygon(2, 6, 6, 6, 8, 8, 16, 8, 16, 16, 2, 16,
                                  fill='', outline=color, width=1.5)
            if name == 'Complete': line(6, 12, 8, 14, 12, 10)
            if name == 'Incomplete': canvas.create_arc(6, 10, 12, 15, start=25, extent=285, outline=color)
        elif name == 'Video':
            canvas.create_rectangle(2, 4, 16, 15, outline=color, width=1.5)
            canvas.create_polygon(8, 7, 8, 12, 12, 9.5, fill=color)
        elif name == 'Audio':
            line(8, 13, 8, 5, 14, 4, 14, 12)
            canvas.create_oval(4, 12, 8, 15, fill=color, outline='')
            canvas.create_oval(10, 11, 14, 14, fill=color, outline='')
        elif name == 'Compressed':
            canvas.create_rectangle(3, 4, 15, 15, outline=color, width=1.5)
            line(6, 8, 12, 8); line(6, 11, 12, 11)
        elif name == 'Document':
            canvas.create_polygon(4, 3, 12, 3, 15, 6, 15, 16, 4, 16, fill='', outline=color, width=1.5)
            line(7, 9, 12, 9); line(7, 12, 12, 12)
        elif name == 'Application':
            for x in (4, 10):
                for y in (5, 11): canvas.create_rectangle(x, y, x+4, y+4, outline=color, width=1.5)
        else:
            for x in (5, 9, 13): canvas.create_oval(x, 9, x+2, 11, fill=color, outline='')

    for name, indent in categories:
        row = tk.Frame(nav, bg=PANEL, height=27, cursor='hand2')
        row.pack(fill='x')
        row.pack_propagate(False)
        icon_canvas = tk.Canvas(row, width=18, height=18, bg=PANEL, highlightthickness=0, cursor='hand2')
        icon_canvas.pack(side='left', padx=(20 if indent else 10, 5))
        nav_icon(icon_canvas, name, category_colors[name])
        label = tk.Label(row, text=name, bg=PANEL, fg=MUTED, anchor='w',
                         font=('Segoe UI', 9), cursor='hand2')
        label.pack(side='left', fill='x', expand=True)
        for widget in (row, icon_canvas, label):
            widget.bind('<Button-1>', lambda _event, item=name: pick(item))
        nav_buttons[name] = (row, icon_canvas, label)

    table_area = tk.Frame(area, bg=BG)
    table_area.pack(side='left', fill='both', expand=True, padx=(8, 0))
    bar = tk.Scrollbar(table_area, orient='vertical', troughcolor=PANEL, bg='#61768b', width=11)
    bar.pack(side='right', fill='y')
    grid = tk.Canvas(table_area, bg=PANEL, highlightthickness=0, bd=0, yscrollincrement=20)
    grid.pack(side='left', fill='both', expand=True)
    ROW_H, HEADER_H = 34, 36

    def columns(width):
        # Same columns and similar proportions as the reference screenshot.
        boundaries = [0, .31, .42, .56, .70, .85, 1]
        return [round(width * point) for point in boundaries]

    def fitted(value, limit, display_font=content_font):
        value = str(value)
        if limit <= 0: return ''
        if display_font.measure(value) <= limit: return value
        while value and display_font.measure(value + '…') > limit: value = value[:-1]
        return value + '…'

    def draw():
        grid.delete('all')
        width = max(1, grid.winfo_width())
        height = max(1, grid.winfo_height())
        xs = columns(width)
        grid.create_rectangle(0, 0, width, height, fill=PANEL, outline='')
        grid.create_rectangle(0, 0, width, HEADER_H, fill=HEAD, outline='')
        headings = ('File Name', 'Size', 'Status', 'Bandwidth', 'Remaining Time', 'Last Try')
        keys = ('filename', 'total', 'status', 'bandwidth', 'remaining', 'last_try')
        for index, heading in enumerate(headings):
            if keys[index] == sort_key: heading += ' ↓' if sort_desc else ' ↑'
            grid.create_text(xs[index] + 7, HEADER_H / 2, text=fitted(heading, xs[index+1]-xs[index]-12, header_font),
                             anchor='w', fill=BLUE if keys[index] == sort_key else TEXT, font=header_font)
        if not visible:
            cx = width / 2
            cy = max(HEADER_H + 95, height / 2 - 28)
            grid.create_oval(cx-25, cy-55, cx+25, cy-5, outline=BLUE, width=2, tags='empty')
            grid.create_line(cx, cy-43, cx, cy-19, fill=BLUE, width=2, tags='empty')
            grid.create_line(cx-9, cy-28, cx, cy-19, cx+9, cy-28, fill=BLUE, width=2, tags='empty')
            grid.create_text(cx, cy+18, text='No downloads here yet' if active_category == 'All Downloads'
                             else 'No downloads in this category', fill=TEXT,
                             font=('Segoe UI Semibold', 15), tags='empty')
            grid.create_text(cx, cy+45, text='Add a link or download from your browser' if active_category == 'All Downloads'
                             else 'Choose All Downloads to see your other files', fill=MUTED,
                             font=('Segoe UI', 10), tags='empty')
            if active_category == 'All Downloads':
                grid.create_rectangle(cx-65, cy+69, cx+65, cy+105, fill=BLUE, outline='', tags='empty_add')
                grid.create_text(cx, cy+87, text='+  Add URL', fill=HEAD,
                                 font=('Segoe UI Semibold', 10), tags='empty_add')
            bar.set(0, 1)
            folder_var.set(hint if time.monotonic() < hint_until else f'Save to: {api.DEST}')
            rate_var.set('0 files     ↓ 0.0 MB/s')
            return
        capacity = max(1, (height-HEADER_H)//ROW_H + 1)
        for slot in range(capacity):
            top = HEADER_H + slot * ROW_H
            if top >= height: break
            index = scroll_row + slot
            job = visible[index] if index < len(visible) else None
            if job and job['id'] == selected:
                grid.create_rectangle(0, top, width, top+ROW_H, fill='#345e7c', outline='')
            elif slot % 2:
                grid.create_rectangle(0, top, width, top+ROW_H, fill=ROW, outline='')
            if job:
                total, done = job['total'], job['done']
                progress = f" {done*100/total:.0f}%" if total and job['status'] != 'completed' else ''
                speed = api.current_speed(job['id'])
                remaining = time_text(max(0, total-done)/speed) if speed > 0 and total and job['status'] == 'downloading' else '—'
                attempt = time.strftime('%d %b %H:%M', time.localtime(job['last_try'])) if job.get('last_try') else '—'
                cells = (job['filename'], size_text(total or done), job['status'].capitalize()+progress,
                         f'{speed/1048576:.2f} MB/s' if speed else '—', remaining, attempt)
                for col, value in enumerate(cells):
                    color = (GREEN if job['status'] == 'completed' else RED if job['status'] == 'failed'
                             else GOLD if job['status'] == 'paused' else BLUE) if col == 2 else GREEN if col == 3 and speed else TEXT
                    grid.create_text(xs[col]+10, top+ROW_H/2-2, text=fitted(value, xs[col+1]-xs[col]-20),
                                     anchor='w', fill=color, font=content_font)
                if total and job['status'] in ('downloading', 'paused'):
                    left, right = xs[2]+10, xs[3]-10
                    grid.create_rectangle(left, top+ROW_H-8, right, top+ROW_H-5,
                                          fill=LINE, outline='')
                    progress_width = max(0, min(right-left, (right-left)*done/total))
                    grid.create_rectangle(left, top+ROW_H-8, left+progress_width, top+ROW_H-5,
                                          fill=BLUE if job['status'] == 'downloading' else GOLD, outline='')
        # Draw the separators after all row fills. Otherwise the next row hides
        # every other line, making two rows look like one oversized row.
        for y in range(HEADER_H+ROW_H, height, ROW_H):
            grid.create_line(0, y, width, y, fill=LINE, width=1)
        for x in xs[1:-1]: grid.create_line(x, 0, x, height, fill=LINE, width=1)
        grid.create_line(0, HEADER_H, width, HEADER_H, fill=LINE, width=1)
        total_rows = max(capacity, len(visible))
        bar.set(scroll_row/total_rows, min(1, (scroll_row+capacity)/total_rows))
        job = current_job()
        save_path = job.get('folder') if job else str(api.DEST)
        folder_var.set(hint if time.monotonic() < hint_until else f'Save to: {save_path}')
        rate_var.set(f"{len(visible)} files     ↓ {sum(api.current_speed(job_id) for job_id in list(api.speeds))/1048576:.1f} MB/s")

    def scroll(*args):
        nonlocal scroll_row
        capacity = max(1, (grid.winfo_height()-HEADER_H)//ROW_H)
        maximum = max(0, len(visible)-capacity)
        if args[0] == 'moveto': scroll_row = round(float(args[1]) * maximum)
        else: scroll_row += int(args[1]) * (capacity if args[2] == 'pages' else 1)
        scroll_row = max(0, min(maximum, scroll_row))
        draw()

    def wheel(event):
        scroll('scroll', -1 if event.delta > 0 else 1, 'units')

    def clicked(event):
        nonlocal selected, sort_key, sort_desc, scroll_row
        if event.y < HEADER_H:
            keys = ('filename', 'total', 'status', 'bandwidth', 'remaining', 'last_try')
            xs = columns(grid.winfo_width())
            for index in range(len(keys)):
                if xs[index] <= event.x < xs[index+1]:
                    sort_desc = not sort_desc if sort_key == keys[index] else keys[index] != 'filename'
                    sort_key = keys[index]
                    scroll_row = 0
                    refresh()
                    return
        index = scroll_row + (event.y-HEADER_H)//ROW_H
        if event.y >= HEADER_H and 0 <= index < len(visible): selected = visible[index]['id']
        else: selected = None
        draw()

    menu = tk.Menu(root, tearoff=False, bg=PANEL, fg=TEXT, activebackground='#486277', activeforeground='white')
    menu.add_command(label='Resume / Retry', command=resume)
    menu.add_command(label='Stop', command=stop)
    menu.add_command(label='Rename', command=rename)
    menu.add_command(label='Open folder', command=open_folder)
    menu.add_command(label='Remove from list', command=delete)

    def context(event):
        clicked(event)
        if selected is not None:
            try: menu.tk_popup(event.x_root, event.y_root)
            finally: menu.grab_release()

    grid.bind('<Configure>', lambda _event: draw())
    grid.bind('<Button-1>', clicked)
    grid.bind('<Button-3>', context)
    grid.bind('<Double-1>', lambda _event: resume())
    grid.bind('<MouseWheel>', wheel)
    grid.tag_bind('empty_add', '<Button-1>', lambda _event: add())
    grid.tag_bind('empty_add', '<Enter>', lambda _event: grid.config(cursor='hand2'))
    grid.tag_bind('empty_add', '<Leave>', lambda _event: grid.config(cursor=''))
    bar.config(command=scroll)

    footer = tk.Frame(root, bg=BG, height=23)
    footer.pack(fill='x', side='bottom', padx=10)
    footer.pack_propagate(False)
    folder_var = tk.StringVar()
    rate_var = tk.StringVar()
    tk.Label(footer, textvariable=folder_var, bg=BG, fg=MUTED, font=('Segoe UI', 9), anchor='w').pack(side='left')
    tk.Label(footer, textvariable=rate_var, bg=BG, fg=MUTED, font=('Segoe UI', 9), anchor='e').pack(side='right')

    def refresh():
        nonlocal visible, selected
        with api.connection() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY id DESC')]
        summary['active'].config(text=str(sum(job['status'] in ('queued', 'downloading') for job in rows)))
        summary['completed'].config(text=str(sum(job['status'] == 'completed' for job in rows)))
        summary['attention'].config(text=str(sum(job['status'] in ('failed', 'cancelled') for job in rows)))
        name = active_category
        if name == 'Complete': visible = [job for job in rows if job['status'] == 'completed']
        elif name == 'Incomplete': visible = [job for job in rows if job['status'] != 'completed']
        elif name == 'All Downloads': visible = rows
        else: visible = [job for job in rows if category(job['filename']) == name]
        def row_key(job):
            if sort_key == 'bandwidth': return api.current_speed(job['id'])
            if sort_key == 'remaining':
                speed = api.current_speed(job['id'])
                return (job['total']-job['done'])/speed if speed and job['total'] else -1
            value = job.get(sort_key)
            return (value or '').lower() if isinstance(value, str) else value or 0
        visible.sort(key=row_key, reverse=sort_desc)
        if selected is not None and not any(job['id'] == selected for job in visible): selected = None
        draw()

    active_offer = [None]
    def confirm_offer(key):
        offer = api.offers.get(key)
        if not offer or api.offer_status(key) != 'pending': return
        show_window()
        window = tk.Toplevel(root, bg=BG)
        window.title('Confirm download — Tori')
        video = offer.get('kind') == 'video'
        window.geometry('560x448' if video else '560x350')
        window.resizable(False, False)
        window.transient(root)
        if os.name == 'nt': window.attributes('-topmost', True)
        window.offer_key = key
        active_offer[0] = window
        tk.Label(window, text='Save video' if video else 'Save download', bg=BG, fg=TEXT,
                 font=('Segoe UI Semibold', 18)).pack(anchor='w', padx=24, pady=(20, 9))
        tk.Label(window, text='Choose the file name and location before starting.', bg=BG, fg=MUTED,
                 font=('Segoe UI', 10)).pack(anchor='w', padx=24, pady=(0, 8))
        tk.Label(window, text=offer['url'][:150], bg=PANEL, fg=MUTED, wraplength=490,
                 justify='left', font=('Segoe UI', 9)).pack(anchor='w', padx=24, pady=(0, 13))
        tk.Label(window, text='FILE NAME', bg=BG, fg=MUTED,
                 font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=24)
        name = tk.StringVar(value=offer['filename'])
        tk.Entry(window, textvariable=name, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                 relief='flat', font=('Segoe UI', 10)).pack(fill='x', padx=24, ipady=8, pady=(4, 12))
        quality = tk.StringVar(value='Auto')
        if video:
            tk.Label(window, text='QUALITY / AUDIO', bg=BG, fg=MUTED,
                     font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=24)
            selector = tk.OptionMenu(window, quality, 'Auto')
            selector.configure(bg=PANEL, fg=TEXT, activebackground='#31536d',
                               activeforeground=TEXT, highlightthickness=0, relief='flat',
                               font=('Segoe UI', 10), anchor='w')
            selector['menu'].configure(bg=PANEL, fg=TEXT, activebackground='#31536d',
                                       activeforeground=TEXT)
            selector.pack(fill='x', padx=24, pady=(4, 1))
            format_hint = tk.StringVar(value='Checking available qualities…')
            tk.Label(window, textvariable=format_hint, bg=BG, fg=MUTED,
                     font=('Segoe UI', 9)).pack(anchor='w', padx=24, pady=(0, 8))
            def select_quality(value):
                quality.set(value)
                suffix = '.mp3' if value == 'MP3' else '.mp4'
                name.set(Path(name.get()).stem + suffix)
            def refresh_qualities():
                if not window.winfo_exists(): return
                available = list(offer.get('qualities', ['Auto']))
                menu = selector['menu']
                menu.delete(0, 'end')
                for item in available:
                    menu.add_command(label='MP3 (audio only)' if item == 'MP3' else item,
                                     command=lambda choice=item: select_quality(choice))
                if offer.get('quality_state') == 'checking':
                    window.after(400, refresh_qualities)
                elif offer.get('quality_state') == 'unavailable':
                    format_hint.set('Formats unavailable; Auto will retry when downloading.')
                else:
                    format_hint.set('Choose an available resolution or MP3 audio.')
            refresh_qualities()
        tk.Label(window, text='SAVE IN', bg=BG, fg=MUTED,
                 font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=24)
        path = tk.StringVar(value=str(api.DEST))
        row = tk.Frame(window, bg=BG)
        row.pack(fill='x', padx=24, pady=(4, 14))
        tk.Label(row, textvariable=path, bg=PANEL, fg=TEXT, anchor='w', padx=10,
                 font=('Segoe UI', 9)).pack(side='left', fill='x', expand=True, ipady=9)
        def browse():
            chosen = filedialog.askdirectory(title='Save this download in', initialdir=path.get(), parent=window)
            if chosen: path.set(chosen)
        tk.Button(row, text='Browse', command=browse, bg='#31536d', fg=TEXT,
                  relief='flat', padx=12, pady=6, cursor='hand2').pack(side='right', padx=(8, 0))
        buttons = tk.Frame(window, bg=BG)
        buttons.pack(fill='x', padx=24)
        def close(accepted):
            if accepted and (not name.get().strip() or not Path(path.get()).is_dir()):
                messagebox.showerror('Check download', 'Enter a file name and select an existing folder.', parent=window)
                return
            if api.resolve_offer(key, accepted, name.get(), path.get(), quality.get()):
                window.destroy()
                active_offer[0] = None
                if accepted:
                    notice('Checking the link; download will start shortly…', 6)
                    def watch_result():
                        status = api.offer_status(key)
                        if status == 'checking': root.after(300, watch_result)
                        elif status == 'fallback': notice('Tori could not fetch this file. Check the extension Tori only setting.', 7)
                    root.after(300, watch_result)
                else: notice('Download canceled.')
        tk.Button(buttons, text='Download', command=lambda: close(True), bg=GREEN, fg=HEAD,
                  font=('Segoe UI Semibold', 10), padx=20, pady=8, relief='flat').pack(side='right')
        tk.Button(buttons, text='Cancel', command=lambda: close(False), bg=PANEL, fg=TEXT,
                  font=('Segoe UI', 10), padx=20, pady=8, relief='flat').pack(side='right', padx=(0, 10))
        window.protocol('WM_DELETE_WINDOW', lambda: close(False))
        window.grab_set()
        window.focus_force()

    def process_offers():
        window = active_offer[0]
        if window and not window.winfo_exists(): active_offer[0] = None
        if window and api.offer_status(window.offer_key) != 'pending':
            window.destroy()
            active_offer[0] = None
        if active_offer[0] is None:
            try: confirm_offer(api.offer_queue.get_nowait())
            except queue.Empty: pass
        root.after(150, process_offers)

    pick('All Downloads')
    process_offers()
    def tick():
        refresh()
        root.after(600, tick)
    tick()
    if '--background' in sys.argv and tray_icon:
        root.withdraw()
    root.mainloop()
