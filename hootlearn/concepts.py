"""A small library of programming concepts the analyzer can spot in code.

Each concept has regex patterns (optionally limited to some languages) and a
plain-English explanation written for someone who already knows variables,
loops and functions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Concept:
    key: str
    title: str
    explain: str
    practice: str
    patterns: list[str]
    languages: set[str] | None = None  # None = any language
    _compiled: list[re.Pattern] = field(default_factory=list, repr=False)

    def matches(self, language: str, text: str) -> int:
        if self.languages and language not in self.languages:
            return 0
        if not self._compiled:
            self._compiled = [re.compile(p, re.MULTILINE) for p in self.patterns]
        return sum(len(rx.findall(text)) for rx in self._compiled)


JS = {"javascript", "typescript", "tsx", "jsx"}
C_LIKE = {"c", "cpp", "java", "csharp", "go", "rust", "kotlin", "swift", "scala", "dart"}

CONCEPTS: list[Concept] = [
    Concept(
        "classes", "Classes and objects",
        "A class is a blueprint that bundles data (attributes) together with the functions that work on "
        "that data (methods). Each object you create from it gets its own copy of the data.",
        "Write a `BankAccount` class with a balance, plus `deposit` and `withdraw` methods. Create two accounts "
        "and check that they don't share a balance.",
        [r"^\s*(?:export\s+)?(?:abstract\s+)?(?:public\s+)?class\s+\w+", r"^\s*(?:pub\s+)?struct\s+\w+", r"^\s*impl\b"],
    ),
    Concept(
        "inheritance", "Inheritance and interfaces",
        "A class can build on another class (inherit) or promise to provide certain methods (implement an "
        "interface/trait). It lets different types be used the same way.",
        "Make a `Shape` base with an `area()` method, then `Circle` and `Square` that override it. Put both in "
        "a list and print every area in one loop.",
        [r"class\s+\w+\s*\(\s*[A-Z]\w*", r"class\s+\w+\s+extends\s+\w+", r"\bimplements\s+\w+",
         r"^\s*(?:pub\s+)?trait\s+\w+", r"^\s*(?:export\s+)?interface\s+\w+", r"\bimpl\s+\w+\s+for\s+\w+"],
    ),
    Concept(
        "async", "Asynchronous code (async / await)",
        "Async code lets a program start a slow task (a network call, reading a file) and do other work while "
        "it waits, instead of freezing. `await` means \"pause here until that result is ready\".",
        "Write a program that 'downloads' three things at once using `asyncio.sleep` (or `setTimeout`) to fake "
        "the delay. Time it and compare with doing them one after another.",
        [r"\basync\s+(?:def|fn|function)\b", r"\bawait\b", r"\.then\(", r"\bgo\s+func\b", r"\bgo\s+\w+\("],
    ),
    Concept(
        "decorators", "Decorators and annotations",
        "A decorator (the `@something` line above a function or class) wraps it with extra behaviour, such as "
        "registering a web route, caching results, or marking a test.",
        "Write a `@timer` decorator in Python that prints how long the wrapped function took.",
        [r"^\s*@\w[\w.]*"], {"python", "typescript", "tsx", "java", "kotlin", "csharp", "dart"},
    ),
    Concept(
        "comprehensions", "Comprehensions and functional helpers",
        "Short ways to build a new list or dictionary from an old one, for example "
        "`[x * 2 for x in numbers]` or `numbers.map(x => x * 2)`. They replace loops that append to a list.",
        "Rewrite three of your own `for` loops that build lists as comprehensions or `map`/`filter` calls.",
        [r"\[[^\]\n]+\bfor\b[^\]\n]+\bin\b[^\]\n]+\]", r"\.map\(", r"\.filter\(", r"\.reduce\(", r"\.iter\(\)"],
    ),
    Concept(
        "errors", "Error handling",
        "Code that expects something might go wrong (a missing file, bad input) and handles it instead of "
        "crashing: `try/except`, `try/catch`, Go's `if err != nil`, or Rust's `Result` and `?`.",
        "Write a function that reads a number from the user and keeps asking until the input is valid.",
        [r"^\s*try\s*[:{]", r"\bexcept\b", r"\bcatch\s*\(", r"if\s+err\s*!=\s*nil", r"\bResult<", r"\?\s*;", r"\braise\b", r"\bthrow\b"],
    ),
    Concept(
        "types", "Type hints and static types",
        "Labels that say what kind of value a variable or function expects (`name: str`, `count: number`). "
        "They catch mistakes early and act as documentation.",
        "Add type hints to one of your old scripts and run a type checker (`mypy` or `tsc`) on it.",
        [r"def\s+\w+\([^)]*:\s*\w+", r"\)\s*->\s*[\w\[]", r":\s*(?:string|number|boolean)\b", r"^\s*type\s+\w+\s*="],
        {"python"} | JS,
    ),
    Concept(
        "generators", "Generators and iterators",
        "A generator produces values one at a time with `yield` instead of building a whole list in memory. "
        "Useful for big files or endless streams of data.",
        "Write a generator that yields the lines of a file that contain a given word.",
        [r"\byield\b", r"function\s*\*", r"\bimpl\s+Iterator\b"],
    ),
    Concept(
        "context_managers", "Resource cleanup (with / defer / using)",
        "Patterns that make sure things like files or network connections are closed when you are done, even "
        "if an error happens: Python's `with`, Go's `defer`, C#'s `using`.",
        "Open a file with `with open(...)` and write to it. Then write your own tiny context manager class with "
        "`__enter__` and `__exit__`.",
        [r"^\s*(?:async\s+)?with\s+.+:\s*$", r"^\s*defer\s+", r"\busing\s*\(", r"__enter__"],
    ),
    Concept(
        "closures", "Functions as values (lambdas and callbacks)",
        "Functions can be stored in variables, passed to other functions, and created on the fly. A callback is "
        "a function you hand to someone else to call later.",
        "Write a `make_multiplier(n)` function that returns a new function which multiplies its input by n.",
        [r"\blambda\b", r"=>\s*[{(\w]", r"\|\w*\|\s*[{\w]", r"\bfunc\s*\("],
    ),
    Concept(
        "regex", "Regular expressions",
        "A mini-language for finding text patterns, such as all email addresses or every line that starts with a "
        "date. Powerful, but hard to read, so keep them small and commented.",
        "Use a regex to pull every number out of a sentence, then every word that starts with a capital letter.",
        [r"\bre\.(?:compile|match|search|findall|sub)\(", r"\bnew\s+RegExp\(", r"\bRegex::new\(", r"\bregexp\.\w+\(",
         r"(?<![\w)\]])/(?![/*\s])(?:\\.|[^/\n])+/[gimsuy]*\.(?:test|exec)\("],
    ),
    Concept(
        "file_io", "Reading and writing files",
        "Opening files, reading their contents, and saving results back to disk.",
        "Write a script that counts the words in a text file and saves the top 10 to a new file.",
        [r"\bopen\(", r"\.read_text\(", r"\.write_text\(", r"\bfs\.\w+", r"\bos\.ReadFile\b", r"\bFile::open\b", r"\bPath\("],
    ),
    Concept(
        "json", "JSON data",
        "JSON is a text format for structured data (dictionaries and lists). Programs use it to save settings or "
        "talk to web APIs.",
        "Save a dictionary of your favourite movies to a .json file, then load it back and print it.",
        [r"\bjson\.(?:loads?|dumps?)\(", r"\bJSON\.(?:parse|stringify)\(", r"\bserde_json\b", r"\bjson\.(?:Marshal|Unmarshal)\("],
    ),
    Concept(
        "http", "Talking to the web (HTTP requests)",
        "Sending requests to other servers (APIs) and reading their responses, e.g. fetching weather data.",
        "Call a free public API (such as https://api.github.com/users/<name>) and print one field from the reply.",
        [r"\brequests\.(?:get|post|put|delete)\(", r"\bhttpx\.", r"\bfetch\(", r"\baxios\b", r"\bhttp\.(?:Get|Post|NewRequest)\(", r"\breqwest\b", r"\burllib\.request\b"],
    ),
    Concept(
        "web_server", "Web servers and routes",
        "A program that waits for web requests and answers them. Each URL path (route) is connected to a function "
        "that builds the response.",
        "Build a tiny server with two routes: `/` that says hello and `/add?a=1&b=2` that returns the sum.",
        [r"@\w+\.(?:route|get|post|put|delete)\(", r"\bapp\.(?:get|post|use|listen)\(", r"\bexpress\(\)", r"\bFastAPI\(", r"\bFlask\(",
         r"\bhttp\.HandleFunc\(", r"\bRouter\(", r"\baxum::", r"\bactix_web\b"],
    ),
    Concept(
        "cli", "Command-line arguments",
        "Reading options the user types after the program name, like `tool --verbose input.txt`.",
        "Write a script that takes a filename and an optional `--upper` flag, and prints the file (in capitals "
        "if the flag is set).",
        [r"\bargparse\b", r"\bclick\.", r"\btyper\b", r"\bsys\.argv\b", r"\bprocess\.argv\b", r"\bcommander\b", r"\byargs\b",
         r"\bclap::", r"\bflag\.(?:String|Int|Bool|Parse)\(", r"\bcobra\b"],
    ),
    Concept(
        "env_config", "Configuration and environment variables",
        "Settings such as API keys or ports are read from environment variables or config files instead of being "
        "written into the code, so they can change without editing the program.",
        "Make a script print a greeting whose name comes from the `GREETING_NAME` environment variable, with a "
        "default if it isn't set.",
        [r"\bos\.environ\b", r"\bos\.getenv\(", r"\bprocess\.env\b", r"\bos\.Getenv\(", r"\benv::var\(", r"\bdotenv\b"],
    ),
    Concept(
        "testing", "Automated tests",
        "Small programs that run your code with known inputs and check the outputs. They tell you right away "
        "when a change breaks something.",
        "Write three `pytest` tests (or `jest`/`go test`) for a function you wrote earlier, including one edge case.",
        [r"^\s*def\s+test_\w+", r"\bimport\s+pytest\b", r"\bunittest\b", r"\bdescribe\(", r"\bit\(", r"\bexpect\(", r"func\s+Test\w+\(", r"#\[test\]", r"@Test\b"],
    ),
    Concept(
        "concurrency", "Threads and parallel work",
        "Running several pieces of work at the same time using threads, processes or worker pools. Care is "
        "needed so they don't overwrite each other's data.",
        "Use `concurrent.futures.ThreadPoolExecutor` to fetch several web pages at once.",
        [r"\bthreading\b", r"\bThread\(", r"\bmultiprocessing\b", r"\bconcurrent\.futures\b", r"\bsync\.(?:WaitGroup|Mutex)\b",
         r"\bstd::thread\b", r"\bMutex<", r"\bArc<", r"\bWorker\("],
    ),
    Concept(
        "database", "Databases and SQL",
        "Storing data in a database and getting it back out with queries, either with raw SQL or an ORM library "
        "that turns tables into classes.",
        "Use Python's built-in `sqlite3` to create a table of books, insert three rows, and query them back.",
        [r"\bSELECT\b[\s\S]{0,80}\bFROM\b", r"\bINSERT\s+INTO\b", r"\bsqlite3\b", r"\bsqlalchemy\b", r"\bprisma\b", r"\bmongoose\b", r"\bdatabase/sql\b", r"\bsqlx\b", r"\bdiesel\b"],
    ),
    Concept(
        "logging", "Logging",
        "Writing messages about what the program is doing (info, warnings, errors) so you can debug it later, "
        "instead of scattering `print` everywhere.",
        "Replace the `print` calls in a script with Python's `logging` module and try different log levels.",
        [r"\blogging\.\w+", r"\blogger\.\w+\(", r"\bconsole\.(?:error|warn)\(", r"\blog\.(?:Printf|Println|Fatal)\(", r"\btracing::", r"\blog::(?:info|warn|error)!"],
    ),
    Concept(
        "dataclasses", "Data containers (dataclasses, structs, records)",
        "Lightweight types whose main job is holding a few named fields together, like a `Point` with `x` and `y`.",
        "Turn a dictionary you use often into a `@dataclass` and notice how your editor now autocompletes the fields.",
        [r"@dataclass", r"\bNamedTuple\b", r"\bBaseModel\)", r"\brecord\s+\w+\(", r"\bdata\s+class\b", r"^\s*(?:pub\s+)?struct\s+\w+\s*\{"],
    ),
    Concept(
        "enums", "Enums",
        "A fixed set of named options, like `Color.RED`, `Color.GREEN`. They stop typos you would get from using "
        "plain strings.",
        "Create an enum for the days of the week and write a function that says whether a day is a weekend.",
        [r"\bclass\s+\w+\(\s*(?:\w+\.)?(?:Enum|IntEnum|StrEnum)\s*\)", r"^\s*(?:export\s+)?(?:pub\s+)?enum\s+\w+", r"\biota\b"],
    ),
    Concept(
        "recursion", "Recursion",
        "A function that calls itself on a smaller part of the problem, for example walking through folders inside "
        "folders. It needs a base case so it stops.",
        "Write a recursive function that prints every file inside a folder and all of its subfolders.",
        [],  # detected structurally in analyzer.py
    ),
    Concept(
        "gui", "Graphical user interfaces",
        "Windows, buttons and text boxes. GUI code is usually event-driven: you connect functions to events like "
        "'button clicked' and the toolkit calls them for you.",
        "Make a window with a text box and a button that shows the text reversed when clicked.",
        [r"\btkinter\b", r"\bPyQt\d?\b", r"\bPySide\d?\b", r"\bwx\.", r"\bReact\b", r"\buseState\(", r"\bdocument\.getElementById\(",
         r"\baddEventListener\(", r"\bSwiftUI\b", r"\bgtk\b"],
    ),
    Concept(
        "llm_api", "Calling AI models",
        "Sending text to a large language model through an API (Anthropic, OpenAI and others) and using the "
        "answer in your program.",
        "Read the API docs for one model provider and write a script that asks one question and prints the answer.",
        [r"\banthropic\b", r"\bopenai\b", r"\bmessages\.create\(", r"\bchat\.completions\b", r"\blangchain\b"],
    ),
]

CONCEPTS_BY_KEY = {c.key: c for c in CONCEPTS}


def detect(language: str, text: str) -> dict[str, int]:
    """Return {concept_key: number_of_hits} for one file's text."""
    hits = {}
    for concept in CONCEPTS:
        n = concept.matches(language, text)
        if n:
            hits[concept.key] = n
    return hits
