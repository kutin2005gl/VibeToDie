"""Head + tail truncation for tool output (ported from ref/core).

Book ch04 §4.5–4.6: a cut that does not say what was cut makes the agent believe it saw
everything, so every cut says what was omitted and how to read it.
"""


def truncate_head_tail(
    text: str,
    *,
    how_to_read_rest: str,
    max_lines: int = 200,
    max_chars: int = 10_000,
    head_lines: int = 50,
    tail_lines: int = 50,
) -> str:
    """Keep the start and the end of `text` and replace the middle with a marker.

    The start often holds the context or the first error, the end the last error or the success
    line. Text within both limits is returned unchanged. `how_to_read_rest` is required: the
    output is not stored anywhere, so the tool must say how to get the omitted part back.
    """
    if not how_to_read_rest.strip():
        raise ValueError("how_to_read_rest must say how to read the omitted part")
    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines and len(text) <= max_chars:
        return text

    if len(lines) > max_lines:
        head = "".join(lines[:head_lines])
        tail = "".join(lines[len(lines) - tail_lines :])
    else:
        head = tail = text
    # A few very long lines (minified code) can still be too large, so each end is also capped
    half = max_chars // 2
    head = head[:half]
    tail = tail[max(0, len(tail) - half) :]

    # Line numbers of the original text; a line cut part-way counts as shown
    first = len(head.splitlines()) + 1
    last = len(lines) - len(tail.splitlines())
    if first <= last:
        where = f"lines {first}–{last} of {len(lines)}"
    else:
        where = f"part of line {first - 1}"
    omitted = len(text) - len(head) - len(tail)
    marker = f"... [{where} omitted ({omitted} characters). {how_to_read_rest}] ...\n"
    if head and not head.endswith("\n"):
        marker = "\n" + marker
    return head + marker + tail
