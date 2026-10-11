"""Static analysis of a repository: what is in each file and how the files fit together.

Parsing is done with tree-sitter (through `tree-sitter-language-pack`), which
understands 100+ languages in the same way. If that package is missing, a
simpler regex-based fallback is used so the tool still works.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import concepts as concept_lib
from .repo import SourceFile, git_history, list_files, read_text

try:
    import tree_sitter_language_pack as tslp
except ImportError:  # the tool still works, just less precisely
    tslp = None

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

EXT_LANGUAGES = {
    ".py": "python", ".pyw": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".mts": "typescript", ".tsx": "tsx", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala", ".c": "c", ".h": "c", ".cc": "cpp",
    ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".swift": "swift", ".dart": "dart", ".lua": "lua", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".r": "r", ".jl": "julia", ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".hs": "haskell",
    ".ml": "ocaml", ".clj": "clojure", ".zig": "zig", ".nim": "nim", ".vue": "vue", ".svelte": "svelte",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".sql": "sql", ".nix": "nix",
    ".md": "markdown", ".rst": "rst", ".txt": "text", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".xml": "xml", ".gradle": "groovy", ".ps1": "powershell",
}
NAME_LANGUAGES = {"Dockerfile": "dockerfile", "Makefile": "make", "CMakeLists.txt": "cmake", "Justfile": "make"}

DOC_LANGUAGES = {"markdown", "rst", "text"}
CONFIG_LANGUAGES = {"json", "yaml", "toml", "ini", "xml", "dockerfile", "make", "cmake", "nix", "groovy",
                    "gomod", "gosum", "gitignore", "gitattributes", "properties", "editorconfig", "csv"}
STYLE_LANGUAGES = {"css", "scss", "html"}

LANGUAGE_NAMES = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript", "tsx": "TypeScript (React)",
    "go": "Go", "rust": "Rust", "java": "Java", "kotlin": "Kotlin", "c": "C", "cpp": "C++", "csharp": "C#",
    "ruby": "Ruby", "php": "PHP", "swift": "Swift", "bash": "Shell", "html": "HTML", "css": "CSS",
    "scss": "SCSS", "sql": "SQL", "markdown": "Markdown", "json": "JSON", "yaml": "YAML", "toml": "TOML",
    "dockerfile": "Dockerfile", "make": "Makefile",
}

MAX_CODE_FILES = 3000


def detect_language(rel: str) -> str | None:
    name = rel.rsplit("/", 1)[-1]
    if name in NAME_LANGUAGES:
        return NAME_LANGUAGES[name]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext in EXT_LANGUAGES:
        return EXT_LANGUAGES[ext]
    if tslp is not None:
        try:
            return tslp.detect_language_from_path(rel)
        except Exception:
            return None
    return None


def language_name(lang: str) -> str:
    return LANGUAGE_NAMES.get(lang, lang.capitalize())


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Symbol:
    kind: str           # Function, Class, Method, Struct, ...
    name: str
    signature: str
    line: int           # 1-based
    end_line: int
    doc: str = ""
    children: list["Symbol"] = field(default_factory=list)
    recursive: bool = False
    decorators: list[str] = field(default_factory=list)


@dataclass
class FileInfo:
    rel: str
    language: str
    role: str                     # source | test | config | docs | style | other
    lines: int = 0
    code_lines: int = 0
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)       # raw import statements
    module_hints: list[str] = field(default_factory=list)  # e.g. Rust `mod foo;`
    internal_deps: list[str] = field(default_factory=list)  # other files in this repo it uses
    external_deps: list[str] = field(default_factory=list)  # libraries it uses
    concepts: dict[str, int] = field(default_factory=dict)
    is_entry: bool = False
    summary: str = ""             # first docstring / header comment
    parse_errors: int = 0

    @property
    def all_symbols(self) -> list[Symbol]:
        out = []
        for s in self.symbols:
            out.append(s)
            out.extend(s.children)
        return out


@dataclass
class Analysis:
    root: Path
    name: str
    files: list[FileInfo]
    languages: Counter
    readme: str
    manifests: dict[str, list[str]]       # manifest file -> declared dependencies
    entry_points: list[str]
    build_order: list[str]
    used_by: dict[str, list[str]]
    concept_files: dict[str, list[str]]   # concept key -> files using it
    history: dict
    parser: str
    skipped: list[str] = field(default_factory=list)

    def file(self, rel: str) -> FileInfo:
        return self._index[rel]

    def __post_init__(self):
        self._index = {f.rel: f for f in self.files}

    @property
    def code_files(self) -> list[FileInfo]:
        return [f for f in self.files if f.role in ("source", "test")]


# ---------------------------------------------------------------------------
# Per-file parsing
# ---------------------------------------------------------------------------

TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$|Tests?\.\w+$")
ENTRY_NAMES = {"main", "__main__", "app", "index", "cli", "server", "manage", "run", "program", "start"}
ENTRY_CODE_RE = re.compile(
    r"if\s+__name__\s*==\s*['\"]__main__['\"]|^func\s+main\s*\(|^\s*(?:pub\s+)?(?:async\s+)?fn\s+main\s*\(|"
    r"static\s+(?:async\s+)?\w+\s+[Mm]ain\s*\(|^int\s+main\s*\(|\.listen\(|createRoot\(|ReactDOM\.render\(",
    re.MULTILINE,
)


def classify(rel: str, language: str | None) -> str:
    if language in DOC_LANGUAGES:
        return "docs"
    parts = rel.split("/")
    if language in CONFIG_LANGUAGES or any(p.startswith(".") for p in parts):
        return "config"
    if len(parts) > 1 and parts[0].lower() in ("docs", "doc", "documentation"):
        return "docs"
    if language in STYLE_LANGUAGES:
        return "style"
    if language is None:
        return "other"
    return "test" if TEST_RE.search(rel) else "source"


def _clean_doc(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.strip()
    text = re.sub(r'^[rRbBuU]?("""|\'\'\'|"|\')', "", text)
    text = re.sub(r'("""|\'\'\'|"|\')$', "", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(///?|/\*\*?|\*/|\*|#+|--|;+)\s?", "", line).rstrip()
        line = re.sub(r"\*/\s*$", "", line).strip()
        lines.append(line)
    text = " ".join(l for l in lines if l).strip()
    # First sentence is enough for a summary.
    m = re.match(r"(.{20,300}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:300]).strip()


def _parse_with_tree_sitter(text: str, language: str) -> tuple[list[Symbol], list[str], list[str], str, int, int] | None:
    try:
        result = tslp.process(text, tslp.ProcessConfig(language=language, docstrings=True, comments=True))
    except Exception:
        return None
    docstrings = {d.associated_item: d.text for d in (result.docstrings or []) if d.associated_item}
    lines = text.splitlines()

    def convert(item) -> Symbol:
        span = item.span
        name = item.name or "(anonymous)"
        sym = Symbol(
            kind=str(item.kind),
            name=name,
            signature=(item.signature or (lines[span.start_line] if span.start_line < len(lines) else name)).strip(),
            line=span.start_line + 1,
            end_line=span.end_line + 1,
            doc=_clean_doc(item.doc_comment or docstrings.get(name)),
            children=[convert(c) for c in (item.children or [])],
            decorators=[d.strip() for d in (item.decorators or []) if d.strip()],
        )
        if sym.kind in ("Function", "Method") and item.body_span and item.name:
            body = text.encode()[item.body_span.start_byte:item.body_span.end_byte].decode("utf-8", "replace")
            sym.recursive = re.search(rf"(?<![\w.]){re.escape(item.name)}\s*\(|(?:self|this)\.{re.escape(item.name)}\s*\(", body) is not None
        return sym

    symbols = [convert(i) for i in (result.structure or [])]
    imports = [i.source.strip() for i in (result.imports or []) if i.source]
    mods = [s.name for s in symbols if s.kind == "Module" and language == "rust"]
    symbols = [s for s in symbols if not (s.kind == "Module" and language == "rust" and not s.children)]

    # A file-level summary: module docstring or the first comment at the top of the file.
    summary = ""
    for d in result.docstrings or []:
        if d.span.start_line <= 2 and not d.associated_item:
            summary = _clean_doc(d.text)
            break
    if not summary:
        for c in result.comments or []:
            if c.span.start_line <= 3 and not c.text.startswith("#!") and "license" not in c.text.lower():
                summary = _clean_doc(c.text)
                break
    if not summary and text.lstrip().startswith(('"""', "'''")):
        m = re.match(r'\s*("""|\'\'\')(.*?)\1', text, re.DOTALL)
        summary = _clean_doc(m.group(2)) if m else ""
    code_lines = result.metrics.code_lines if result.metrics else len(lines)
    errors = result.metrics.error_count if result.metrics else 0
    return symbols, imports, mods, summary, code_lines, errors


# Regex fallback: good enough to list top-level definitions in common languages.
FALLBACK_DEFS = [
    ("Class", re.compile(r"^([ \t]*)(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(?:public\s+|private\s+)?class\s+(\w+)[^\n]*", re.M)),
    ("Function", re.compile(r"^([ \t]*)(?:async\s+)?def\s+(\w+)\s*\([^\n]*", re.M)),
    ("Function", re.compile(r"^([ \t]*)(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\([^\n]*", re.M)),
    ("Function", re.compile(r"^([ \t]*)(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*=>[^\n]*", re.M)),
    ("Function", re.compile(r"^([ \t]*)func\s+(?:\([^)]*\)\s*)?(\w+)\s*\([^\n]*", re.M)),
    ("Function", re.compile(r"^([ \t]*)(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)[^\n]*", re.M)),
    ("Struct", re.compile(r"^([ \t]*)(?:pub\s+)?struct\s+(\w+)[^\n]*", re.M)),
    ("Struct", re.compile(r"^([ \t]*)type\s+(\w+)\s+struct\b[^\n]*", re.M)),
    ("Interface", re.compile(r"^([ \t]*)(?:export\s+)?interface\s+(\w+)[^\n]*", re.M)),
    ("Enum", re.compile(r"^([ \t]*)(?:export\s+)?(?:pub\s+)?enum\s+(\w+)[^\n]*", re.M)),
    ("Trait", re.compile(r"^([ \t]*)(?:pub\s+)?trait\s+(\w+)[^\n]*", re.M)),
]
FALLBACK_IMPORT = re.compile(
    r"^\s*(?:import\s+[^\n]+|from\s+\S+\s+import\s+[^\n]+|(?:const|let|var)\s+[^\n]*=\s*require\([^)]*\)[^\n]*|"
    r"use\s+[\w:{}, *]+;|#include\s*[<\"][^>\"]+[>\"]|require(?:_relative)?\s+['\"][^'\"]+['\"])",
    re.M,
)
FALLBACK_GO_BLOCK = re.compile(r"^import\s*\(([^)]*)\)", re.M)


def _parse_with_regex(text: str, language: str):
    symbols = []
    for kind, rx in FALLBACK_DEFS:
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            kind_here = "Method" if kind == "Function" and m.group(1) else kind
            symbols.append(Symbol(kind_here, m.group(2), m.group(0).strip().rstrip("{:").strip(), line, line))
    symbols.sort(key=lambda s: s.line)
    # Nest indented functions under the class right above them (Python/JS style).
    nested: list[Symbol] = []
    for s in symbols:
        if s.kind == "Method" and nested and nested[-1].kind == "Class":
            nested[-1].children.append(s)
        else:
            nested.append(s)
    imports = [m.group(0).strip() for m in FALLBACK_IMPORT.finditer(text)]
    for block in FALLBACK_GO_BLOCK.finditer(text):
        imports += [l.strip() for l in block.group(1).splitlines() if l.strip()]
    mods = re.findall(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", text, re.M) if language == "rust" else []
    summary = ""
    m = re.match(r'\s*(?:#![^\n]*\n)?\s*("""|\'\'\'|/\*\*?|//+|#)(.*?)(?:\1|\*/|\n\n|\n(?!\s*(?://|#|\*)))', text, re.S)
    if m:
        summary = _clean_doc(m.group(2))
    code_lines = sum(1 for l in text.splitlines() if l.strip() and not l.strip().startswith(("#", "//", "*", "/*")))
    return nested, imports, mods, summary, code_lines, 0


def parse_file(sf: SourceFile) -> FileInfo | None:
    language = detect_language(sf.rel)
    role = classify(sf.rel, language)
    text = read_text(sf.path)
    if text is None:
        return None
    info = FileInfo(rel=sf.rel, language=language or "unknown", role=role, lines=text.count("\n") + 1)
    if role not in ("source", "test"):
        return info

    parsed = _parse_with_tree_sitter(text, language) if tslp is not None else None
    if parsed is None:
        parsed = _parse_with_regex(text, language)
    info.symbols, info.imports, info.module_hints, info.summary, info.code_lines, info.parse_errors = parsed

    info.concepts = concept_lib.detect(language, text)
    if any(s.recursive for s in info.all_symbols):
        info.concepts["recursion"] = sum(1 for s in info.all_symbols if s.recursive)
    stem = posixpath.splitext(posixpath.basename(sf.rel))[0]
    info.is_entry = role == "source" and (bool(ENTRY_CODE_RE.search(text)) or stem in ENTRY_NAMES)
    return info


# ---------------------------------------------------------------------------
# Linking imports to files
# ---------------------------------------------------------------------------

RESOLVE_EXTS = ["", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".php",
                ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".dart", ".vue", ".svelte", ".lua"]
INDEX_FILES = ["/index.ts", "/index.tsx", "/index.js", "/index.jsx", "/__init__.py", "/mod.rs", "/lib.rs", "/main.go"]


class Resolver:
    """Turns import statements into paths of files inside the repository."""

    def __init__(self, files: list[FileInfo]):
        self.paths = {f.rel for f in files if f.role in ("source", "test")}
        self.by_suffix: dict[str, set[str]] = defaultdict(set)
        self.dir_files: dict[str, set[str]] = defaultdict(set)
        for rel in self.paths:
            noext = posixpath.splitext(rel)[0]
            if noext.endswith(("/__init__", "/index", "/mod")):
                noext = noext.rsplit("/", 1)[0]
            parts = noext.split("/")
            for i in range(len(parts)):
                self.by_suffix["/".join(parts[i:])].add(rel)
            self.dir_files[posixpath.dirname(rel)].add(rel)

    def _try_path(self, base: str) -> str | None:
        base = posixpath.normpath(base)
        # TypeScript projects import "./x.js" even though the file on disk is x.ts.
        m = re.match(r"(.*)\.(?:js|jsx|mjs|cjs)$", base)
        if m and base not in self.paths:
            for ext in (".ts", ".tsx", ".mts", ".cts"):
                if m.group(1) + ext in self.paths:
                    return m.group(1) + ext
        for ext in RESOLVE_EXTS:
            if base + ext in self.paths:
                return base + ext
        for idx in INDEX_FILES:
            if base + idx in self.paths:
                return base + idx
        return None

    def _suffix(self, dotted: str, src: str) -> set[str]:
        parts = [p for p in re.split(r"\.|::|/", dotted) if p and p not in ("crate", "self", "super", "*", "@")]
        while parts:
            hits = self.by_suffix.get("/".join(parts))
            if hits:
                hits = hits - {src}
                if len(hits) > 3:  # too ambiguous, prefer files in the same tree
                    top = src.split("/")[0]
                    hits = {h for h in hits if h.split("/")[0] == top} or set()
                if hits:
                    return hits
            parts = parts[:-1]
        return set()

    def candidates(self, statement: str) -> list[str]:
        """Module names mentioned by one import statement."""
        out = re.findall(r"['\"]([^'\"]+)['\"]", statement)
        m = re.match(r"\s*from\s+(\.*[\w.]*)\s+import\s+(.+)", statement, re.S)
        if m:
            mod = m.group(1)
            names = [n.strip().split(" as ")[0] for n in m.group(2).strip("()").split(",")]
            out = [f"{mod}.{n}" if mod.strip(".") else mod + n for n in names if n and n != "*"]
            out.append(mod)
            return out
        m = re.match(r"\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)\s*;?\s*$", statement)
        if m and not out:
            out += [p.strip() for p in m.group(1).split(",")]
        m = re.match(r"\s*(?:pub\s+)?use\s+([\w:]+)", statement)
        if m:
            out.append(m.group(1))
        m = re.match(r"\s*using\s+([\w.]+)\s*;", statement)
        if m:
            out.append(m.group(1))
        return out

    def resolve(self, src: str, statement: str) -> tuple[set[str], list[str]]:
        """Return (internal files, external library names) for one import."""
        internal, external = set(), []
        src_dir = posixpath.dirname(src)
        cands = self.candidates(statement)
        python_from = re.match(r"\s*from\s+\S+\s+import\b", statement) is not None
        for i, cand in enumerate(cands):
            # `from pkg import mod`: the last candidate is the bare package, only use it if nothing else matched.
            if python_from and i == len(cands) - 1 and i > 0 and internal:
                break
            hit = None
            if cand.startswith(("./", "../")) or cand in (".", ".."):
                hit = self._try_path(posixpath.join(src_dir, cand))
                hits = {hit} if hit else set()
            elif re.match(r"^\.+\w", cand) or re.match(r"^\.+$", cand):  # Python relative import
                dots = len(cand) - len(cand.lstrip("."))
                base = src_dir
                for _ in range(dots - 1):
                    base = posixpath.dirname(base)
                rest = cand.lstrip(".").replace(".", "/")
                hit = self._try_path(posixpath.join(base, rest) if rest else base)
                hits = {hit} if hit else set()
            elif cand.startswith("@/") or cand.startswith("~/"):
                hits = self._suffix(cand[2:], src)
            else:
                hits = set()
                if "/" in cand and not cand.startswith("@"):
                    # Go-style package path, or a C include relative to the file.
                    hit = self._try_path(posixpath.join(src_dir, cand))
                    if hit:
                        hits = {hit}
                    else:
                        tail = cand.split("/")
                        for i in range(len(tail)):
                            d = "/".join(tail[i:])
                            if d in self.dir_files:
                                hits = {f for f in self.dir_files[d] if not TEST_RE.search(f)}
                                break
                if not hits:
                    hits = self._suffix(cand, src)
                if not hits and not re.match(r"^(self|super|crate)\b", cand):
                    external.append(_package_name(cand, src))
            internal |= {h for h in hits if h != src}
        return internal, [e for e in external if e]


def _package_name(module: str, src: str = "") -> str:
    module = module.strip()
    if src.endswith(".go"):  # Go: stdlib paths like encoding/json stay whole; modules keep host/user/repo
        parts = module.split("/")
        return "/".join(parts[:3]) if "." in parts[0] else module
    if module.startswith("@") and "/" in module:          # @scope/pkg/sub -> @scope/pkg
        return "/".join(module.split("/")[:2])
    if module.startswith(("node:", "std", "core", "alloc")):
        return module.split(":")[0] if module.startswith("node:") else module.split("::")[0]
    if re.match(r"^[\w-]+\.[a-z]{2,}/", module):           # github.com/user/repo/pkg
        return "/".join(module.split("/")[:3])
    return re.split(r"[./:]", module)[0]


# ---------------------------------------------------------------------------
# Project-level analysis
# ---------------------------------------------------------------------------

def _read_manifests(root: Path, files: list[FileInfo]) -> dict[str, list[str]]:
    manifests: dict[str, list[str]] = {}
    for f in files:
        name = f.rel.rsplit("/", 1)[-1]
        if f.rel.count("/") > 2:
            continue
        path = root / f.rel
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        deps: list[str] = []
        if name == "package.json":
            try:
                data = json.loads(text)
                for key in ("dependencies", "devDependencies"):
                    deps += list((data.get(key) or {}).keys())
            except ValueError:
                pass
        elif name.startswith("requirements") and name.endswith(".txt"):
            deps = [re.split(r"[<>=!~\[; ]", l.strip())[0] for l in text.splitlines() if l.strip() and not l.startswith(("#", "-"))]
        elif name == "pyproject.toml":
            block = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
            if block:
                deps = [re.split(r"[<>=!~\[; ]", d)[0] for d in re.findall(r"['\"]([^'\"]+)['\"]", block.group(1))]
            deps += re.findall(r"^\s*([\w-]+)\s*=\s*[\"{^]", text.split("[tool.poetry.dependencies]")[-1], re.M) if "[tool.poetry.dependencies]" in text else []
        elif name == "Cargo.toml":
            section = re.search(r"\[dependencies\](.*?)(?:\n\[|\Z)", text, re.S)
            if section:
                deps = re.findall(r"^\s*([\w-]+)\s*=", section.group(1), re.M)
        elif name == "go.mod":
            deps = re.findall(r"^\s*([\w.\-]+/[\w.\-/]+)\s+v", text, re.M)
        elif name == "Gemfile":
            deps = re.findall(r"^\s*gem\s+['\"]([^'\"]+)", text, re.M)
        elif name == "composer.json":
            try:
                deps = list((json.loads(text).get("require") or {}).keys())
            except ValueError:
                pass
        else:
            continue
        manifests[f.rel] = [d for d in deps if d and d != "python"]
    return manifests


def _build_order(files: list[FileInfo]) -> list[str]:
    """Order code files so that each file comes after the files it depends on."""
    code = {f.rel: f for f in files if f.role in ("source", "test")}
    deps = {rel: set(f.internal_deps) & code.keys() for rel, f in code.items()}

    def weight(rel: str) -> tuple:
        f = code[rel]
        # Prefer: not a test, not an entry point, fewer lines (easier first), then path.
        return (f.role == "test", f.is_entry, f.code_lines, rel)

    order, done = [], set()
    remaining = set(code)
    while remaining:
        ready = [r for r in remaining if deps[r] <= done]
        if not ready:  # circular imports: pick the file with the fewest unmet dependencies
            ready = [min(remaining, key=lambda r: (len(deps[r] - done), weight(r)))]
        nxt = min(ready, key=weight)
        order.append(nxt)
        done.add(nxt)
        remaining.discard(nxt)
    # Place each test right after the last file it depends on, so you test as you go.
    tests = [r for r in order if code[r].role == "test"]
    order = [r for r in order if code[r].role != "test"]
    for t in tests:
        positions = [order.index(d) for d in deps[t] if d in order]
        order.insert((max(positions) + 1) if positions else len(order), t)
    return order


def analyze(root: Path, log=print) -> Analysis:
    root = Path(root)
    log(f"Scanning {root} ...")
    sources = list_files(root)
    log(f"Found {len(sources)} files. Parsing with {'tree-sitter' if tslp else 'regex fallback'} ...")

    files: list[FileInfo] = []
    skipped: list[str] = []
    code_count = 0
    for i, sf in enumerate(sources, 1):
        if code_count >= MAX_CODE_FILES and classify(sf.rel, detect_language(sf.rel)) in ("source", "test"):
            skipped.append(sf.rel)
            continue
        info = parse_file(sf)
        if info is None:
            continue
        files.append(info)
        if info.role in ("source", "test"):
            code_count += 1
        if i % 100 == 0:
            log(f"  parsed {i}/{len(sources)} files")

    log("Linking imports between files ...")
    resolver = Resolver(files)
    by_rel = {f.rel: f for f in files}
    for f in files:
        if f.role not in ("source", "test"):
            continue
        internal, external = set(), []
        for stmt in f.imports:
            ins, outs = resolver.resolve(f.rel, stmt)
            internal |= ins
            external += outs
        for mod in f.module_hints:  # Rust: `mod foo;` means foo.rs or foo/mod.rs next to this file
            hit = resolver._try_path(posixpath.join(posixpath.dirname(f.rel), mod))
            if hit:
                internal.add(hit)
        f.internal_deps = sorted(internal)
        f.external_deps = sorted(set(external))

    used_by: dict[str, list[str]] = defaultdict(list)
    for f in files:
        for d in f.internal_deps:
            used_by[d].append(f.rel)

    readme = ""
    for f in files:
        if f.role == "docs" and f.rel.lower().startswith("readme"):
            readme = (root / f.rel).read_text(errors="replace")
            break

    concept_files: dict[str, list[str]] = defaultdict(list)
    for f in files:
        for key in f.concepts:
            concept_files[key].append(f.rel)

    languages = Counter()
    for f in files:
        if f.role in ("source", "test", "style"):
            languages[f.language] += max(f.code_lines, 1) if f.role != "style" else f.lines

    entry_points = [f.rel for f in files if f.is_entry and by_rel[f.rel].role == "source"]
    # Entry points nothing else imports are the real "front doors".
    entry_points.sort(key=lambda r: (len(used_by.get(r, [])) > 0, r.count("/"), r))

    log("Working out a build order ...")
    order = _build_order(files)
    history = git_history(root)

    return Analysis(
        root=root, name=root.name, files=files, languages=languages, readme=readme,
        manifests=_read_manifests(root, files), entry_points=entry_points, build_order=order,
        used_by=dict(used_by), concept_files=dict(concept_files), history=history,
        parser="tree-sitter" if tslp else "regex fallback", skipped=skipped,
    )
