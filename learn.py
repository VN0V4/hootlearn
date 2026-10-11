#!/usr/bin/env python3
"""Launcher for HootLearn.

    python learn.py                      open the GUI
    python learn.py lesson.md            open a Markdown file in the GUI
    python learn.py analyze <repo> ...   generate a lesson from the command line
"""

import sys

from hootlearn.cli import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and args[0].lower().endswith((".md", ".markdown")):
        args = ["gui", args[0]]
    sys.exit(main(args))
