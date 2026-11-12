"""
Build a single-file version of the mandate package for Spyder.
==============================================================

WHY
---
The package layout is correct engineering and it is friction for someone
running this in Spyder: relative imports break under F5, and the folder name
is part of the import path. A tool you cannot run is worth nothing, so this
generates one self-contained file you can open and press F5 on.

WHY GENERATE RATHER THAN HAND-MERGE
-----------------------------------
Because hand-merging creates exactly the drift this package exists to prevent.
If you paste factors.py into a combined file and later edit the original, the
two disagree and nothing tells you which is stale. Generating means the
single file is always derived from the package, never a second source of
truth. Edit the package, re-run this, and the standalone file follows.

HOW
---
Modules are concatenated in dependency order. Relative imports are dropped
(everything lands in one namespace, so they are unnecessary). Standard-library
and third-party imports are hoisted and deduplicated at the top, after the
mandatory `from __future__ import annotations`. Each module's docstring is
converted to a banner comment so it cannot collide with the future import.

The portfolio JSON is embedded as a fallback, so the output genuinely needs no
other file.

USAGE
-----
    python build_standalone.py
    python build_standalone.py --out ~/Desktop/mandate_standalone.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Dependency order: a module may only reference names defined above it.
MODULE_ORDER = [
    "factors.py",
    "policy.py",
    "rubric.py",
    "valuation.py",
    "company.py",
    "scenarios.py",
    "risk.py",
    "review.py",
]

RELATIVE_IMPORT = re.compile(r"^\s*from\s+\.")
IMPORT_LINE = re.compile(r"^\s*(?:import\s+\w|from\s+(?!\.)\w[\w.]*\s+import\s)")
FUTURE_IMPORT = re.compile(r"^\s*from\s+__future__\s+import")
MAIN_GUARD = re.compile(r"^if\s+__name__\s*==")


def split_module(text: str) -> tuple[str, list[str], list[str]]:
    """Return (docstring, hoisted imports, body lines) for one module."""
    lines = text.splitlines()

    # Module docstring: leading triple-quoted block.
    docstring = ""
    start = 0
    if lines and lines[0].lstrip().startswith(('"""', "'''")):
        quote = lines[0].lstrip()[:3]
        end = 0
        if lines[0].lstrip().count(quote) >= 2 and len(lines[0].strip()) > 3:
            end = 0
        else:
            for i in range(1, len(lines)):
                if quote in lines[i]:
                    end = i
                    break
        docstring = "\n".join(lines[: end + 1])
        start = end + 1

    imports: list[str] = []
    body: list[str] = []
    skipping_main = False
    for line in lines[start:]:
        # Drop each module's own `if __name__ == "__main__":` block. Left in,
        # the first one reached would call main() and SystemExit out of the
        # script before the combined entry point at the bottom ever runs.
        if MAIN_GUARD.match(line):
            skipping_main = True
            continue
        if skipping_main:
            if line.strip() and not line.startswith((" ", "\t")):
                skipping_main = False  # dedented back to module level
            else:
                continue
        if RELATIVE_IMPORT.match(line) or FUTURE_IMPORT.match(line):
            continue
        if IMPORT_LINE.match(line) and not line.startswith((" ", "\t")):
            imports.append(line.strip())
            continue
        body.append(line)

    return docstring, imports, body


def _merge_from_imports(lines) -> list[str]:
    """Collapse `from X import a` + `from X import a, b` into one line.

    Duplicate from-imports are legal but noisy, and noise at the top of a
    generated file is what makes people distrust generated files.
    """
    by_module: dict[str, set[str]] = {}
    for line in lines:
        module, _, names = line.partition(" import ")
        module = module.replace("from ", "").strip()
        by_module.setdefault(module, set()).update(
            n.strip() for n in names.split(",") if n.strip()
        )
    return [
        f"from {module} import {', '.join(sorted(names))}"
        for module, names in sorted(by_module.items())
    ]


def banner(title: str, docstring: str) -> list[str]:
    """Turn a module docstring into a comment block that cannot collide."""
    out = ["", "# " + "=" * 76, f"# MODULE: {title}", "# " + "=" * 76]
    stripped = docstring.strip().strip('"').strip("'").strip()
    for line in stripped.splitlines():
        out.append(("# " + line).rstrip())
    out.append("")
    return out


def build(package: Path, portfolio: Path) -> str:
    all_imports: list[str] = []
    sections: list[list[str]] = []

    for name in MODULE_ORDER:
        path = package / name
        if not path.exists():
            raise FileNotFoundError(f"missing module: {path}")
        doc, imports, body = split_module(path.read_text(encoding="utf-8"))
        for imp in imports:
            if imp not in all_imports:
                all_imports.append(imp)
        sections.append(banner(name, doc) + body)

    # Embed as a JSON *string* parsed at runtime, not as a Python literal.
    # json.dumps emits null/true/false, which are not Python names, so pasting
    # its output into source is a NameError waiting to happen.
    embedded_json = json.dumps(
        json.loads(portfolio.read_text(encoding="utf-8")), indent=2
    )

    header = [
        '"""',
        "mandate — single-file build. GENERATED; do not edit by hand.",
        "",
        "Source of truth is the mandate/ package. Edit there and re-run",
        "build_standalone.py, or your changes are lost on the next build.",
        "",
        "Open this file in Spyder and press F5. It needs numpy and pandas and",
        "nothing else — the portfolio is embedded below.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    header += sorted(i for i in all_imports if i.startswith("import "))
    header += _merge_from_imports(i for i in all_imports if i.startswith("from "))
    header += [
        "",
        "",
        "# Embedded portfolio, used when no JSON file sits beside this script.",
        '_EMBEDDED_PORTFOLIO_JSON = r"""',
        embedded_json,
        '"""',
        "_EMBEDDED_PORTFOLIO = json.loads(_EMBEDDED_PORTFOLIO_JSON)",
        "",
        "",
        "# " + "-" * 76,
        "# Module aliases",
        "# " + "-" * 76,
        "# In the package, review.py does `from . import risk, scenarios` and then",
        "# calls risk.concentration(...). Here everything shares one namespace, so",
        "# those relative imports were stripped -- which left the FUNCTIONS defined",
        "# but the MODULE names undefined, and every qualified call raised",
        "# NameError at runtime rather than at import.",
        "#",
        "# This shim resolves attribute lookups straight into this file's globals.",
        "# __getattr__ runs at call time, so names defined further down are found",
        "# even though the alias is created up here.",
        "",
        "",
        "class _ModuleAlias:",
        '    """Makes `risk.concentration` resolve to the flat global of that name."""',
        "",
        "    def __getattr__(self, name: str):",
        "        try:",
        "            return globals()[name]",
        "        except KeyError:",
        "            raise AttributeError(",
        "                f'{name!r} is not defined in this single-file build'",
        "            ) from None",
        "",
        "",
        "factors = policy = risk = rubric = scenarios = valuation = _ModuleAlias()",
        "",
    ]

    footer = [
        "",
        "",
        "# " + "=" * 76,
        "# STANDALONE ENTRY POINT",
        "# " + "=" * 76,
        "#",
        "# Writes the embedded portfolio to disk if no JSON is present, then runs",
        "# the review. In Spyder: press F5. In a terminal: python <thisfile>.py",
        "",
        "",
        "def _ensure_portfolio() -> Path:",
        "    path = script_dir() / 'portfolio.json'",
        "    if not path.exists():",
        "        path.write_text(json.dumps(_EMBEDDED_PORTFOLIO, indent=2), encoding='utf-8')",
        "        print(f'Wrote a starter portfolio to {path}')",
        "        print('Edit it with your real market values, then run again.\\n')",
        "    return path",
        "",
        "",
        "if __name__ == '__main__':",
        "    main(['--portfolio', str(_ensure_portfolio())])",
        "",
    ]

    parts = header
    for section in sections:
        parts += section
    parts += footer
    return "\n".join(parts)


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Build the single-file version.")
    parser.add_argument("--package", type=Path, default=here / "mandate")
    parser.add_argument("--out", type=Path, default=here / "mandate_standalone.py")
    args = parser.parse_args()

    text = build(args.package, args.package / "portfolio.json")
    args.out.write_text(text, encoding="utf-8")
    lines = text.count("\n") + 1
    print(f"Wrote {args.out} ({lines:,} lines, {len(text) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
