"""A small Markdown renderer for Tkinter's Text widget (no extra dependencies).

Supports headings, paragraphs, bold/italic/code, links, bullet and numbered
lists, block quotes, fenced code blocks, tables, horizontal rules and
collapsible <details> sections.
"""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

THEMES = {
    "light": {
        "bg": "#fbfbf9", "fg": "#1f2328", "muted": "#59636e", "link": "#0b62d6", "code_bg": "#eff1f3",
        "code_fg": "#1f2328", "quote": "#4d5862", "rule": "#d0d7de", "heading": "#0f1720", "find": "#ffe58a",
        "line_hl": "#fff3b0", "summary": "#6b4fbb", "table_bg": "#f4f5f7",
    },
    "dark": {
        "bg": "#16181d", "fg": "#d8dde3", "muted": "#8b949e", "link": "#58a6ff", "code_bg": "#22262e",
        "code_fg": "#e6edf3", "quote": "#9aa4af", "rule": "#30363d", "heading": "#f0f3f6", "find": "#6b5a14",
        "line_hl": "#4a3f12", "summary": "#b392f0", "table_bg": "#1d2026",
    },
}

INLINE_RE = re.compile(
    r"(?P<code>`+)(?P<code_text>.+?)(?P=code)"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_url><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<auto>https?://[^>\s]+)>"
    r"|\*\*(?P<bold>.+?)\*\*|__(?P<bold2>[^_]+?)__"
    r"|(?<![\w*])\*(?P<italic>[^*\s][^*]*?)\*(?!\w)|(?<![\w])_(?P<italic2>[^_\s][^_]*?)_(?![\w])"
)
HTML_TAG_RE = re.compile(r"</?(?:div|span|p|br|img|a|sub|sup|kbd|b|i|em|strong|picture|source|center|h\d)[^>]*>", re.I)


def anchor_for(text: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"[`*_\[\]()]", "", text)
    return re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")


class MarkdownView(ttk.Frame):
    def __init__(self, master, on_link=None, theme: str = "light", font_size: int = 11):
        super().__init__(master)
        self.on_link = on_link or (lambda url: None)
        self.theme = theme
        self.font_size = font_size
        self.text = tk.Text(self, wrap="word", padx=28, pady=18, borderwidth=0, highlightthickness=0,
                            cursor="arrow", spacing1=2, spacing3=2, undo=False)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.headings: list[tuple[int, str, str]] = []  # (level, title, text index)
        self.anchors: dict[str, str] = {}
        self._links: dict[str, str] = {}
        self._details = 0
        self._make_fonts()
        self.apply_theme(theme)

        self.text.tag_bind("link", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        self.text.tag_bind("summary", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("summary", "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        # Read-only, but still allow selecting and copying text.
        self.text.bind("<Key>", self._readonly)

    # -- setup -------------------------------------------------------------

    def _readonly(self, event):
        if event.state & 0x4 and event.keysym.lower() in ("c", "a"):
            if event.keysym.lower() == "a":
                self.text.tag_add("sel", "1.0", "end")
                return "break"
            return None
        if event.keysym in ("Up", "Down", "Prior", "Next", "Home", "End", "Left", "Right"):
            return None
        return "break"

    def _make_fonts(self):
        base = tkfont.nametofont("TkDefaultFont").actual("family")
        mono = tkfont.nametofont("TkFixedFont").actual("family")
        s = self.font_size
        self.fonts = {
            "body": tkfont.Font(family=base, size=s),
            "bold": tkfont.Font(family=base, size=s, weight="bold"),
            "italic": tkfont.Font(family=base, size=s, slant="italic"),
            "code": tkfont.Font(family=mono, size=s - 1),
            "h1": tkfont.Font(family=base, size=s + 11, weight="bold"),
            "h2": tkfont.Font(family=base, size=s + 6, weight="bold"),
            "h3": tkfont.Font(family=base, size=s + 3, weight="bold"),
            "h4": tkfont.Font(family=base, size=s + 1, weight="bold"),
            "small": tkfont.Font(family=base, size=s - 1),
        }

    def set_font_size(self, size: int):
        self.font_size = max(8, min(24, size))
        s = self.font_size
        sizes = {"body": s, "bold": s, "italic": s, "code": s - 1, "h1": s + 11, "h2": s + 6, "h3": s + 3, "h4": s + 1, "small": s - 1}
        for name, f in self.fonts.items():
            f.configure(size=sizes[name])

    def apply_theme(self, theme: str):
        self.theme = theme
        c = THEMES[theme]
        t = self.text
        t.configure(background=c["bg"], foreground=c["fg"], insertbackground=c["fg"], selectbackground=c["link"],
                    selectforeground=c["bg"], font=self.fonts["body"])
        t.tag_configure("bold", font=self.fonts["bold"])
        t.tag_configure("italic", font=self.fonts["italic"])
        t.tag_configure("code", font=self.fonts["code"], background=c["code_bg"], foreground=c["code_fg"])
        t.tag_configure("codeblock", font=self.fonts["code"], background=c["code_bg"], foreground=c["code_fg"],
                        lmargin1=16, lmargin2=16, rmargin=16, spacing1=0, spacing3=0, wrap="none")
        t.tag_configure("codelabel", font=self.fonts["small"], foreground=c["muted"], lmargin1=16)
        t.tag_configure("table", font=self.fonts["code"], background=c["table_bg"], lmargin1=8, lmargin2=8, wrap="none", spacing1=0, spacing3=0)
        t.tag_configure("tablehead", font=tkfont.Font(family=self.fonts["code"].actual("family"), size=self.font_size - 1, weight="bold"))
        t.tag_configure("link", foreground=c["link"], underline=True)
        for i in range(1, 5):
            t.tag_configure(f"h{i}", font=self.fonts[f"h{i}"], foreground=c["heading"],
                            spacing1={1: 6, 2: 18, 3: 14, 4: 10}[i], spacing3={1: 8, 2: 8, 3: 4, 4: 2}[i])
        t.tag_configure("quote", foreground=c["quote"], lmargin1=24, lmargin2=24, font=self.fonts["italic"])
        t.tag_configure("rule", foreground=c["rule"], justify="center")
        t.tag_configure("muted", foreground=c["muted"])
        t.tag_configure("summary", foreground=c["summary"], font=self.fonts["bold"])
        t.tag_configure("find", background=c["find"])
        t.tag_configure("line_hl", background=c["line_hl"])
        for depth in range(6):
            t.tag_configure(f"list{depth}", lmargin1=12 + 22 * depth, lmargin2=30 + 22 * depth)
        t.tag_raise("sel")

    # -- rendering ------------------------------------------------------------

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for tag in list(self.text.tag_names()):
            if tag.startswith(("link-", "details-")):
                self.text.tag_delete(tag)
        self.headings, self.anchors, self._links, self._details = [], {}, {}, 0

    def render(self, markdown: str):
        self.clear()
        self._render_blocks(markdown.replace("\r\n", "\n").replace("\t", "    ").split("\n"))
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")

    def render_code(self, code: str, language: str = "", highlight_line: int | None = None):
        """Show a source file with line numbers."""
        self.clear()
        lines = code.replace("\r\n", "\n").split("\n")
        width = len(str(len(lines)))
        for i, line in enumerate(lines, 1):
            self.text.insert("end", f"{i:>{width}}  ", ("codeblock", "muted"))
            self.text.insert("end", line + "\n", ("codeblock",))
        if highlight_line:
            self.text.tag_add("line_hl", f"{highlight_line}.0", f"{highlight_line}.end+1c")
            self.text.see(f"{max(1, highlight_line - 5)}.0")
            self.text.see(f"{highlight_line}.0")
        else:
            self.text.see("1.0")

    def _insert(self, text: str, tags=()):
        self.text.insert("end", text, tags)

    def _render_blocks(self, lines: list[str]):
        i, n = 0, len(lines)
        para: list[str] = []
        details_stack: list[str] = []

        def tags(*extra):
            return tuple(extra) + tuple(details_stack)

        def flush_para():
            if para:
                text = ""
                for j, l in enumerate(para):
                    hard_break = l.endswith("  ") or l.endswith("\\")
                    text += l.rstrip(" \\") + ("\n" if hard_break and j < len(para) - 1 else " ")
                self._inline(text.strip(), tags())
                self._insert("\n\n", tags())
                para.clear()

        while i < n:
            line = lines[i]
            stripped = line.strip()

            # Fenced code block
            m = re.match(r"^\s*(```+|~~~+)\s*([\w+\-#.]*)", line)
            if m:
                flush_para()
                fence, lang = m.group(1), m.group(2)
                body = []
                i += 1
                while i < n and not lines[i].strip().startswith(fence):
                    body.append(lines[i])
                    i += 1
                i += 1
                if lang and lang not in ("text", "txt"):
                    self._insert(lang + "\n", tags("codelabel"))
                self._insert("\n".join(body) + "\n", tags("codeblock"))
                self._insert("\n", tags())
                continue

            # <details> / <summary>
            m = re.match(r"^<details[^>]*>\s*(?:<summary>(.*?)</summary>)?\s*$", stripped, re.I)
            if m:
                flush_para()
                summary = m.group(1)
                if summary is None and i + 1 < n:
                    m2 = re.match(r"^\s*<summary>(.*?)</summary>\s*$", lines[i + 1], re.I)
                    if m2:
                        summary = m2.group(1)
                        i += 1
                self._details += 1
                tag = f"details-{self._details}"
                self.text.tag_configure(tag, elide=True)
                start = self.text.index("end-1c")
                self._insert(f"▶ {summary or 'Details'}\n", tags("summary"))
                toggle_tag = f"{tag}-toggle"
                self.text.tag_add(toggle_tag, start, self.text.index("end-1c"))
                self.text.tag_bind(toggle_tag, "<Button-1>", lambda e, t=tag, s=start: self._toggle(t, s))
                details_stack.append(tag)
                i += 1
                continue
            if re.match(r"^</details>\s*$", stripped, re.I):
                flush_para()
                if details_stack:
                    details_stack.pop()
                self._insert("\n", tags())
                i += 1
                continue

            # Blank line
            if not stripped:
                flush_para()
                i += 1
                continue

            # Heading
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
            if m:
                flush_para()
                level = min(len(m.group(1)), 4)
                title = m.group(2)
                index = self.text.index("end-1c")
                self._inline(title, tags(f"h{level}"))
                self._insert("\n", tags(f"h{level}"))
                plain = re.sub(r"[`*]|\[([^\]]*)\]\([^)]*\)", r"\1", title)
                self.headings.append((len(m.group(1)), plain, index))
                self.anchors.setdefault(anchor_for(title), index)
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
                flush_para()
                self._insert("─" * 60 + "\n\n", tags("rule"))
                i += 1
                continue

            # Table
            if stripped.startswith("|") and i + 1 < n and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
                flush_para()
                rows = []
                while i < n and lines[i].strip().startswith("|"):
                    rows.append(lines[i].strip())
                    i += 1
                self._table(rows, tags())
                continue

            # Block quote
            if stripped.startswith(">"):
                flush_para()
                quote = []
                while i < n and lines[i].strip().startswith(">"):
                    quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                text = "\n".join(l if l.endswith("  ") else l.rstrip() for l in quote).strip()
                for part in re.split(r"\n\s*\n", text):
                    part = re.sub(r"  +\n\s*", "\x00", part)  # two trailing spaces = line break
                    part = re.sub(r"\s*\n\s*", " ", part).replace("\x00", "\n")
                    self._inline(part, tags("quote"))
                    self._insert("\n", tags("quote"))
                self._insert("\n", tags())
                continue

            # List item
            m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
            if m:
                flush_para()
                depth = min(len(m.group(1).expandtabs(4)) // 2, 5)
                marker = "•" if m.group(2) in "-*+" else m.group(2)
                item = m.group(3)
                i += 1
                # Continuation lines (indented, not a new item)
                while i < n and lines[i].strip() and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]) \
                        and (lines[i].startswith("  ") or not re.match(r"^\s*(#|```|>|\|)", lines[i])) \
                        and lines[i].startswith(" "):
                    item += " " + lines[i].strip()
                    i += 1
                checkbox = re.match(r"^\[( |x|X)\]\s+(.*)", item)
                if checkbox:
                    marker = "☑" if checkbox.group(1).lower() == "x" else "☐"
                    item = checkbox.group(2)
                self._insert(f"{marker} ", tags(f"list{depth}"))
                self._inline(item, tags(f"list{depth}"))
                self._insert("\n", tags(f"list{depth}"))
                if i >= n or not lines[i].strip() or not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                    self._insert("\n", tags())
                continue

            # Stand-alone HTML lines we don't render
            if re.match(r"^</?(p|div|img|br|picture|source|center|h\d)\b", stripped, re.I):
                flush_para()
                i += 1
                continue

            para.append(line.strip() if not line.endswith("  ") else line.strip() + "  ")
            i += 1
        flush_para()

    def _toggle(self, tag: str, start: str):
        hidden = self.text.tag_cget(tag, "elide")
        now_hidden = not (hidden in (True, 1, "1", "true"))
        self.text.tag_configure(tag, elide=now_hidden)
        tags = self.text.tag_names(start)
        self.text.delete(start, f"{start}+1c")
        self.text.insert(start, "▶" if now_hidden else "▼", tags)

    def _table(self, rows: list[str], base_tags):
        def cells(row):
            row = row.strip().strip("|")
            return [self._plain(c.strip()) for c in re.split(r"(?<!\\)\|", row)]

        header = cells(rows[0])
        body = [cells(r) for r in rows[2:]]
        cols = max(len(header), *(len(r) for r in body)) if body else len(header)
        widths = [0] * cols
        for r in [header] + body:
            for j, c in enumerate(r):
                widths[j] = min(max(widths[j], len(c)), 90)

        def fmt(r):
            out = []
            for j in range(cols):
                c = r[j] if j < len(r) else ""
                if len(c) > 90:
                    c = c[:87] + "..."
                out.append(c.ljust(widths[j]))
            return "  " + "   ".join(out).rstrip() + "  \n"

        if any(header):
            self._insert(fmt(header), base_tags + ("table", "tablehead"))
            self._insert("  " + "   ".join("─" * w for w in widths) + "\n", base_tags + ("table", "muted"))
        for r in body:
            self._insert(fmt(r), base_tags + ("table",))
        self._insert("\n", base_tags)

    @staticmethod
    def _plain(text: str) -> str:
        text = re.sub(r"\[([^\]]+)\]\((?:<[^>]+>|[^)]+)\)", r"\1", text)
        text = text.replace("\\|", "|")
        return re.sub(r"(\*\*|__|`)", "", text)

    def _inline(self, text: str, base_tags=()):
        text = HTML_TAG_RE.sub("", text)
        pos = 0
        for m in INLINE_RE.finditer(text):
            if m.start() > pos:
                self._insert(self._unescape(text[pos:m.start()]), base_tags)
            if m.group("code_text") is not None:
                self._insert(m.group("code_text").strip(" "), base_tags + ("code",))
            elif m.group("link_text") is not None:
                url = m.group("link_url").strip("<>")
                self._link(self._plain(m.group("link_text")), url, base_tags)
            elif m.group("auto"):
                self._link(m.group("auto"), m.group("auto"), base_tags)
            elif m.group("bold") or m.group("bold2"):
                self._inline(m.group("bold") or m.group("bold2"), base_tags + ("bold",))
            elif m.group("italic") or m.group("italic2"):
                self._insert(m.group("italic") or m.group("italic2"), base_tags + ("italic",))
            pos = m.end()
        if pos < len(text):
            self._insert(self._unescape(text[pos:]), base_tags)

    @staticmethod
    def _unescape(text: str) -> str:
        return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>])", r"\1", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    def _link(self, label: str, url: str, base_tags):
        tag = f"link-{len(self._links)}"
        self._links[tag] = url
        # Inline code inside links keeps its look, but the whole thing is clickable.
        self._insert(label, base_tags + ("link", tag))
        self.text.tag_bind(tag, "<Button-1>", lambda e, u=url: self.on_link(u))

    # -- navigation ------------------------------------------------------------

    def goto_anchor(self, anchor: str) -> bool:
        index = self.anchors.get(anchor.lstrip("#").lower())
        if index is None:
            return False
        self.goto_index(index)
        return True

    def goto_index(self, index: str):
        self.text.yview(index)

    def find(self, query: str, forwards: bool = True) -> bool:
        self.text.tag_remove("find", "1.0", "end")
        if not query:
            return False
        start = self.text.index("insert")
        if forwards:
            start = f"{start}+1c"
        pos = self.text.search(query, start, stopindex=None, nocase=True, backwards=not forwards, elide=False)
        if not pos:
            return False
        end = f"{pos}+{len(query)}c"
        # Count every match so the highlight shows all of them.
        idx = "1.0"
        while True:
            idx = self.text.search(query, idx, stopindex="end", nocase=True)
            if not idx:
                break
            self.text.tag_add("find", idx, f"{idx}+{len(query)}c")
            idx = f"{idx}+{len(query)}c"
        self.text.mark_set("insert", pos)
        self.text.see(pos)
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", pos, end)
        return True
