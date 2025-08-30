from __future__ import annotations
import json
import re
from typing import Any, Callable, Mapping
from .context import get_dotted

_TOKEN_RE = re.compile(r"\{([\w\.\_]+)\}")


def _const_renderer(s: str) -> Callable[[Mapping[str, Any], Any], str]:
    def render(_ctx: Mapping[str, Any], _res: Any) -> str:
        return s

    return render


def compile_logfmt(fmt: str | None) -> Callable[[Mapping[str, Any], Any], str] | None:
    """Precompile a log format with {dotted.path} tokens into a fast formatter."""
    if not fmt:
        return None

    tokens = list(_TOKEN_RE.finditer(fmt))
    if not tokens:
        # no tokens: return constant function
        return _const_renderer(fmt)

    # Pre-split static segments and token accessors
    segments: list[str] = []
    accessors: list[Callable[[Mapping[str, Any], Any], str]] = []

    last = 0
    for m in tokens:
        start, end = m.span()
        if start > last:
            segments.append(fmt[last:start])
        token = m.group(1)

        if token.endswith(".__len__"):
            base = token[: -len(".__len__")]
            if base.startswith("result."):
                path = base[len("result.") :]

                def acc(ctx, res, _path=path):
                    val = get_dotted(res, _path)
                    return str(len(val) if val is not None else 0)

            else:
                path = base

                def acc(ctx, res, _path=path):
                    val = get_dotted(ctx, _path)
                    return str(len(val) if val is not None else 0)

            accessors.append(acc)
            segments.append("")  # placeholder
            last = end
            continue

        if token.startswith("result."):
            path = token[len("result.") :]

            def acc(ctx, res, _path=path):
                val = get_dotted(res, _path)
                return _coerce_value(val)

        else:
            path = token

            def acc(ctx, res, _path=path):
                val = get_dotted(ctx, _path)
                return _coerce_value(val)

        accessors.append(acc)
        segments.append("")  # placeholder
        last = end

    if last < len(fmt):
        segments.append(fmt[last:])

    def render(ctx: Mapping[str, Any], result: Any) -> str:
        out: list[str] = []
        seg_iter = iter(segments)
        acc_iter = iter(accessors)
        # segments and accessors alternate; segments starts with static or "".
        for seg in segments:
            out.append(next(seg_iter, ""))  # append seg (already iterating list)
        # Rebuild with tokens filled
        out = []
        t = 0
        pos = 0
        for m in tokens:
            out.append(fmt[pos : m.start()])
            out.append(next(acc_iter)(ctx, result))
            pos = m.end()
        if pos < len(fmt):
            out.append(fmt[pos:])
        return "".join(out)

    return render


def _coerce_value(val: Any) -> str:
    # zero-arg callable
    if callable(val):
        try:
            val = val()
        except TypeError:
            pass
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val)
        except Exception:
            return str(val)
    return "" if val is None else str(val)


def format_dotted(fmt: str, ctx: Mapping[str, Any], result: Any) -> str:
    """Compatibility wrapper used by older codepaths; now runs the compiled formatter."""
    render = compile_logfmt(fmt)
    return render(ctx, result) if render else ""
