"""Skill levels: how much the lesson explains and how much it gives away."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    key: str
    label: str
    who: str                 # who this level is for
    show_primer: bool        # include the "coding basics" primer
    show_analogies: bool     # everyday comparisons for each concept
    show_deeper: bool        # design trade-offs and pitfalls for each concept
    signatures: str          # "full" | "names" | "none": how much of each step's code shape to reveal
    hints: str               # "detailed" | "some" | "minimal"
    exercise_style: str      # how the "your turn" tasks are phrased
    ai_guidance: str         # tells the AI how to pitch its explanations


LEVELS: dict[str, Level] = {
    "beginner": Level(
        "beginner", "Beginner",
        "You are new to programming, or have only followed a tutorial or two.",
        show_primer=True, show_analogies=True, show_deeper=False, signatures="full", hints="detailed",
        exercise_style="guided",
        ai_guidance=(
            "The reader is a complete beginner. Define every technical term the first time you use it, use "
            "everyday analogies, keep sentences short, and explain what each important line does. Never assume "
            "they know what a function, import, class or return value is: explain it in passing. Break each "
            "rebuild task into very small steps, each one runnable on its own."
        ),
    ),
    "basics": Level(
        "basics", "Some basics",
        "You know variables, loops, if-statements and functions, and want to learn how real projects are built.",
        show_primer=False, show_analogies=True, show_deeper=False, signatures="full", hints="some",
        exercise_style="guided",
        ai_guidance=(
            "The reader knows variables, loops, conditionals and functions, but not much more. Explain anything "
            "beyond that (classes, decorators, async, generics, closures, frameworks) briefly when it appears. "
            "Focus on how the pieces fit together and why the code is structured this way. Give step-by-step "
            "rebuild tasks with hints, not full solutions."
        ),
    ),
    "intermediate": Level(
        "intermediate", "Intermediate",
        "You have written a few programs of your own and want to understand architecture and good habits.",
        show_primer=False, show_analogies=False, show_deeper=True, signatures="names", hints="some",
        exercise_style="independent",
        ai_guidance=(
            "The reader is an intermediate programmer. Skip basic syntax. Focus on architecture, responsibilities "
            "of each module, data flow, design patterns, error handling strategy and idioms specific to this "
            "language. Point out good practices and anything you would do differently. Rebuild tasks should "
            "describe goals and constraints rather than step-by-step instructions."
        ),
    ),
    "advanced": Level(
        "advanced", "Advanced",
        "You are comfortable building projects and want to study design decisions and trade-offs.",
        show_primer=False, show_analogies=False, show_deeper=True, signatures="none", hints="minimal",
        exercise_style="challenge",
        ai_guidance=(
            "The reader is an experienced programmer. Be concise and technical. Concentrate on design decisions, "
            "trade-offs, alternatives that were not taken, performance and correctness risks, testability and "
            "what an LLM-generated codebase might have got subtly wrong. Rebuild tasks should be open-ended "
            "challenges (e.g. rebuild from the spec alone, then compare; or redesign one part)."
        ),
    ),
}

DEFAULT_LEVEL = "basics"
LEVEL_KEYS = list(LEVELS)


def get(key: str | None) -> Level:
    return LEVELS.get((key or DEFAULT_LEVEL).lower(), LEVELS[DEFAULT_LEVEL])


# A short primer on the absolute basics, only shown to beginners.
PRIMER = """\
Before diving in, here are the few ideas every program in this repository is built from.

- **File / module**: a program is usually split into many files. Each file groups related code together, like
  chapters in a book.
- **Variable**: a name that holds a value, e.g. `age = 12`. Think of it as a labelled box.
- **Function**: a named, reusable recipe. You give it inputs (*parameters*), it does some work and can hand back
  an output (*return value*). `def add(a, b): return a + b` in Python, `function add(a, b) { return a + b }` in
  JavaScript.
- **Import**: borrowing code from another file or from a library someone else wrote, so you don't have to
  write everything yourself.
- **Library / package / dependency**: code written by other people that a project downloads and uses.
- **Class**: a blueprint that bundles data and the functions that work on it (more on this below).
- **Entry point**: the file you actually run. It starts the program and calls everything else.
- **Running code**: for Python, `python file.py`. For JavaScript, `node file.js`. Other languages first
  *compile* the code into a program, then run it (`go run .`, `cargo run`).

**How to use this lesson:** don't just read it. Make a new empty folder, and for each step, try to write
the file yourself *before* looking at the original. Getting stuck is normal; that's when you learn the most.
Peek at the real file, understand the part you were missing, then close it and keep going.
"""

# Extra notes per concept: (everyday analogy for newer learners, deeper notes for experienced ones).
CONCEPT_NOTES: dict[str, tuple[str, str]] = {
    "classes": (
        "A class is like a cookie cutter, and each object is a cookie made with it.",
        "Watch for classes that are only a bag of functions (a module would do) and for deep hierarchies. "
        "Prefer composition (objects holding other objects) over inheritance when behaviour varies.",
    ),
    "inheritance": (
        "Like a 'vehicle' that every car and bike is a kind of: they share the basics but each adds its own parts.",
        "Interfaces/traits/protocols decouple callers from concrete types and make testing with fakes easy. "
        "Deep inheritance couples subclasses to parent internals (the 'fragile base class' problem).",
    ),
    "async": (
        "Like putting a kettle on and making toast while it boils, instead of staring at the kettle.",
        "Async helps with I/O-bound work, not CPU-bound work. Look for blocking calls inside async functions, "
        "unawaited coroutines/promises, and missing timeouts or cancellation handling.",
    ),
    "decorators": (
        "Like gift-wrapping a present: the present is the same, but it now comes with something extra around it.",
        "Decorators run at import time, so registration-style decorators create hidden global state. Use "
        "`functools.wraps` to keep names and docstrings, and keep decorators small and side-effect free.",
    ),
    "comprehensions": (
        "Like saying 'give me every red apple from this basket' in one sentence instead of checking them one by one.",
        "Great for simple transforms. Once a comprehension has nested loops or complex conditions, a normal loop "
        "or a named helper is easier to read. Generator expressions avoid building big lists in memory.",
    ),
    "errors": (
        "Like a seatbelt: you hope you don't need it, but the program survives when something goes wrong.",
        "Check what is caught: broad `except Exception`/`catch (e)` that silently swallows errors hides bugs. "
        "Good code handles errors at the level that can actually do something about them.",
    ),
    "types": (
        "Like labels on storage boxes saying what belongs inside, so nobody puts shoes in the cereal box.",
        "Types document intent and catch whole classes of bugs before runtime. Look at how the code models "
        "optional values and errors in its types, and whether `Any`/`any` leaks hide real problems.",
    ),
    "generators": (
        "Like a ticket machine that prints the next number only when someone asks, instead of printing all of them at once.",
        "Generators are lazy and single-pass. They pair well with pipelines; be careful with code that iterates "
        "the same generator twice or holds resources (files) open across `yield`s.",
    ),
    "context_managers": (
        "Like a library that automatically takes your book back when you leave, so you never forget to return it.",
        "Deterministic cleanup is key to avoiding resource leaks. Check that every opened resource has a clear "
        "owner and that cleanup also happens on error paths.",
    ),
    "closures": (
        "Like handing a friend a note with instructions to follow later: the note is the function.",
        "Closures capture variables, not values: watch for late-binding bugs in loops. Callbacks can lead to "
        "deeply nested code; promises/async or small named functions keep it flat.",
    ),
    "regex": (
        "Like a 'find' box in a word processor that understands rules, such as 'any 3 digits followed by a dash'.",
        "Regexes are compact but brittle. Prefer real parsers for structured formats (HTML, JSON, code), "
        "precompile hot patterns, and beware catastrophic backtracking on untrusted input.",
    ),
    "file_io": (
        "Like opening a notebook, reading or writing in it, and closing it again.",
        "Watch for encoding assumptions, partial writes (write to a temp file then rename), and path handling "
        "that breaks across operating systems.",
    ),
    "json": (
        "Like a standard shipping box that every program knows how to open and pack.",
        "Validate data from outside your program instead of trusting its shape. Typed models (dataclasses, "
        "pydantic, zod, serde) turn loose dictionaries into checked structures.",
    ),
    "http": (
        "Like sending a letter to another computer and waiting for its reply.",
        "Look for timeouts, retries with backoff, status-code checks and how secrets are passed. Missing timeouts "
        "are one of the most common production bugs.",
    ),
    "web_server": (
        "Like a restaurant where each item on the menu (URL) has a cook (function) who prepares it.",
        "Notice how routing, validation, business logic and storage are separated. Handlers that do everything "
        "themselves are hard to test. Check input validation and authentication on every route.",
    ),
    "cli": (
        "Like ordering at a counter: the words after the program name tell it exactly what you want.",
        "A good CLI keeps parsing separate from logic so the logic can be imported and tested. Check exit codes "
        "and whether errors go to stderr.",
    ),
    "env_config": (
        "Like a settings menu, so you can change how the program behaves without rebuilding it.",
        "Configuration should be read once at the edges and passed in, not read from globals deep inside the code. "
        "Secrets must never be committed; look for a documented `.env.example`.",
    ),
    "testing": (
        "Like a checklist you run after cooking to confirm the dish tastes right, every single time.",
        "Look at what is tested (behaviour vs. implementation details), how external services are faked, and "
        "whether edge cases and failure paths are covered.",
    ),
    "concurrency": (
        "Like several cooks in one kitchen: faster, but they must not grab the same pan at the same time.",
        "Check shared mutable state, locking, and how errors from workers are collected. Python threads don't "
        "speed up CPU-bound work because of the GIL; processes do.",
    ),
    "database": (
        "Like a giant, very organised filing cabinet you can ask questions.",
        "Look for parameterised queries (never string-concatenated SQL), transactions around multi-step writes, "
        "N+1 query patterns, and how schema migrations are handled.",
    ),
    "logging": (
        "Like a ship's logbook: a written record of what happened and when.",
        "Structured logs and consistent levels make debugging production issues possible. Make sure secrets and "
        "personal data are not logged.",
    ),
    "dataclasses": (
        "Like a form with labelled boxes (name, age, email) instead of a loose pile of notes.",
        "Immutable data (frozen dataclasses, records) is easier to reason about. Check whether validation happens "
        "at construction or is scattered around the code.",
    ),
    "enums": (
        "Like a multiple-choice question: only the listed answers are allowed.",
        "Exhaustive matching over enums (match/switch with no default) lets the compiler or type checker warn you "
        "when a new case is added but not handled.",
    ),
    "recursion": (
        "Like Russian nesting dolls: open one, and there's a smaller one inside, until you reach the smallest.",
        "Recursion depth is limited (about 1000 frames in Python). Deep inputs may need an explicit stack. "
        "Memoisation turns exponential recursive algorithms into fast ones.",
    ),
    "gui": (
        "Like a TV remote: pressing a button sends a signal, and the program reacts to it.",
        "Long work must not run on the UI thread or the window freezes. Look at how state is kept in sync with "
        "what is displayed (manual updates vs. a reactive framework).",
    ),
    "llm_api": (
        "Like texting a very well-read assistant and using their reply inside your program.",
        "Look at prompt construction, handling of refusals, rate limits and errors, streaming for long outputs, "
        "and whether model output is validated before the program acts on it.",
    ),
}
