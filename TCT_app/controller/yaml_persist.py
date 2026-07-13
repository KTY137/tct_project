"""Comment-preserving persistence for ``configs/devices.yaml``.

Every prior devices.yaml writer round-tripped the file through
``yaml.safe_load`` -> ``yaml.dump``, which is semantically correct but
silently strips every comment in the document (PyYAML's ``safe_load`` never
retains comment nodes). That destroyed manual-cited documentation twice
(TECH_DEBT.md, RISK, 2026-07-10 and again 2026-07-11 -- the
``waveform_generator.level_low_V`` / ``level_high_V`` unipolar-trigger
comment block).

``ruamel.yaml`` (round-trip mode) would be the natural fix but is not in
``requirements.txt`` / the project venv today -- adding a new dependency to
fix a persistence bug is out of scope for this change, so this module is a
small, deliberately "dumb" line-level surgical editor instead: it walks the
YAML *source text* with an indentation stack (this repo's devices.yaml is
consistently 2-space-indented, no tabs) and only rewrites the value half of
lines whose key path exactly matches a known, caller-supplied update --
every other line (including every comment, blank line, and unrelated
section) passes through completely untouched, byte-for-byte.

This is intentionally NOT a general YAML editor: existing *list items* in
the source document (e.g. ``slow_control.channels``) are opaque to it --
untouched, but never a valid update target/path. A leaf *value* that is
itself a ``list``/``tuple`` (e.g. ``_MotorSection.to_dict()``'s PI branch
``"axes": [1, 2, 3]``) IS supported: it is rendered flow-style on the single
``key: [1, 2, 3]`` line the rewrite/append path already produces (see
:func:`_yaml_scalar_text`) -- multi-document files, flow-style mappings, and
complex/multi-line scalars remain unsupported; only the plain
``key: scalar`` (or ``key: [flow, list]``) block-mapping style this
project's config file already uses. Every writer that rewrites devices.yaml
(gui/scope_panel.py, gui/settings_window.py) should route through
:func:`merge_yaml_text` / :func:`update_yaml_file` instead of a raw
``yaml.safe_load`` + ``yaml.dump`` round trip.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

# A block-mapping key line: optional leading spaces, a key (anything up to
# the first ":"), a colon, then the rest of the line (value + optional
# trailing comment). Deliberately excludes list items ("- foo: bar") --
# those are rejected by the ``lstripped.startswith("- ")`` check in the
# callers below before this pattern is even tried.
_KEY_LINE_RE = re.compile(r"^(?P<indent> *)(?P<key>[^\s:#][^:]*):(?P<rest>.*)$")


def _flatten(updates: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Flatten a nested ``{section: {key: value, sub: {...}}}`` mapping into
    ``{(section, key): value, (section, sub, key2): value2, ...}``. Only
    ``dict`` values recurse; everything else (str/int/float/bool/None/list)
    is treated as a leaf scalar to write verbatim."""
    flat: dict[tuple[str, ...], Any] = {}
    for key, value in updates.items():
        path = prefix + (str(key),)
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _yaml_scalar_text(value: Any) -> str:
    """Render *value* the way PyYAML would render it as a mapping value
    (quoting/formatting stays consistent with the rest of this project's
    yaml.dump-written history), e.g. ``True`` -> ``true``, ``None`` ->
    ``null``, ``"19112408"`` -> ``'19112408'``.

    ``list``/``tuple`` leaves (e.g. ``_MotorSection.to_dict()``'s PI branch
    ``"axes": [1, 2, 3]``, settings_window.py) are rendered flow-style
    (``[1, 2, 3]``) on a single line -- block style would emit a multi-line
    ``- 1\\n- 2\\n...`` sequence that this single-line ``key: <value>``
    rewrite/append path cannot represent, which used to silently truncate
    the value to nothing (Mary review, 2026-07-11: a Quick-Settings save
    after switching motor_stage to "pi" corrupted ``axes`` to ``null``)."""
    if isinstance(value, (list, tuple)):
        dumped = yaml.safe_dump(list(value), default_flow_style=True, allow_unicode=True)
        return dumped.strip()
    dumped = yaml.safe_dump({"v": value}, default_flow_style=False, allow_unicode=True)
    first_line = dumped.splitlines()[0]
    _, sep, rest = first_line.partition(": ")
    if sep:
        return rest.strip()
    # Values PyYAML renders with no space after the colon (rare; e.g. an
    # empty mapping) -- fall back to splitting on the bare colon.
    return first_line.split(":", 1)[1].strip()


def _find_comment_start(rest: str) -> int | None:
    """Return the index within *rest* where a trailing ``# comment`` begins,
    or ``None`` if there isn't one. Tracks quote state so a ``#`` inside a
    quoted scalar is not mistaken for a comment (best-effort, not a full
    YAML scalar grammar)."""
    in_squote = in_dquote = False
    for i, ch in enumerate(rest):
        if ch == "'" and not in_dquote:
            in_squote = not in_squote
        elif ch == '"' and not in_squote:
            in_dquote = not in_dquote
        elif ch == "#" and not in_squote and not in_dquote:
            if i == 0 or rest[i - 1].isspace():
                return i
    return None


def _is_key_line(line: str) -> tuple[str, str, re.Match[str]] | None:
    """Classify *line* as a block-mapping key line. Returns
    ``(indent, key, match)`` or ``None`` for blank/comment/list-item/
    continuation lines."""
    stripped = line.strip()
    if stripped == "" or stripped.startswith("#"):
        return None
    lstripped = line.lstrip(" ")
    if lstripped.startswith("- "):
        return None
    m = _KEY_LINE_RE.match(line)
    if not m:
        return None
    return m.group("indent"), m.group("key").strip(), m


def _block_end(lines: list[str], path: tuple[str, ...]) -> int | None:
    """Return the index of the last line belonging to *path*'s block
    (the header line itself if it has no children), or ``None`` if *path*
    is not present in *lines* at all."""
    if path == ():
        return len(lines) - 1
    stack: list[tuple[int, str]] = []
    header_idx: int | None = None
    header_indent = -1
    last_idx: int | None = None
    for idx, line in enumerate(lines):
        classified = _is_key_line(line)
        if classified is None:
            if header_idx is not None:
                # Blank/comment line encountered while still inside the
                # target block -- tentatively part of it; corrected below if
                # a dedented key line ends the block first.
                last_idx = idx
            continue
        indent_str, key, _match = classified
        indent = len(indent_str)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        cur_path = tuple(k for _, k in stack) + (key,)
        stack.append((indent, key))
        if header_idx is not None:
            if indent > header_indent:
                last_idx = idx
                continue
            break  # dedent (or sibling) -- left the target's block
        if cur_path == path:
            header_idx = idx
            header_indent = indent
            last_idx = idx
    return last_idx if header_idx is not None else None


def _old_value_extent(lines: list[str], header_idx: int, header_indent: int) -> int:
    """Return the index of the last line belonging to the *old* value that
    followed a key line with an empty inline part (``key:`` with nothing
    after the colon) -- i.e. a nested mapping, or a block/"indentless"
    sequence (PyYAML's default dump style puts list items at the SAME
    indent as their key, e.g. ``charge_integration_window_s:`` / ``-
    2.0e-08`` in this project's own devices.yaml, not further indented).
    Returns *header_idx* itself if the key has no such body (a bare ``key:``
    with a null value). Needed so rewriting a leaf whose old value spanned
    multiple lines -- most importantly a block-style list being replaced by
    this module's single-line flow-style list rendering -- removes the old
    body instead of leaving orphaned ``- item`` lines behind (which would
    otherwise become invalid YAML sitting next to the new single-line
    value)."""
    last = header_idx
    for j in range(header_idx + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            last = j
            continue
        lstripped = line.lstrip(" ")
        indent = len(line) - len(lstripped)
        if lstripped.startswith("- ") and indent >= header_indent:
            last = j
            continue
        if indent > header_indent:
            last = j
            continue
        break
    return last


def merge_yaml_text(text: str, updates: Mapping[str, Any]) -> str:
    """Apply *updates* (a nested ``{section: {key: value}}`` mapping,
    mirroring the shape of the YAML document) onto *text* in place.

    Only the scalar leaves named in *updates* are touched: an existing
    ``key: <old value>`` line is rewritten to ``key: <new value>``, keeping
    its indentation and any trailing inline comment; a key path that does
    not yet exist in *text* is appended at the end of its deepest existing
    ancestor block (or, if the whole section is new, at the end of the
    file). Every other line -- comments, blank lines, unrelated keys and
    sections, formatting -- is returned byte-for-byte unchanged.
    """
    flat = _flatten(updates)
    if not flat:
        return text

    ends_with_newline = text.endswith("\n")
    lines = text.split("\n")
    if ends_with_newline and lines and lines[-1] == "":
        lines.pop()

    stack: list[tuple[int, str]] = []
    remaining = dict(flat)
    # (start, end) inclusive ranges of old-value body lines to delete after
    # the scan (a leaf whose old value spanned multiple lines -- a nested
    # mapping or a block-style sequence -- being overwritten by this
    # module's single-line value rendering; see _old_value_extent). Applied
    # in reverse order once the forward scan is done so earlier indices
    # stay valid.
    removal_ranges: list[tuple[int, int]] = []

    for idx, line in enumerate(lines):
        classified = _is_key_line(line)
        if classified is None:
            continue
        indent_str, key, match = classified
        indent = len(indent_str)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = tuple(k for _, k in stack) + (key,)
        stack.append((indent, key))
        if path in remaining:
            value_text = _yaml_scalar_text(remaining.pop(path))
            rest = match.group("rest")
            comment = ""
            hash_pos = _find_comment_start(rest)
            if hash_pos is not None:
                comment = rest[hash_pos:]
            new_line = f"{indent_str}{key}: {value_text}"
            if comment:
                new_line += f"  {comment}"
            lines[idx] = new_line
            if rest.strip() == "":
                end = _old_value_extent(lines, idx, indent)
                if end > idx:
                    removal_ranges.append((idx + 1, end))

    for start, end in sorted(removal_ranges, reverse=True):
        del lines[start:end + 1]

    # Anything left in `remaining` had no matching line -- append it under
    # the deepest existing ancestor block (dumb-but-safe: never guesses at
    # restructuring, only ever appends new lines).
    for path, value in remaining.items():
        anchor_depth = len(path) - 1
        anchor_path: tuple[str, ...] = ()
        anchor_idx = len(lines) - 1
        while anchor_depth >= 0:
            candidate = path[:anchor_depth]
            end = _block_end(lines, candidate)
            if end is not None:
                anchor_path = candidate
                anchor_idx = end
                break
            anchor_depth -= 1
        chain = path[len(anchor_path):]
        base_indent = len(anchor_path) * 2
        new_lines = [
            f"{' ' * (base_indent + i * 2)}{k}:"
            for i, k in enumerate(chain[:-1])
        ]
        leaf_indent = base_indent + (len(chain) - 1) * 2
        new_lines.append(f"{' ' * leaf_indent}{chain[-1]}: {_yaml_scalar_text(value)}")
        lines[anchor_idx + 1:anchor_idx + 1] = new_lines

    result = "\n".join(lines)
    if ends_with_newline:
        result += "\n"
    return result


def update_yaml_file(path: str | Path, updates: Mapping[str, Any]) -> None:
    """Read *path*, apply :func:`merge_yaml_text`, write it back. Raises on
    any I/O or read error -- callers that want the historical "best effort,
    silently do nothing on failure" behaviour should catch around this call
    (matching what the former yaml.safe_load/dump call sites did).

    The write is atomic: the full merged text is computed in memory first,
    written to a temporary file in the *same* directory, flushed + fsync'd,
    then :func:`os.replace`'d over the target. A crash mid-write can therefore
    never truncate ``configs/devices.yaml`` (it holds soft limits and HV
    ranges) -- the original stays intact until the atomic rename lands."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    new_text = merge_yaml_text(text, updates)
    # NamedTemporaryFile in the target's directory so os.replace is a same-
    # filesystem atomic rename (a temp on another volume would not be).
    fd, tmp_name = tempfile.mkstemp(
        dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, p)
    except BaseException:
        # Leave the original file untouched; clean up the temp on any failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
