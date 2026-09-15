"""
HTML-script-safe JSON serializer.

Why json.dumps alone is insufficient for <script> embedding
------------------------------------------------------------
json.dumps produces valid JSON but not automatically HTML-script-safe text.
An HTML parser treats the byte sequence </script> (in any case combination)
as closing the current <script> element *before* JavaScript sees the string.
This is independent of JavaScript string syntax: even a string literal like
"foo</script>bar" causes the HTML parser to close the script block, making
the text after </script> raw HTML that is visible to the DOM and to any
injected scripts.

The fix
-------
Unicode-escape the characters that allow script-element termination in the
JSON output produced by json.dumps:

  <      -> \u003c  (prevents any case of </script> from forming)
  >      -> \u003e  (belt-and-suspenders; prevents stray >)
  &      -> \u0026  (prevents HTML entity injection)
  U+2028 -> \u2028  (LINE SEPARATOR -- treated as line terminator in JS)
  U+2029 -> \u2029  (PARAGRAPH SEPARATOR -- same)

Because "<" is escaped, no user-controlled string can produce a literal
"</" sequence in the embedded JSON text, so no closing HTML tag can form.
json.loads(dumps_for_script(v)) == v for all JSON-safe v.
"""
from __future__ import annotations

import json
import re

# Five characters unsafe in HTML <script> text.  U+2028 and U+2029 are
# represented with chr() so the source file stays ASCII-clean.
_LS = chr(0x2028)  # LINE SEPARATOR
_PS = chr(0x2029)  # PARAGRAPH SEPARATOR
_UNSAFE_RE = re.compile("[<>&" + _LS + _PS + "]")

_ESCAPE_MAP: dict[str, str] = {
    "<":  r"\u003c",
    ">":  r"\u003e",
    "&":  r"\u0026",
    _LS:  r"\u2028",
    _PS:  r"\u2029",
}


def _replace(m: re.Match) -> str:
    return _ESCAPE_MAP[m.group()]


def dumps_for_script(value: object, **json_options) -> str:
    """Serialize *value* as JSON safe for embedding in an HTML <script> element.

    Equivalent to json.dumps(value, **json_options) followed by Unicode-escaping
    of characters that would otherwise allow an HTML parser to break out of the
    enclosing script block.

    All JSON-safe Python values are supported (dict, list, str, int, float,
    bool, None).  The output is valid JSON and parses back to the original value.

    Supported *json_options* are forwarded to json.dumps (e.g. sort_keys,
    separators, ensure_ascii, default).
    """
    raw = json.dumps(value, **json_options)
    return _UNSAFE_RE.sub(_replace, raw)
