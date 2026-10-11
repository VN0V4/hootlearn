"""Tkinter desktop app: generate lessons and read any Markdown file."""

from __future__ import annotations

import json
import os
import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from urllib.parse import unquote

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import ai, levels
from .analyzer import detect_language
from .cli import generate_lesson
from .markdown_view import THEMES, MarkdownView

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hootlearn"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
DEFAULT_LESSON_DIR = Path.home() / "hootlearn-lessons"

WELCOME = f"""\
# Welcome to HootLearn

Turn any git repository, including ones written by AI coding assistants, into a **step-by-step lesson** that
teaches you how to build it yourself.

### How it works

1. On the left, pick a **local folder** or paste a **git URL** (for example `https://github.com/user/project`).
2. Choose your **skill level**. The lesson changes how much it explains and how much it gives away.
3. Optionally turn on **AI explanations**. Claude then writes a walkthrough for the most important files.
   This needs an Anthropic API key and costs a little per lesson. Without it, you still get a full lesson
   from static analysis.
4. Press **Generate lesson**. The Markdown file opens here when it's ready.

You can also open *any* Markdown file with **File → Open** (Ctrl+O), such as a project's README.

### Skill levels

{chr(10).join(f"- **{l.label}**: {l.who}" for l in levels.LEVELS.values())}

### Tips

- Click file links in a lesson to view that source file, with the line highlighted.
- Use **Contents** on the left to jump between sections, and Ctrl+F to search.
- Click **▶ Skeleton to fill in** inside a step to reveal the code outline.
"""


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(data: dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


class App:
    def __init__(self, root: tk.Tk, open_file: str | None = None):
        self.root = root
        self.settings = load_settings()
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.history: list[tuple[str, str | None, int | None]] = []   # (path, anchor, line)
        self.history_pos = -1
        self.current: Path | None = None

        root.title("HootLearn")
        root.geometry(self.settings.get("geometry", "1280x820"))
        root.minsize(900, 560)
        self.style = ttk.Style(root)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._bind_keys()
        self.apply_theme(self.settings.get("theme", "light"))

        if open_file:
            self.open_path(Path(open_file))
        else:
            self.show_welcome()
        self.refresh_lessons()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll_queue)

    # ------------------------------------------------------------------ layout

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open Markdown…", accelerator="Ctrl+O", command=self.open_dialog)
        file_menu.add_command(label="Reload", accelerator="F5", command=self.reload)
        self.recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Recent files", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Open lessons folder", command=lambda: self._open_external(self.output_dir()))
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view = tk.Menu(menubar, tearoff=False)
        view.add_command(label="Bigger text", accelerator="Ctrl++", command=lambda: self.zoom(1))
        view.add_command(label="Smaller text", accelerator="Ctrl+-", command=lambda: self.zoom(-1))
        view.add_command(label="Toggle dark mode", accelerator="Ctrl+D", command=self.toggle_theme)
        view.add_command(label="Expand all sections", command=lambda: self.set_details(False))
        view.add_command(label="Collapse all sections", command=lambda: self.set_details(True))
        menubar.add_cascade(label="View", menu=view)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Welcome page", command=self.show_welcome)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)
        self._update_recent_menu()

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.pack(side="top", fill="x")
        self.back_btn = ttk.Button(bar, text="◀ Back", width=8, command=self.go_back)
        self.back_btn.pack(side="left")
        self.fwd_btn = ttk.Button(bar, text="Forward ▶", width=10, command=self.go_forward)
        self.fwd_btn.pack(side="left", padx=(4, 12))
        ttk.Button(bar, text="Open .md…", command=self.open_dialog).pack(side="left")
        ttk.Button(bar, text="Reload", command=self.reload).pack(side="left", padx=4)

        ttk.Button(bar, text="☾ / ☀", width=6, command=self.toggle_theme).pack(side="right")
        ttk.Button(bar, text="A+", width=3, command=lambda: self.zoom(1)).pack(side="right", padx=2)
        ttk.Button(bar, text="A−", width=3, command=lambda: self.zoom(-1)).pack(side="right", padx=2)
        ttk.Button(bar, text="Next", command=lambda: self.do_find(True)).pack(side="right", padx=(2, 12))
        ttk.Button(bar, text="Prev", command=lambda: self.do_find(False)).pack(side="right", padx=2)
        self.find_var = tk.StringVar()
        self.find_entry = ttk.Entry(bar, textvariable=self.find_var, width=24)
        self.find_entry.pack(side="right", padx=4)
        self.find_entry.bind("<Return>", lambda e: self.do_find(True))
        self.find_entry.bind("<Shift-Return>", lambda e: self.do_find(False))
        ttk.Label(bar, text="Find:").pack(side="right")

    def _build_body(self):
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        side = ttk.Notebook(paned, width=360)
        paned.add(side, weight=0)
        self.viewer = MarkdownView(paned, on_link=self.on_link, font_size=self.settings.get("font_size", 11))
        paned.add(self.viewer, weight=1)
        self.sidebar = side

        side.add(self._build_generate_tab(side), text="Generate")
        side.add(self._build_contents_tab(side), text="Contents")
        side.add(self._build_lessons_tab(side), text="Lessons")

    def _build_generate_tab(self, parent):
        f = ttk.Frame(parent, padding=12)
        f.columnconfigure(0, weight=1)
        r = 0

        ttk.Label(f, text="Repository (folder or git URL)", style="Head.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        row = ttk.Frame(f)
        row.grid(row=r, column=0, sticky="ew", pady=(2, 10)); r += 1
        row.columnconfigure(0, weight=1)
        self.repo_var = tk.StringVar(value=self.settings.get("last_repo", ""))
        ttk.Entry(row, textvariable=self.repo_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Browse…", command=self.pick_repo).grid(row=0, column=1, padx=(4, 0))

        ttk.Label(f, text="Your skill level", style="Head.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        self.level_var = tk.StringVar(value=self.settings.get("level", levels.DEFAULT_LEVEL))
        for lv in levels.LEVELS.values():
            ttk.Radiobutton(f, text=lv.label, value=lv.key, variable=self.level_var,
                            command=self._update_level_help).grid(row=r, column=0, sticky="w"); r += 1
        self.level_help = ttk.Label(f, wraplength=320, style="Muted.TLabel", justify="left")
        self.level_help.grid(row=r, column=0, sticky="w", pady=(2, 10)); r += 1
        self._update_level_help()

        box = ttk.LabelFrame(f, text="AI explanations (optional)", padding=8)
        box.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        box.columnconfigure(1, weight=1)
        self.ai_var = tk.BooleanVar(value=self.settings.get("use_ai", False))
        ttk.Checkbutton(box, text="Ask Claude to explain the key files", variable=self.ai_var,
                        command=self._update_ai_state).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text="Model").grid(row=1, column=0, sticky="w", pady=2)
        self.model_var = tk.StringVar(value=self.settings.get("model", ai.DEFAULT_MODEL))
        self.model_box = ttk.Combobox(box, textvariable=self.model_var, values=list(ai.MODELS), state="readonly")
        self.model_box.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(box, text="API key").grid(row=2, column=0, sticky="w", pady=2)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(box, textvariable=self.key_var, show="•")
        self.key_entry.grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(box, text="Max files").grid(row=3, column=0, sticky="w", pady=2)
        self.max_files_var = tk.IntVar(value=self.settings.get("max_ai_files", 15))
        self.max_files = ttk.Spinbox(box, from_=1, to=200, textvariable=self.max_files_var, width=6)
        self.max_files.grid(row=3, column=1, sticky="w", pady=2)
        self.ai_status = ttk.Label(box, wraplength=300, style="Muted.TLabel", justify="left")
        self.ai_status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._update_ai_state()

        ttk.Label(f, text="Save lessons to", style="Head.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        row = ttk.Frame(f)
        row.grid(row=r, column=0, sticky="ew", pady=(2, 10)); r += 1
        row.columnconfigure(0, weight=1)
        self.out_var = tk.StringVar(value=self.settings.get("output_dir", str(DEFAULT_LESSON_DIR)))
        ttk.Entry(row, textvariable=self.out_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="…", width=3, command=self.pick_output).grid(row=0, column=1, padx=(4, 0))

        self.gen_btn = ttk.Button(f, text="Generate lesson", style="Accent.TButton", command=self.generate)
        self.gen_btn.grid(row=r, column=0, sticky="ew", ipady=4); r += 1
        self.progress = ttk.Progressbar(f, mode="indeterminate")
        self.progress.grid(row=r, column=0, sticky="ew", pady=(6, 6)); r += 1
        self.progress.grid_remove()  # only shown while working

        ttk.Label(f, text="Log", style="Head.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        self.log_text = tk.Text(f, height=8, wrap="word", borderwidth=0, highlightthickness=1, font=("TkFixedFont", 9))
        self.log_text.grid(row=r, column=0, sticky="nsew")
        f.rowconfigure(r, weight=1)
        return f

    def _build_contents_tab(self, parent):
        f = ttk.Frame(parent, padding=6)
        self.toc = ttk.Treeview(f, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(f, orient="vertical", command=self.toc.yview)
        self.toc.configure(yscrollcommand=scroll.set)
        self.toc.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.toc.bind("<<TreeviewSelect>>", self._toc_selected)
        self._toc_index: dict[str, str] = {}
        return f

    def _build_lessons_tab(self, parent):
        f = ttk.Frame(parent, padding=6)
        ttk.Label(f, text="Lessons in your output folder (double-click to open)", style="Muted.TLabel").pack(anchor="w")
        self.lessons = tk.Listbox(f, activestyle="none", borderwidth=0, highlightthickness=1)
        self.lessons.pack(fill="both", expand=True, pady=4)
        self.lessons.bind("<Double-Button-1>", self._lesson_opened)
        self.lessons.bind("<Return>", self._lesson_opened)
        buttons = ttk.Frame(f)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Refresh", command=self.refresh_lessons).pack(side="left")
        ttk.Button(buttons, text="Delete…", command=self.delete_lesson).pack(side="left", padx=4)
        return f

    def _build_statusbar(self):
        self.status = ttk.Label(self.root, padding=(8, 3), style="Muted.TLabel", anchor="w")
        self.status.pack(side="bottom", fill="x")

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-o>", lambda e: self.open_dialog())
        r.bind("<Control-q>", lambda e: self.on_close())
        r.bind("<Control-f>", lambda e: (self.find_entry.focus_set(), self.find_entry.select_range(0, "end")))
        r.bind("<Control-d>", lambda e: self.toggle_theme())
        r.bind("<Control-plus>", lambda e: self.zoom(1))
        r.bind("<Control-equal>", lambda e: self.zoom(1))
        r.bind("<Control-minus>", lambda e: self.zoom(-1))
        r.bind("<F5>", lambda e: self.reload())
        r.bind("<Alt-Left>", lambda e: self.go_back())
        r.bind("<Alt-Right>", lambda e: self.go_forward())

    # ------------------------------------------------------------------ theme

    def apply_theme(self, theme: str):
        self.theme = theme
        c = THEMES[theme]
        panel = "#eceef1" if theme == "light" else "#1f2229"
        field = "#ffffff" if theme == "light" else "#262a32"
        s = self.style
        s.configure(".", background=panel, foreground=c["fg"], fieldbackground=field, bordercolor=c["rule"],
                    lightcolor=panel, darkcolor=panel, troughcolor=field, insertcolor=c["fg"])
        s.configure("TEntry", fieldbackground=field, foreground=c["fg"])
        s.configure("TCombobox", fieldbackground=field, foreground=c["fg"], arrowcolor=c["fg"])
        s.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", c["fg"])])
        s.configure("TSpinbox", fieldbackground=field, foreground=c["fg"], arrowcolor=c["fg"])
        s.configure("TButton", background=field, foreground=c["fg"], padding=(8, 3))
        s.map("TButton", background=[("active", c["code_bg"]), ("disabled", panel)])
        s.configure("Accent.TButton", background=c["link"], foreground="#ffffff", font=("TkDefaultFont", 10, "bold"))
        s.map("Accent.TButton", background=[("active", c["link"]), ("disabled", c["rule"])])
        s.configure("TNotebook", background=panel)
        s.configure("TNotebook.Tab", background=panel, foreground=c["muted"], padding=(12, 4))
        s.map("TNotebook.Tab", background=[("selected", field)], foreground=[("selected", c["fg"])])
        s.configure("Treeview", background=field, fieldbackground=field, foreground=c["fg"], rowheight=24)
        s.map("Treeview", background=[("selected", c["link"])], foreground=[("selected", "#ffffff")])
        s.configure("Head.TLabel", font=("TkDefaultFont", 10, "bold"))
        s.configure("Muted.TLabel", foreground=c["muted"])
        s.configure("TLabelframe", background=panel)
        s.configure("TLabelframe.Label", background=panel, foreground=c["fg"])
        s.configure("TCheckbutton", background=panel, foreground=c["fg"])
        s.configure("TRadiobutton", background=panel, foreground=c["fg"])
        s.configure("Horizontal.TProgressbar", background=c["link"])
        self.root.configure(background=panel)
        for widget in (self.log_text, self.lessons):
            widget.configure(background=field, foreground=c["fg"], highlightbackground=c["rule"],
                             selectbackground=c["link"], selectforeground="#ffffff")
        self.log_text.configure(insertbackground=c["fg"])
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", c["fg"])
        self.viewer.apply_theme(theme)

    def toggle_theme(self):
        self.apply_theme("dark" if self.theme == "light" else "light")

    def zoom(self, delta: int):
        self.viewer.set_font_size(self.viewer.font_size + delta)

    def set_details(self, hidden: bool):
        t = self.viewer.text
        for tag in t.tag_names():
            if tag.startswith("details-") and not tag.endswith("-toggle"):
                if bool(t.tag_cget(tag, "elide") in (True, 1, "1", "true")) != hidden:
                    first = t.tag_ranges(f"{tag}-toggle")
                    if first:
                        self.viewer._toggle(tag, str(first[0]))

    # ------------------------------------------------------------------ generate tab

    def _update_level_help(self):
        lv = levels.get(self.level_var.get())
        self.level_help.configure(text=lv.who)

    def _update_ai_state(self):
        on = self.ai_var.get()
        for w in (self.model_box, self.key_entry, self.max_files):
            w.configure(state=("readonly" if w is self.model_box else "normal") if on else "disabled")
        if not ai.available():
            msg = "The `anthropic` package isn't installed, so lessons use static analysis only. Install it with: pip install anthropic"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            msg = "Using ANTHROPIC_API_KEY from your environment (leave the key box empty)."
        else:
            msg = "Paste an API key from console.anthropic.com, or set ANTHROPIC_API_KEY. The key is not saved."
        self.ai_status.configure(text=msg if on else "Off: lessons use static analysis only (free, offline).")

    def pick_repo(self):
        d = filedialog.askdirectory(title="Choose a repository folder", mustexist=True)
        if d:
            self.repo_var.set(d)

    def pick_output(self):
        d = filedialog.askdirectory(title="Where should lessons be saved?")
        if d:
            self.out_var.set(d)
            self.refresh_lessons()

    def output_dir(self) -> Path:
        return Path(self.out_var.get().strip() or DEFAULT_LESSON_DIR).expanduser()

    def log(self, msg: str):
        self.queue.put(("log", msg))

    def generate(self):
        if self.worker and self.worker.is_alive():
            return
        target = self.repo_var.get().strip()
        if not target:
            messagebox.showinfo("HootLearn", "Choose a repository folder or paste a git URL first.")
            return
        use_ai = self.ai_var.get()
        if use_ai and not ai.available():
            if not messagebox.askyesno("HootLearn", "The `anthropic` package is not installed, so AI explanations "
                                       "can't be used.\n\nGenerate the lesson with static analysis only?"):
                return
            use_ai = False
        try:
            max_files = max(1, int(self.max_files_var.get()))
        except (tk.TclError, ValueError):
            max_files = 15
        self.save_current_settings()
        self.log_text.delete("1.0", "end")
        self.gen_btn.configure(state="disabled", text="Working…")
        self.progress.grid()
        self.progress.start(12)
        args = dict(target=target, level_key=self.level_var.get(), out=self.output_dir(), use_ai=use_ai,
                    model=self.model_var.get(), max_ai_files=max_files, api_key=self.key_var.get().strip() or None,
                    log=self.log)

        def work():
            try:
                path = generate_lesson(**args)
                self.queue.put(("done", path))
            except Exception as e:  # show any failure in the GUI instead of crashing the thread
                self.queue.put(("error", f"{e}\n\n{traceback.format_exc(limit=3)}" if not isinstance(
                    e, (FileNotFoundError, RuntimeError, ValueError)) else str(e)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log_text.insert("end", payload + "\n")
                    self.log_text.see("end")
                    self.status.configure(text=payload)
                elif kind == "done":
                    self._finish()
                    self.refresh_lessons()
                    self.open_path(Path(payload))
                elif kind == "error":
                    self._finish()
                    self.log_text.insert("end", "Error: " + payload + "\n")
                    messagebox.showerror("HootLearn", payload.split("\n\n")[0])
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def _finish(self):
        self.progress.stop()
        self.progress.grid_remove()
        self.gen_btn.configure(state="normal", text="Generate lesson")

    # ------------------------------------------------------------------ lessons tab

    def refresh_lessons(self):
        self.lessons.delete(0, "end")
        self._lesson_paths = []
        d = self.output_dir()
        if d.is_dir():
            for p in sorted(d.glob("*.md"), key=lambda p: -p.stat().st_mtime):
                self._lesson_paths.append(p)
                self.lessons.insert("end", p.name)

    def _lesson_opened(self, _event=None):
        sel = self.lessons.curselection()
        if sel:
            self.open_path(self._lesson_paths[sel[0]])

    def delete_lesson(self):
        sel = self.lessons.curselection()
        if not sel:
            return
        p = self._lesson_paths[sel[0]]
        if messagebox.askyesno("Delete lesson", f"Delete {p.name}?"):
            p.unlink(missing_ok=True)
            self.refresh_lessons()

    # ------------------------------------------------------------------ viewing

    def show_welcome(self):
        self.current = None
        self.viewer.render(WELCOME)
        self._fill_toc()
        self.root.title("HootLearn")
        self.status.configure(text="Welcome")

    def open_dialog(self):
        start = str(self.current.parent if self.current else self.output_dir() if self.output_dir().is_dir() else Path.home())
        path = filedialog.askopenfilename(title="Open a Markdown file", initialdir=start,
                                          filetypes=[("Markdown", "*.md *.markdown *.mdown *.txt"), ("All files", "*")])
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path, anchor: str | None = None, line: int | None = None, record: bool = True):
        path = path.expanduser().resolve()
        if not path.is_file():
            messagebox.showerror("HootLearn", f"File not found:\n{path}")
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            messagebox.showerror("HootLearn", str(e))
            return
        is_md = path.suffix.lower() in (".md", ".markdown", ".mdown", ".mkd")
        if is_md:
            self.viewer.render(text)
        else:
            self.viewer.render_code(text, detect_language(path.name) or "", highlight_line=line)
        self.current = path
        self._fill_toc() if is_md else self._clear_toc()
        if anchor:
            self.viewer.goto_anchor(anchor)
        self.root.title(f"{path.name} – HootLearn")
        self.status.configure(text=str(path) + (f"  (line {line})" if line else ""))
        if record:
            self.history = self.history[: self.history_pos + 1] + [(str(path), anchor, line)]
            self.history_pos = len(self.history) - 1
        if is_md:
            self._add_recent(path)
        self._update_nav()

    def reload(self):
        if self.current:
            y = self.viewer.text.yview()[0]
            self.open_path(self.current, record=False)
            self.viewer.text.yview_moveto(y)

    def go_back(self):
        if self.history_pos > 0:
            self.history_pos -= 1
            p, a, l = self.history[self.history_pos]
            self.open_path(Path(p), a, l, record=False)

    def go_forward(self):
        if self.history_pos < len(self.history) - 1:
            self.history_pos += 1
            p, a, l = self.history[self.history_pos]
            self.open_path(Path(p), a, l, record=False)

    def _update_nav(self):
        self.back_btn.configure(state="normal" if self.history_pos > 0 else "disabled")
        self.fwd_btn.configure(state="normal" if self.history_pos < len(self.history) - 1 else "disabled")

    def on_link(self, url: str):
        if url.startswith("#"):
            if not self.viewer.goto_anchor(url[1:]):
                self.status.configure(text=f"Section not found: {url}")
            return
        if url.startswith(("http://", "https://", "mailto:")):
            webbrowser.open(url)
            return
        url = unquote(url.removeprefix("file://"))
        path_part, _, frag = url.partition("#")
        line = int(frag[1:]) if frag.startswith("L") and frag[1:].isdigit() else None
        base = self.current.parent if self.current else Path.cwd()
        path = Path(path_part)
        if not path.is_absolute():
            path = base / path
        if not path.exists():
            self.status.configure(text=f"Link target not found: {path}")
            return
        if path.is_dir():
            self._open_external(path)
            return
        self.open_path(path, anchor=None if line else (frag or None), line=line)

    def _open_external(self, path: Path):
        path.mkdir(parents=True, exist_ok=True) if not path.exists() else None
        webbrowser.open(path.resolve().as_uri())

    def do_find(self, forwards: bool):
        if not self.viewer.find(self.find_var.get(), forwards):
            self.status.configure(text=f"Not found: {self.find_var.get()}")

    # ------------------------------------------------------------------ contents / recent

    def _clear_toc(self):
        self.toc.delete(*self.toc.get_children())
        self._toc_index = {}

    def _fill_toc(self):
        self._clear_toc()
        parents: dict[int, str] = {}
        for level, title, index in self.viewer.headings:
            parent = ""
            for l in range(level - 1, 0, -1):
                if l in parents:
                    parent = parents[l]
                    break
            iid = self.toc.insert(parent, "end", text=title, open=level <= 2)
            parents[level] = iid
            for deeper in [l for l in parents if l > level]:
                del parents[deeper]
            self._toc_index[iid] = index

    def _toc_selected(self, _event=None):
        sel = self.toc.selection()
        if sel and sel[0] in self._toc_index:
            self.viewer.goto_index(self._toc_index[sel[0]])

    def _add_recent(self, path: Path):
        recent = [p for p in self.settings.get("recent", []) if p != str(path)]
        self.settings["recent"] = ([str(path)] + recent)[:12]
        self._update_recent_menu()

    def _update_recent_menu(self):
        self.recent_menu.delete(0, "end")
        recent = [p for p in self.settings.get("recent", []) if Path(p).exists()]
        if not recent:
            self.recent_menu.add_command(label="(none yet)", state="disabled")
        for p in recent:
            self.recent_menu.add_command(label=p, command=lambda p=p: self.open_path(Path(p)))

    # ------------------------------------------------------------------ settings

    def save_current_settings(self):
        self.settings.update(
            last_repo=self.repo_var.get().strip(), level=self.level_var.get(), use_ai=self.ai_var.get(),
            model=self.model_var.get(), output_dir=self.out_var.get().strip(), theme=self.theme,
            font_size=self.viewer.font_size, geometry=self.root.geometry(),
        )
        try:
            self.settings["max_ai_files"] = int(self.max_files_var.get())
        except (tk.TclError, ValueError):
            pass
        save_settings(self.settings)

    def on_close(self):
        self.save_current_settings()
        self.root.destroy()


def run_gui(open_file: str | None = None):
    root = tk.Tk()
    App(root, open_file)
    root.mainloop()
