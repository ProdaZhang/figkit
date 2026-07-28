# -*- coding: utf-8 -*-
"""spec parity — spec/ authority vs shipped copy, plus en/zh structural parity.

Check 1 (byte parity):
    spec/<name>.md = version header (leading "> " quote lines + one blank line) + the body.
    Strip that header and it must equal figma2html/references/<name>.md byte for byte.

Check 2 (cross-language structure):
    spec/<name>.zh.md is a convenience mirror of the English authority. Prose cannot be
    compared across languages, but the fenced code blocks can be: strip `//` comments and
    whitespace and what remains is the schema itself, which is language-independent.
    This catches "someone changed the schema in English and forgot the zh mirror".

Usage: python3 tools/spec_parity.py   (run from the repo root; exit 0 = consistent, 1 = drift)
How to change things: land content edits in figma2html/references/ first (that's what ships
with the skill), then sync into spec/ (keeping the version header). Structural changes must
follow the freeze discipline: bump the version and update the changelog line in the header.
Then mirror the same edit into spec/<name>.zh.md.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("ui.json-schema.md", "flow-events.md")


def strip_header(text):
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return "\n".join(lines[i:])


def code_skeleton(text):
    """Fenced code blocks, with // comments and whitespace removed → the language-independent part."""
    out = []
    for block in re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.S):
        block = re.sub(r"//[^\n]*", "", block)          # drop line comments (they're translated)
        out.append(re.sub(r"\s+", "", block))
    return out


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def main():
    bad = []
    for name in FILES:
        spec, ref = _read("spec", name), _read("figma2html", "references", name)
        if strip_header(spec) != ref:
            bad.append(name)
            print("DRIFT:", name, "(spec minus header != figma2html/references copy)")
        else:
            print("OK:", name)

        zh_path = os.path.join(ROOT, "spec", name.replace(".md", ".zh.md"))
        if not os.path.exists(zh_path):
            continue                                     # zh mirror is optional
        zh_name = os.path.basename(zh_path)
        en_code, zh_code = code_skeleton(spec), code_skeleton(_read("spec", zh_name))
        if en_code != zh_code:
            bad.append(zh_name)
            print("DRIFT:", zh_name, "(code blocks differ from the English authority — "
                                     "%d vs %d blocks)" % (len(en_code), len(zh_code)))
        else:
            print("OK:", zh_name, "(%d code blocks match)" % len(en_code))

    if bad:
        print("FAIL: spec drift — land edits in references/ first, then sync spec/ "
              "(keep the version header) and mirror into the .zh.md copy.")
        return 1
    print("spec parity holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
