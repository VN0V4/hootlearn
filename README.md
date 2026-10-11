# HootLearn

Point it at any git repository (a local folder or a URL), including code written by AI assistants, and it
writes a **Markdown lesson that teaches you how to rebuild that project yourself**, pitched at your skill level.
It comes with a desktop GUI that also works as a general Markdown reader.

## What a lesson contains

- **What the project is**: from the README, plus an AI-written overview if you turn AI on.
- **Tools you'll need**: languages, how to set them up, and the libraries used, with short descriptions.
- **Map of the project**: a folder tree, entry points, the core files, and which files import which.
- **Concepts you'll practise**: techniques found in the code (async, classes, decorators, error handling,
  recursion, HTTP, testing and about 20 more), each explained with a practice exercise.
- **Rebuild it step by step**: every code file in *dependency order*, so each step only uses things you have
  already built. Tests come right after the code they check. Each step has a goal, hints, a code skeleton,
  a checkpoint and a link to the original.
- **How the original was built**: the order files were really added, from git history.
- **Where to go next**: follow-up challenges.

## Skill levels

| Level | You get |
|---|---|
| Beginner | A coding-basics primer, everyday analogies, detailed hints, full code skeletons |
| Some basics | Analogies, hints, full code skeletons |
| Intermediate | Design notes, names of what to build (you design the signatures) |
| Advanced | Responsibilities only, trade-offs and pitfalls, open-ended challenges |

## Setup

```bash
# NixOS (provides Python with tkinter, creates .venv automatically):
nix-shell

# Elsewhere (tkinter usually ships with Python; on Debian/Ubuntu: sudo apt install python3-tk):
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Both dependencies are optional. Without `tree-sitter-language-pack` a simpler regex parser is used. Without
`anthropic`, AI explanations are unavailable.

## Usage

```bash
python learn.py                       # open the GUI
python learn.py some-file.md          # read any Markdown file in the GUI

# command line
python learn.py analyze ~/code/some-project --level beginner
python learn.py analyze https://github.com/user/repo -l intermediate -o lessons/
python learn.py analyze . --ai --max-ai-files 10        # add Claude explanations
```

Lessons are saved to `./lessons/` from the command line, or `~/hootlearn-lessons/` from the GUI (you can
change this). Repositories cloned from a URL are cached in `~/.cache/hootlearn/repos/`. Analysis only reads
the code and never runs it.

## AI explanations (optional)

With `--ai` (or the checkbox in the GUI), Claude writes a project overview and a walkthrough with rebuild
exercises for the most important files (15 by default, chosen by importance). Set `ANTHROPIC_API_KEY`, or paste
a key into the GUI (it is not saved). The default model is `claude-opus-5-5`. Sonnet 5.5 and Haiku 5.5 are
cheaper options. If anything goes wrong with the API, the lesson is still written from static analysis.

## GUI tips

- Click file links in a lesson to view the source with the line highlighted. Back/Forward work like a browser.
- **Contents** tab: jump to any heading. **Lessons** tab: every lesson in your output folder.
- Ctrl+F find, Ctrl+D dark mode, Ctrl+plus/minus text size, F5 reload.
