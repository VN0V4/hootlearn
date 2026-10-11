"""Turn an Analysis (plus optional AI text) into a Markdown lesson."""

from __future__ import annotations

import os
import posixpath
import re
from collections import Counter
from datetime import date
from pathlib import Path

from .analyzer import Analysis, FileInfo, Symbol, language_name
from .concepts import CONCEPTS_BY_KEY
from .levels import CONCEPT_NOTES, PRIMER, Level

MAX_STEPS = 80          # longer projects get the remaining files listed briefly
MAX_TREE_ENTRIES = 120

# One-line descriptions of popular libraries, so learners know what they are looking at.
KNOWN_LIBRARIES = {
    "anthropic": "official SDK for calling Claude models", "openai": "SDK for OpenAI models",
    "requests": "simple HTTP requests", "httpx": "HTTP requests, sync and async", "aiohttp": "async HTTP client/server",
    "flask": "small web framework", "fastapi": "web API framework built on type hints", "django": "full-featured web framework",
    "pydantic": "data validation using type hints", "sqlalchemy": "database toolkit / ORM", "click": "command-line interfaces",
    "typer": "command-line interfaces from type hints", "rich": "pretty terminal output", "numpy": "fast numeric arrays",
    "pandas": "tables of data (DataFrames)", "matplotlib": "charts and plots", "pytest": "testing framework",
    "tkinter": "built-in desktop GUI toolkit", "argparse": "built-in command-line argument parsing",
    "asyncio": "built-in async/await support", "pathlib": "built-in file path handling", "json": "built-in JSON reading/writing",
    "re": "built-in regular expressions", "os": "built-in operating-system access", "sys": "built-in interpreter access",
    "subprocess": "built-in way to run other programs", "dataclasses": "built-in simple data classes",
    "typing": "built-in type-hint helpers", "logging": "built-in logging", "collections": "built-in extra container types",
    "itertools": "built-in iteration helpers", "functools": "built-in function helpers", "sqlite3": "built-in SQLite database",
    "react": "UI library for building interfaces from components", "react-dom": "renders React in the browser",
    "next": "React framework with routing and server rendering", "vue": "UI framework", "svelte": "UI compiler/framework",
    "express": "minimal Node.js web server", "axios": "HTTP requests", "zod": "schema validation for TypeScript",
    "typescript": "typed superset of JavaScript", "vite": "fast dev server and bundler", "webpack": "bundler",
    "jest": "testing framework", "vitest": "testing framework for Vite", "eslint": "code linter", "prettier": "code formatter",
    "tailwindcss": "utility-first CSS framework", "lodash": "utility functions", "fs": "built-in Node file system access",
    "path": "built-in Node path helpers", "node": "built-in Node.js modules", "dotenv": "loads settings from a .env file",
    "prisma": "database ORM", "mongoose": "MongoDB object modelling", "socket.io": "real-time websockets",
    "std": "the language's standard library", "serde": "serialisation (JSON etc.) for Rust", "tokio": "async runtime for Rust",
    "clap": "command-line parsing for Rust", "anyhow": "easy error handling for Rust", "thiserror": "custom error types for Rust",
    "reqwest": "HTTP client for Rust", "axum": "web framework for Rust", "fmt": "Go's built-in formatting/printing",
    "net": "Go's built-in networking", "github.com/spf13/cobra": "command-line apps in Go",
    "github.com/gin-gonic/gin": "web framework for Go",
}

COMMENT = {"python": "#", "ruby": "#", "bash": "#", "r": "#", "elixir": "#", "julia": "#", "nix": "#",
           "lua": "--", "haskell": "--", "sql": "--"}

SETUP = {
    "python": "Create a folder and a virtual environment: `python -m venv .venv`, activate it "
              "(`source .venv/bin/activate`, or `.venv\\Scripts\\activate` on Windows), then `pip install` the "
              "libraries listed below as you need them.",
    "javascript": "Install Node.js, then in an empty folder run `npm init -y` and `npm install` the libraries below as you need them.",
    "typescript": "Install Node.js, run `npm init -y`, then `npm install --save-dev typescript` and `npx tsc --init`.",
    "tsx": "The quickest start is `npm create vite@latest` and choosing React + TypeScript.",
    "go": "Install Go, then in an empty folder run `go mod init example.com/yourname/project`.",
    "rust": "Install Rust with rustup, then run `cargo new project` and add libraries with `cargo add <name>`.",
    "java": "Install a JDK and use Gradle (`gradle init`) or Maven to create a project.",
    "csharp": "Install the .NET SDK and run `dotnet new console`.",
    "ruby": "Install Ruby and Bundler; create a `Gemfile` and run `bundle install`.",
    "c": "Install a compiler (gcc or clang). Compile with `gcc file.c -o program`.",
    "cpp": "Install a compiler (g++ or clang++). Larger projects use CMake.",
}


def _anchor(text: str) -> str:
    return re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")


def _link(a: Analysis, rel: str, out_dir: Path, line: int | None = None) -> str:
    target = os.path.relpath(a.root / rel, out_dir).replace(os.sep, "/")
    if target.startswith("../../"):  # far away: an absolute path is easier to read
        target = (a.root / rel).resolve().as_posix()
    label = f"{rel}:{line}" if line else rel
    return f"[`{label}`](<{target}{'#L' + str(line) if line else ''}>)"


def _symbol_counts(f: FileInfo) -> str:
    counts = Counter(s.kind.lower() for s in f.all_symbols)
    if not counts:
        return "no named functions or classes (mostly top-level code)"
    parts = []
    for kind, n in counts.most_common():
        word = {"class": "class", "function": "function", "method": "method", "struct": "struct", "impl": "impl block",
                "interface": "interface", "trait": "trait", "enum": "enum", "module": "module"}.get(kind, kind)
        plural = "es" if word.endswith(("s", "sh", "ch")) else "s"
        parts.append(f"{n} {word}{plural if n != 1 else ''}")
    return ", ".join(parts)


def _skeleton(f: FileInfo) -> str:
    """A code outline: every signature, bodies left for the learner to write."""
    lang = f.language
    out: list[str] = []
    cmt = COMMENT.get(lang, "//")

    def emit(sym: Symbol, indent: str):
        sig = sym.signature.splitlines()[0].rstrip(" {:") if sym.signature else sym.name
        if lang in ("python", "typescript", "tsx", "java", "kotlin", "csharp", "dart"):
            out.extend(indent + (d if d.startswith(("@", "[")) else "@" + d) for d in sym.decorators)
        if lang == "python":
            out.append(f"{indent}{sig}:")
            if sym.doc:
                out.append(f'{indent}    """{sym.doc}"""')
            if sym.children:
                out.append("")
                for c in sym.children:
                    emit(c, indent + "    ")
            else:
                out.append(f"{indent}    ...  # TODO: write this")
            out.append("")
        elif lang in ("ruby", "elixir", "lua"):
            out.append(f"{indent}{sig}")
            if sym.doc:
                out.append(f"{indent}  {cmt} {sym.doc}")
            for c in sym.children:
                emit(c, indent + "  ")
            if not sym.children:
                out.append(f"{indent}  {cmt} TODO")
            out.append(f"{indent}end")
        else:
            if sym.doc:
                out.append(f"{indent}{cmt} {sym.doc}")
            out.append(f"{indent}{sig} {{")
            for c in sym.children:
                emit(c, indent + "    ")
            if not sym.children:
                out.append(f"{indent}    {cmt} TODO")
            out.append(f"{indent}}}")
            out.append("")

    for sym in f.symbols:
        emit(sym, "")
    return "\n".join(out).rstrip()


def _tree(a: Analysis) -> str:
    rels = sorted(f.rel for f in a.files if f.role in ("source", "test", "config", "docs", "style"))
    shown = rels[:MAX_TREE_ENTRIES]
    lines, seen_dirs = [f"{a.name}/"], set()
    for rel in shown:
        parts = rel.split("/")
        for depth in range(len(parts) - 1):
            d = "/".join(parts[: depth + 1])
            if d not in seen_dirs:
                seen_dirs.add(d)
                lines.append("    " * (depth + 1) + parts[depth] + "/")
        f = a.file(rel)
        note = {"test": "  (tests)", "config": "  (config)", "docs": "  (docs)"}.get(f.role, "")
        if rel in a.entry_points[:5]:
            note = "  <- start here (entry point)"
        lines.append("    " * len(parts) + parts[-1] + note)
    if len(rels) > len(shown):
        lines.append(f"    ... and {len(rels) - len(shown)} more files")
    return "\n".join(lines)


def build_markdown(a: Analysis, level: Level, out_path: Path, ai_overview: str | None = None,
                   ai_files: dict[str, str] | None = None, ai_notes: list[str] | None = None,
                   ai_model: str | None = None) -> str:
    ai_files = ai_files or {}
    out_dir = out_path.parent.resolve()
    md: list[str] = []
    w = md.append

    code_files = a.code_files
    total_lines = sum(f.code_lines for f in code_files)
    main_langs = [l for l, _ in a.languages.most_common() if l not in ("html", "css", "scss")][:3]

    # ---- title ------------------------------------------------------------
    w(f"# Learn to build: {a.name}\n")
    ai_part = f"AI explanations by `{ai_model}`" if ai_model and (ai_overview or ai_files) else "static analysis only (no AI)"
    w(f"> Skill level: **{level.label}** · generated {date.today().isoformat()} · parser: {a.parser} · {ai_part}  \n"
      f"> Source: `{a.root}`\n")

    sections = ["What is this project?", "Tools you'll need", "Map of the project", "Concepts you'll practise",
                "Rebuild it step by step", "How the original was built", "Where to go next"]
    if level.show_primer:
        sections.insert(0, "Coding basics first")
    w("## Contents\n")
    for i, s in enumerate(sections, 1):
        w(f"{i}. [{s}](#{_anchor(s)})")
    w("")

    w("**Who this is for:** " + level.who + "\n")
    w({
        "guided": "For every step: read the goal, try writing the file yourself in a fresh folder, and only open "
                  "the original when you are stuck or finished. Comparing your version with the original is where most of the learning happens.",
        "independent": "Each step gives you the goal and the shape of the file. Try to design the details "
                       "yourself, then compare with the original and note where (and why) it differs.",
        "challenge": "Steps only state responsibilities. Rebuild each part from the description, then diff your "
                     "design against the original and judge which trade-offs you prefer.",
    }[level.exercise_style] + "\n")

    if level.show_primer:
        w("## Coding basics first\n")
        w(PRIMER)

    # ---- 1. overview -------------------------------------------------------
    w("## What is this project?\n")
    if a.readme:
        intro = _readme_intro(a.readme)
        if intro:
            w("From the project's README:\n")
            w("\n".join("> " + l if l.strip() else ">" for l in intro.splitlines()) + "\n")
    else:
        w("The project has no README, so its purpose has to be worked out from the code.\n")
    if ai_overview:
        w("### The big picture (AI explanation)\n")
        w(ai_overview + "\n")

    w("### At a glance\n")
    w("| | |\n|---|---|")
    w(f"| Main language(s) | {', '.join(language_name(l) for l in main_langs) or 'unknown'} |")
    w(f"| Code files | {sum(1 for f in code_files if f.role == 'source')} source, {sum(1 for f in code_files if f.role == 'test')} test |")
    w(f"| Lines of code | about {total_lines:,} |")
    if a.entry_points:
        w(f"| Where it starts | {', '.join(_link(a, e, out_dir) for e in a.entry_points[:3])} |")
    if a.history:
        w(f"| Git commits | {a.history.get('total_commits', 0)} |")
    w(f"| Difficulty to rebuild | {_difficulty(total_lines, len(code_files))} |")
    w("")

    # ---- 2. tools ------------------------------------------------------------
    w("## Tools you'll need\n")
    if main_langs:
        w("**Languages:** " + ", ".join(f"{language_name(l)} ({n:,} lines)" for l, n in a.languages.most_common(6)) + "\n")
    for lang in main_langs:
        if lang in SETUP:
            w(f"- **Setting up {language_name(lang)}:** {SETUP[lang]}")
    w("")
    declared = sorted({d for deps in a.manifests.values() for d in deps})
    used = Counter(d for f in code_files for d in f.external_deps)
    if declared:
        w("**Libraries this project installs** (from " + ", ".join(f"`{m}`" for m in a.manifests) + "):\n")
        for d in declared[:60]:
            desc = KNOWN_LIBRARIES.get(d.lower())
            w(f"- `{d}`" + (f": {desc}" if desc else ""))
        if len(declared) > 60:
            w(f"- ... and {len(declared) - 60} more")
        w("")
    if used:
        w("**Most-imported modules and libraries** (including the language's built-in ones):\n")
        for name, n in used.most_common(15):
            desc = KNOWN_LIBRARIES.get(name.lower())
            w(f"- `{name}`: imported in {n} file{'s' if n != 1 else ''}" + (f", {desc}" if desc else ""))
        w("")
        if level.hints == "detailed":
            w("*Tip: when you meet a library you don't know, search for \"<name> quickstart\" and do its first "
              "example before continuing. Built-in ones are documented in the language's official docs.*\n")

    # ---- 3. map ----------------------------------------------------------------
    w("## Map of the project\n")
    w("```text\n" + _tree(a) + "\n```\n")
    core = sorted(a.used_by.items(), key=lambda kv: -len(kv[1]))
    core = [(rel, users) for rel, users in core if a.file(rel).role == "source"][:8]
    if core:
        w("### The core files (used by many others)\n")
        if level.hints == "detailed":
            w("These are the foundations: other files import them, so they get built early.\n")
        for rel, users in core:
            f = a.file(rel)
            w(f"- {_link(a, rel, out_dir)}: used by {len(users)} file{'s' if len(users) != 1 else ''}"
              + (f". {f.summary}" if f.summary else ""))
        w("")
    links = [(f.rel, f.internal_deps) for f in code_files if f.internal_deps and f.role == "source"]
    if links:
        w("### How the files connect\n")
        w("Each file, and the other files in this project it imports:\n")
        w("```text")
        for rel, deps in links[:60]:
            w(f"{rel}\n    uses: {', '.join(deps)}")
        if len(links) > 60:
            w(f"... and {len(links) - 60} more")
        w("```\n")

    # ---- 4. concepts ------------------------------------------------------------
    w("## Concepts you'll practise\n")
    ranked = sorted(a.concept_files.items(), key=lambda kv: -len(kv[1]))
    if not ranked:
        w("No specific techniques were detected. This project sticks to the basics.\n")
    else:
        w("These programming techniques appear in the code, most widespread first. Learn the ones you don't "
          "know yet *before* the steps that use them.\n")
    for key, rels in ranked:
        c = CONCEPTS_BY_KEY.get(key)
        if not c:
            continue
        analogy, deeper = CONCEPT_NOTES.get(key, ("", ""))
        w(f"### {c.title}\n")
        w(c.explain + "\n")
        if level.show_analogies and analogy:
            w(f"*Think of it like this:* {analogy}\n")
        if level.show_deeper and deeper:
            w(f"**Look closer:** {deeper}\n")
        shown = ", ".join(_link(a, r, out_dir) for r in rels[:5])
        w(f"Used in {len(rels)} file{'s' if len(rels) != 1 else ''}: {shown}{' ...' if len(rels) > 5 else ''}\n")
        if level.exercise_style != "challenge":
            w(f"**Practice:** {c.practice}\n")

    # ---- 5. steps ---------------------------------------------------------------
    w("## Rebuild it step by step\n")
    w("The files are ordered so that **every file only depends on files from earlier steps**. Tests come "
      "right after the code they check, so you can test as you go.\n")
    w("### Step 0: Set up the project\n")
    for lang in main_langs[:1]:
        if lang in SETUP:
            w(SETUP[lang] + "\n")
    configs = [f for f in a.files if f.role == "config" and f.rel.count("/") == 0]
    if configs:
        w("Project-level configuration files in the original: " + ", ".join(_link(a, f.rel, out_dir) for f in configs[:10])
          + ". Create these as you need them, rather than all up front.\n")
    if level.hints == "detailed":
        w("Use version control from the start: `git init`, then `git commit` after each step. If you break "
          "something you can always go back.\n")

    for n, rel in enumerate(a.build_order[:MAX_STEPS], 1):
        _write_step(w, a, level, rel, n, out_dir, ai_files.get(rel))

    rest = a.build_order[MAX_STEPS:]
    if rest:
        w(f"### Remaining files ({len(rest)})\n")
        w("The project is large, so the remaining files are listed without full steps, in build order:\n")
        for rel in rest:
            w(f"- {_link(a, rel, out_dir)}: {_symbol_counts(a.file(rel))}")
        w("")

    # ---- 6. history -------------------------------------------------------------
    w("## How the original was built\n")
    commits = (a.history or {}).get("commits_adding_files", [])
    if commits:
        w("Git history shows the order in which files were *actually* added. Projects written with an AI "
          "assistant often appear in big chunks; compare it with the dependency-based order above.\n")
        w("| Date | Commit | Message | Files added |\n|---|---|---|---|")
        for c in commits[:30]:
            added = [x for x in c["added"] if x in {f.rel for f in a.files}]
            files = ", ".join(f"`{x}`" for x in added[:4]) + (f" +{len(added) - 4} more" if len(added) > 4 else "")
            msg = c["subject"].replace("|", "\\|")[:70]
            w(f"| {c['date']} | `{c['sha']}` | {msg} | {files or '-'} |")
        if len(commits) > 30:
            w(f"\n*... {len(commits) - 30} more commits that add files.*")
        w("")
    else:
        w("No git history is available for this folder.\n")

    # ---- 7. next ----------------------------------------------------------------
    w("## Where to go next\n")
    untested = [f.rel for f in code_files if f.role == "source" and not any(
        f.rel in a.file(t).internal_deps for t in (x.rel for x in code_files if x.role == "test"))]
    tips = {
        "guided": [
            "Run your finished version and the original side by side with the same inputs. Do they behave the same?",
            "Change one small thing in your version (a message, a default setting) and predict what will happen before running it.",
            "Explain one file out loud, line by line, as if teaching a friend. Wherever you get stuck, that's what to study next.",
        ],
        "independent": [
            "Add a small feature the original doesn't have, without breaking existing tests.",
            "Write tests for files that don't have any yet.",
            "Find one function that does too much and split it into smaller ones.",
        ],
        "challenge": [
            "Rebuild a core module with a different design (e.g. different data structures or concurrency model) and compare.",
            "Review the codebase as if it were a pull request from an AI assistant: list bugs, risky assumptions and missing tests.",
            "Profile the slowest path and optimise it, measuring before and after.",
        ],
    }[level.exercise_style]
    for t in tips:
        w(f"- {t}")
    if untested and any(f.role == "test" for f in code_files):
        w(f"- These files have no tests that import them directly: {', '.join(f'`{u}`' for u in untested[:8])}"
          f"{' ...' if len(untested) > 8 else ''}. Writing some is great practice.")
    w("")

    if a.skipped or ai_notes:
        w("---\n")
        w("**Notes about this lesson**\n")
        if a.skipped:
            w(f"- {len(a.skipped)} files were not analysed because the project is very large.")
        for note in ai_notes or []:
            w(f"- {note}")
        w("")
    return "\n".join(md)


def _difficulty(lines: int, files: int) -> str:
    if lines < 300:
        return "small: a good weekend project"
    if lines < 2000:
        return "medium: a few weeks of practice"
    if lines < 10000:
        return "large: pick one part to rebuild first"
    return "very large: rebuild a single feature or module, not the whole thing"


def _readme_intro(readme: str) -> str:
    """First real paragraphs of a README, without badges, HTML or headings."""
    text = re.sub(r"<!--.*?-->", "", readme, flags=re.S)
    paras, current = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("```", "<", "[![", "![")) or re.fullmatch(r"[=\-]{3,}", s):
            if current:
                paras.append(" ".join(current))
                current = []
            continue
        if s.startswith("#"):
            if paras or current:
                if current:
                    paras.append(" ".join(current))
                break
            continue
        if not s:
            if current:
                paras.append(" ".join(current))
                current = []
            continue
        current.append(s)
    if current:
        paras.append(" ".join(current))
    intro = "\n\n".join(p for p in paras if len(p) > 20)[:1200]
    return intro


def _write_step(w, a: Analysis, level: Level, rel: str, n: int, out_dir: Path, ai_text: str | None):
    f = a.file(rel)
    kind = "Tests" if f.role == "test" else ("Entry point" if f.is_entry else "File")
    w(f"### Step {n}: `{rel}`\n")
    meta = f"*{kind} · {language_name(f.language)} · {f.code_lines} lines of code · {_symbol_counts(f)}*"
    w(meta + "\n")

    if f.summary:
        w(f"**Goal:** {f.summary}\n")
    if f.internal_deps:
        prev = ", ".join(f"`{d}`" for d in f.internal_deps)
        w(f"**Builds on:** {prev}" + (" (from earlier steps)" if level.hints != "minimal" else "") + "\n")
    users = a.used_by.get(rel, [])
    if users and level.hints != "minimal":
        w(f"**Later used by:** {', '.join(f'`{u}`' for u in users[:6])}{' ...' if len(users) > 6 else ''}\n")

    if f.concepts:
        names = [CONCEPTS_BY_KEY[k].title for k in sorted(f.concepts, key=lambda k: -f.concepts[k]) if k in CONCEPTS_BY_KEY]
        w("**Concepts here:** " + ", ".join(names[:6]) + "\n")

    if ai_text:
        w(ai_text + "\n")
    else:
        _static_instructions(w, a, level, f)

    if level.signatures == "full" and f.symbols:
        w("<details><summary>Skeleton to fill in (signatures only)</summary>\n")
        w(f"```{f.language}\n{_skeleton(f)}\n```\n")
        w("</details>\n")
    elif level.signatures == "names" and f.symbols:
        w("**What it defines:**\n")
        for s in f.symbols[:25]:
            w(f"- {s.kind.lower()} `{s.name}`" + (f": {s.doc}" if s.doc else ""))
            for c in s.children[:12]:
                w(f"    - {c.kind.lower()} `{c.name}`" + (f": {c.doc}" if c.doc else ""))
        w("")

    w(_checkpoint(a, level, f) + "\n")
    w(f"Compare with the original: {_link(a, rel, out_dir)}\n")


def _static_instructions(w, a: Analysis, level: Level, f: FileInfo):
    """Rebuild instructions generated without AI."""
    if level.hints == "minimal":
        public = [s.name for s in f.symbols if not s.name.startswith("_")][:10]
        if public:
            w(f"**Responsibilities:** provide {', '.join(f'`{p}`' for p in public)}"
              + (" and more." if len(f.symbols) > 10 else ".") + " Decide the signatures yourself.\n")
        return

    steps = []
    externals = [e for e in f.external_deps][:8]
    if f.imports:
        if externals:
            steps.append("Start with the imports. This file uses: " + ", ".join(f"`{e}`" for e in externals)
                         + (" plus files from earlier steps." if f.internal_deps else "."))
        elif f.internal_deps:
            steps.append("Start by importing what you need from the earlier steps.")

    order = sorted(f.symbols, key=lambda s: s.line)
    data_kinds = {"Class", "Struct", "Enum", "Interface", "Trait"}
    types_first = [s for s in order if s.kind in data_kinds]
    funcs = [s for s in order if s.kind not in data_kinds]
    if types_first:
        steps.append("Define the data types first, because the functions work with them: "
                     + ", ".join(f"`{s.name}`" for s in types_first[:8]) + ".")
        if level.hints == "detailed":
            for s in types_first[:5]:
                if s.children:
                    steps.append(f"Inside `{s.name}`, add its methods one at a time: "
                                 + ", ".join(f"`{c.name}`" for c in s.children[:10])
                                 + ". Test each one before writing the next.")
    if funcs:
        helpers = [s for s in funcs if s.name.startswith("_")]
        public = [s for s in funcs if not s.name.startswith("_")]
        if helpers and level.hints == "detailed":
            steps.append("Write the small helper functions next (names starting with `_` are private helpers): "
                         + ", ".join(f"`{s.name}`" for s in helpers[:8]) + ".")
        if public:
            steps.append("Then the main functions: " + ", ".join(f"`{s.name}`" for s in public[:10])
                         + (" and more." if len(public) > 10 else "."))
    recursive = [s.name for s in f.all_symbols if s.recursive]
    if recursive:
        steps.append("Watch out: " + ", ".join(f"`{r}`" for r in recursive) + " call themselves (recursion), "
                     "so think about when they should stop.")
    if not f.symbols:
        steps.append("This file is mostly top-level code that runs straight away. Read it top to bottom and "
                     "rewrite it in the same order.")

    documented = [s for s in f.all_symbols if s.doc][:8]
    if documented and level.hints == "detailed":
        steps.append("What some of the pieces are for, according to the original's own comments:\n"
                     + "\n".join(f"    - `{s.name}`: {s.doc}" for s in documented))
    if steps:
        w("**Your turn:**\n")
        for i, s in enumerate(steps, 1):
            w(f"{i}. {s}")
        w("")


def _checkpoint(a: Analysis, level: Level, f: FileInfo) -> str:
    lang = f.language
    if f.role == "test":
        cmd = {"python": f"pytest {f.rel}", "go": "go test ./...", "rust": "cargo test",
               "javascript": "npm test", "typescript": "npm test", "tsx": "npm test"}.get(lang, "your project's test command")
        return f"**Checkpoint:** run `{cmd}`. Your code from the earlier steps should pass these tests."
    if f.is_entry:
        cmd = {"python": f"python {f.rel}", "go": "go run .", "rust": "cargo run", "javascript": f"node {f.rel}"}.get(lang)
        return ("**Checkpoint:** this is a starting point of the program, so try running it"
                + (f" (`{cmd}`)" if cmd else "") + ". Compare its behaviour with the original.")
    if level.hints == "minimal":
        return "**Checkpoint:** write a quick test that pins down this file's behaviour."
    if lang == "python":
        mod = re.sub(r"^(src|lib)/", "", posixpath.splitext(f.rel)[0]).replace("/", ".").removesuffix(".__init__")
        return (f"**Checkpoint:** start `python` in your project folder, run `import {mod}`, and call one of its "
                "functions with simple inputs to see that it works.")
    return "**Checkpoint:** make sure it compiles/loads, then call one of its functions from a small test or scratch file."


def default_output_path(a: Analysis, level: Level, base: Path | None = None) -> Path:
    base = base or Path.cwd() / "lessons"
    return base / f"{a.name}-{level.key}.md"
