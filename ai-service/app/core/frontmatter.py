"""Frontmatter shared by mandates and knowledge documents: a `---` block of `key: value` lines.

A value in `[a, b]` is a list; quotes around a value or a list item are dropped, so
`allowed_roles: ["cskh", "it"]` and `allowed_roles: [cskh, it]` read the same. Nothing nests.
"""

import re

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


class FrontmatterError(ValueError):
    pass


def split(text: str) -> tuple[dict, str]:
    """`(meta, body)` of `text` (newlines already `\\n`); no frontmatter gives `({}, text)`."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise FrontmatterError(f"bad frontmatter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [_unquote(v.strip()) for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = _unquote(value)
    return meta, text[m.end():]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
