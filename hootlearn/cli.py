"""Command-line interface, and the `generate_lesson` pipeline shared with the GUI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ai, levels, report
from .analyzer import analyze
from .repo import resolve_repo


def generate_lesson(target: str, level_key: str = levels.DEFAULT_LEVEL, out: str | Path | None = None,
                    use_ai: bool = False, model: str = ai.DEFAULT_MODEL, max_ai_files: int = 15,
                    api_key: str | None = None, log=print) -> Path:
    """Analyse `target` (folder or git URL) and write a Markdown lesson. Returns the lesson's path."""
    level = levels.get(level_key)
    root = resolve_repo(target, log=log)
    analysis = analyze(root, log=log)
    if not analysis.code_files:
        raise ValueError(f"No source code found in {root}.")
    out_path = Path(out).expanduser() if out else report.default_output_path(analysis, level)
    if out_path.is_dir() or str(out).endswith(("/", "\\")) or (out and not out_path.suffix):
        out_path = report.default_output_path(analysis, level, out_path)

    overview, file_texts, notes = None, {}, []
    if use_ai:
        try:
            tutor = ai.Tutor(level, model=model, api_key=api_key, log=log)
            overview = tutor.overview(analysis)
            chosen = ai.pick_files(analysis, max_ai_files)
            log(f"AI: explaining {len(chosen)} file(s) with {model} ...")
            file_texts = tutor.file_lessons(analysis, chosen)
            notes = tutor.notes
            skipped = len([r for r in analysis.build_order if analysis.file(r).role == "source"]) - len(chosen)
            if skipped > 0:
                notes.append(f"{skipped} smaller or less central files have no AI explanation "
                             f"(the limit was {max_ai_files}); they use the static instructions instead.")
        except ai.AIUnavailable as e:
            log(f"AI explanations unavailable: {e}")
            log("Continuing with static analysis only.")
            notes = [f"AI explanations were requested but unavailable: {e}"]
            overview, file_texts = None, {}

    log("Writing the lesson ...")
    text = report.build_markdown(analysis, level, out_path, ai_overview=overview, ai_files=file_texts,
                                 ai_notes=notes, ai_model=model if use_ai else None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    log(f"Done! Lesson saved to {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hootlearn",
        description="Analyse a git repository and write a Markdown lesson that teaches you to rebuild it.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("analyze", help="analyse a repository and write a lesson")
    p.add_argument("repo", help="path to a local folder, or a git URL to clone")
    p.add_argument("-o", "--out", help="output .md file or folder (default: ./lessons/<name>-<level>.md)")
    p.add_argument("-l", "--level", choices=levels.LEVEL_KEYS, default=levels.DEFAULT_LEVEL,
                   help="your skill level (default: %(default)s)")
    p.add_argument("--ai", action="store_true", help="add explanations written by Claude (needs an API key)")
    p.add_argument("--model", default=ai.DEFAULT_MODEL, help="Claude model for --ai (default: %(default)s)")
    p.add_argument("--max-ai-files", type=int, default=15,
                   help="at most this many files get an AI explanation, to keep costs down (default: %(default)s)")

    g = sub.add_parser("gui", help="open the graphical interface")
    g.add_argument("file", nargs="?", help="a Markdown file to open")

    args = parser.parse_args(argv)
    if args.command in (None, "gui"):
        from .gui import run_gui
        run_gui(getattr(args, "file", None))
        return 0

    try:
        generate_lesson(args.repo, args.level, args.out, args.ai, args.model, args.max_ai_files)
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0
