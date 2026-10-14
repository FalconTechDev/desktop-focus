import ctypes
import json
import os
import shutil
import sys
import time
import tkinter as tk
import winreg
from ctypes import wintypes as wt
from pathlib import Path
from tkinter import messagebox, ttk

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")

user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = wt.HWND
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = wt.LPARAM
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
shell32.SHGetFolderPathW.argtypes = [wt.HWND, ctypes.c_int, wt.HANDLE, wt.DWORD, wt.LPWSTR]
shell32.SHParseDisplayName.argtypes = [wt.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), wt.ULONG, ctypes.POINTER(wt.ULONG)]
shell32.SHGetFileInfoW.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.UINT, wt.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

LVM_GETITEMCOUNT = 0x1004
LVM_SETITEMPOSITION = 0x100F
LVM_GETITEMPOSITION = 0x1010
LVM_GETITEMTEXTW = 0x1073
SKIP = {"desktop.ini", "thumbs.db"}
BIN_CLSID = "{645FF040-5081-101B-9F08-00AA002F954E}"
BIN_REG = r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"
STASH = Path.home() / ".desktop_focus_stash"
STATE_FILE = STASH / "state.json"


class LVITEM(ctypes.Structure):
    _fields_ = [
        ("mask", wt.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
        ("state", wt.UINT), ("stateMask", wt.UINT), ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int), ("lParam", ctypes.c_void_p),
    ]


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
        ("szDisplayName", ctypes.c_wchar * 260), ("szTypeName", ctypes.c_wchar * 80),
    ]


def known_dir(csidl):
    buf = ctypes.create_unicode_buffer(260)
    shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def display_name_of_path(path):
    buf = ctypes.create_unicode_buffer(str(path))
    info = SHFILEINFOW()
    shell32.SHGetFileInfoW(ctypes.cast(buf, ctypes.c_void_p), 0, ctypes.byref(info), ctypes.sizeof(info), 0x200)
    return info.szDisplayName or Path(path).name


def recycle_bin_name():
    pidl = ctypes.c_void_p()
    if shell32.SHParseDisplayName("::" + BIN_CLSID, None, ctypes.byref(pidl), 0, None) != 0:
        return "Recycle Bin"
    info = SHFILEINFOW()
    shell32.SHGetFileInfoW(pidl, 0, ctypes.byref(info), ctypes.sizeof(info), 0x200 | 0x8)
    ole32.CoTaskMemFree(pidl)
    return info.szDisplayName or "Recycle Bin"


def bin_visible():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, BIN_REG) as k:
            return winreg.QueryValueEx(k, BIN_CLSID)[0] == 0
    except OSError:
        return True


def set_bin_visible(visible):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, BIN_REG) as k:
        winreg.SetValueEx(k, BIN_CLSID, 0, winreg.REG_DWORD, 0 if visible else 1)


def find_desktop_windows():
    progman = user32.FindWindowW("Progman", None)
    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else None
    if not defview:
        w = None
        while True:
            w = user32.FindWindowExW(None, w, "WorkerW", None)
            if not w:
                return None, None
            defview = user32.FindWindowExW(w, None, "SHELLDLL_DefView", None)
            if defview:
                break
    return defview, user32.FindWindowExW(defview, None, "SysListView32", None)


def refresh_desktop():
    defview, _ = find_desktop_windows()
    if defview:
        user32.PostMessageW(defview, 0x111, 0x7103, 0)  # WM_COMMAND: refresh


class RemoteMem:
    def __init__(self, hwnd, size=4096):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self.proc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020 | 0x0400, False, pid.value)
        if not self.proc:
            raise OSError("Не удалось открыть процесс проводника")
        self.addr = kernel32.VirtualAllocEx(self.proc, None, size, 0x3000, 0x04)

    def write(self, offset, data):
        kernel32.WriteProcessMemory(self.proc, self.addr + offset, data, len(data), None)

    def read(self, offset, size):
        buf = ctypes.create_string_buffer(size)
        kernel32.ReadProcessMemory(self.proc, self.addr + offset, buf, size, None)
        return buf.raw

    def close(self):
        kernel32.VirtualFreeEx(self.proc, self.addr, 0, 0x8000)
        kernel32.CloseHandle(self.proc)


TEXT_OFF, POINT_OFF = 256, 1024


def read_icons():
    """Возвращает {отображаемое имя: (x, y)} для всех иконок, видимых сейчас на столе."""
    _, lv = find_desktop_windows()
    if not lv:
        return {}
    count = user32.SendMessageW(lv, LVM_GETITEMCOUNT, 0, 0)
    mem = RemoteMem(lv)
    icons = {}
    try:
        for i in range(count):
            item = LVITEM()
            item.iSubItem = 0
            item.pszText = mem.addr + TEXT_OFF
            item.cchTextMax = 260
            mem.write(0, bytes(item))
            user32.SendMessageW(lv, LVM_GETITEMTEXTW, i, mem.addr)
            text = mem.read(TEXT_OFF, 520).decode("utf-16-le").split("\x00")[0]
            user32.SendMessageW(lv, LVM_GETITEMPOSITION, i, mem.addr + POINT_OFF)
            x, y = ctypes.c_int32.from_buffer_copy(mem.read(POINT_OFF, 4)).value, \
                ctypes.c_int32.from_buffer_copy(mem.read(POINT_OFF + 4, 4)).value
            icons[text] = (x, y)
    finally:
        mem.close()
    return icons


def place_icons(positions):
    _, lv = find_desktop_windows()
    if not lv:
        return
    count = user32.SendMessageW(lv, LVM_GETITEMCOUNT, 0, 0)
    mem = RemoteMem(lv)
    try:
        for i in range(count):
            item = LVITEM()
            item.pszText = mem.addr + TEXT_OFF
            item.cchTextMax = 260
            mem.write(0, bytes(item))
            user32.SendMessageW(lv, LVM_GETITEMTEXTW, i, mem.addr)
            text = mem.read(TEXT_OFF, 520).decode("utf-16-le").split("\x00")[0]
            if text in positions:
                x, y = positions[text]
                user32.SendMessageW(lv, LVM_SETITEMPOSITION, i, ((y & 0xFFFF) << 16) | (x & 0xFFFF))
    finally:
        mem.close()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"hidden": [], "positions": {}, "keep": []}


def save_state(state):
    STASH.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def source_dirs():
    return {"user": known_dir(0x10), "public": known_dir(0x19)}


def move_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def hide(items, keep_names):
    """items: [{src, name, display}] — что скрыть. Возвращает список ошибок."""
    dirs = source_dirs()
    state = load_state()
    snapshot = read_icons()
    errors = []
    for it in items:
        try:
            if it["src"] == "bin":
                set_bin_visible(False)
            else:
                dst = STASH / it["src"] / it["name"]
                if dst.exists():
                    raise OSError("уже есть в тайнике")
                move_file(dirs[it["src"]] / it["name"], dst)
        except OSError as e:
            errors.append(f"{it['display']}: {e}")
            continue
        state["hidden"].append(it)
        if it["display"] in snapshot:
            state["positions"][it["display"]] = list(snapshot[it["display"]])
    state["keep"] = keep_names
    save_state(state)
    refresh_desktop()
    return errors


def restore():
    dirs = source_dirs()
    state = load_state()
    errors, still_hidden, restored = [], [], []
    for it in state["hidden"]:
        try:
            if it["src"] == "bin":
                set_bin_visible(True)
            else:
                dst = dirs[it["src"]] / it["name"]
                if dst.exists():
                    raise OSError("на столе уже есть такой элемент")
                move_file(STASH / it["src"] / it["name"], dst)
            restored.append(it["display"])
        except OSError as e:
            errors.append(f"{it['display']}: {e}")
            still_hidden.append(it)
    positions = {d: tuple(p) for d, p in state["positions"].items() if d in restored}
    state["hidden"] = still_hidden
    state["positions"] = {d: p for d, p in state["positions"].items() if d not in restored}
    save_state(state)
    refresh_desktop()
    deadline = time.time() + 6
    while restored and time.time() < deadline:
        time.sleep(0.4)
        if all(d in read_icons() for d in restored):
            break
    time.sleep(0.3)
    place_icons(positions)
    return errors


def visible_items():
    dirs = source_dirs()
    items = []
    for src, d in dirs.items():
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.name.lower() in SKIP:
                continue
            items.append({"src": src, "name": p.name, "display": display_name_of_path(p)})
    if bin_visible():
        items.append({"src": "bin", "name": BIN_CLSID, "display": recycle_bin_name()})
    items.sort(key=lambda i: i["display"].lower())
    return items


def ensure_admin():
    if shell32.IsUserAnAdmin() or "--no-elevate" in sys.argv:
        return True
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    script = os.path.abspath(sys.argv[0])
    shell32.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    r = shell32.ShellExecuteW(None, "runas", exe, f'"{script}"', None, 1)
    if r and r > 32:
        sys.exit(0)
    return False


class App:
    def __init__(self, root, is_admin):
        self.root = root
        root.title("Desktop Focus")
        root.geometry("460x580")
        STASH.mkdir(exist_ok=True)

        ttk.Label(root, text="Отметьте иконки, которые ОСТАВИТЬ на столе:",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)
        self.canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        btns = ttk.Frame(root)
        btns.pack(fill="x", padx=10, pady=8)
        self.hide_btn = ttk.Button(btns, text="Скрыть остальные", command=self.hide_others)
        self.hide_btn.pack(side="left", padx=(0, 6))
        self.show_btn = ttk.Button(btns, text="Вернуть всё", command=self.restore_all)
        self.show_btn.pack(side="left")
        ttk.Button(btns, text="Обновить", command=self.refresh).pack(side="right")

        self.status = ttk.Label(root, foreground="#555")
        self.status.pack(anchor="w", padx=10, pady=(0, 2))
        if not is_admin:
            ttk.Label(root, foreground="#b00",
                      text="Нет прав администратора: иконки общего стола скрыть не получится."
                      ).pack(anchor="w", padx=10, pady=(0, 6))

        self.items = []
        self.vars = []
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def refresh(self):
        keep = set(load_state().get("keep", []))
        for w in self.inner.winfo_children():
            w.destroy()
        self.items = visible_items()
        self.vars = []
        for it in self.items:
            v = tk.BooleanVar(value=it["display"] in keep)
            self.vars.append(v)
            ttk.Checkbutton(self.inner, text=it["display"], variable=v).pack(anchor="w")
        hidden = len(load_state()["hidden"])
        self.status.config(text=f"На столе: {len(self.items)} | Скрыто: {hidden}")
        self.show_btn.state(["!disabled"] if hidden else ["disabled"])
        self.hide_btn.state(["!disabled"] if self.items else ["disabled"])

    def report(self, title, errors):
        if errors:
            messagebox.showwarning(title, "\n".join(errors))

    def hide_others(self):
        keep = [it["display"] for it, v in zip(self.items, self.vars) if v.get()]
        to_hide = [it for it, v in zip(self.items, self.vars) if not v.get()]
        if not to_hide:
            return
        self.root.config(cursor="watch")
        self.root.update()
        errors = hide(to_hide, keep)
        self.root.config(cursor="")
        time.sleep(0.5)
        self.refresh()
        self.report("Не всё скрыто", errors)

    def restore_all(self):
        self.root.config(cursor="watch")
        self.root.update()
        errors = restore()
        self.root.config(cursor="")
        self.refresh()
        self.report("Не всё возвращено", errors)

    def on_close(self):
        if load_state()["hidden"]:
            ans = messagebox.askyesnocancel(
                "Скрытые иконки",
                "Иконки всё ещё скрыты.\n\nДа — вернуть на места и выйти\nНет — выйти, оставив скрытыми\nОтмена — остаться")
            if ans is None:
                return
            if ans:
                self.restore_all()
        self.root.destroy()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass
    admin = ensure_admin()
    if "--restore" in sys.argv:
        sys.exit(1 if restore() else 0)
    root = tk.Tk()
    App(root, bool(shell32.IsUserAnAdmin()))
    root.mainloop()
