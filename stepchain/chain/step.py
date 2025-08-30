from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Type


@dataclass(slots=True)
class StepSpec:
    func: Callable[..., Any]
    out: str
    args: Sequence[Any]
    kwargs: Mapping[str, Any]
    name: Optional[str]
    retries: int
    retry_on: Tuple[Type[BaseException], ...]
    backoff: float
    max_backoff: float
    log: Optional[Callable[[Mapping[str, Any], Any], None]] = None
    log_fmt: Optional[str] = None
    validate: Optional[Callable[[Any], None]] = None

    # compiled
    arg_resolvers: Optional[Sequence[Callable[[Mapping[str, Any]], Any]]] = None
    kw_resolvers: Optional[Mapping[str, Callable[[Mapping[str, Any]], Any]]] = None
    log_renderer: Optional[Callable[[Mapping[str, Any], Any], str]] = None
