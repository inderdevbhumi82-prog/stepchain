from __future__ import annotations
import random
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple, Type

from .logging_setup import logger
from .step import StepSpec
from .context import compile_ref, compile_kwargs
from .formatting import compile_logfmt
from ..exceptions import StepFailedError, ValidationFailedError

HooksFn = Callable[..., None]


class Chain:
    """
    Composable chain of steps with:
      - precompiled arg/kw resolvers
      - precompiled log templates
      - jittered, deadline-aware retries
      - hooks & redaction
      - strict mode (unresolved refs -> errors)
      - tiny dependency footprint
    """

    def __init__(
        self,
        *,
        strict: bool = False,
        before_step: HooksFn | None = None,
        after_step: HooksFn | None = None,
        on_retry: HooksFn | None = None,
        redact: Callable[[str], str] | None = None,
        deadline_fn: Callable[[], float] | None = None,
        safety_margin: float = 0.25,
        jitter: bool = True,
    ) -> None:
        self._ctx: Dict[str, Any] = {}
        self._steps: list[StepSpec] = []
        self._strict = strict
        self._before = before_step
        self._after = after_step
        self._on_retry = on_retry
        self._redact = redact or (lambda s: s)
        self._deadline_fn = deadline_fn
        self._safety_margin = max(0.0, safety_margin)
        self._jitter = jitter

    def put(self, key: str, value: Any) -> "Chain":
        self._ctx[key] = value
        return self

    def next(
        self,
        func: Callable[..., Any],
        *,
        out: str,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        retries: int = 0,
        retry_on: Tuple[Type[BaseException], ...] = (Exception,),
        backoff: float = 1.5,
        max_backoff: float = 10.0,
        log: Optional[Callable[[Mapping[str, Any], Any], None]] = None,
        log_fmt: Optional[str] = None,
        validate: Optional[Callable[[Any], None]] = None,
    ) -> "Chain":
        spec = StepSpec(
            func=func,
            out=out,
            args=list(args or ()),
            kwargs=dict(kwargs or {}),
            name=name,
            retries=retries,
            retry_on=retry_on,
            backoff=backoff,
            max_backoff=max_backoff,
            log=log,
            log_fmt=log_fmt,
            validate=validate,
        )
        # precompile resolvers + log template
        spec.arg_resolvers = [compile_ref(a, self._strict) for a in spec.args]
        spec.kw_resolvers = compile_kwargs(spec.kwargs, self._strict)
        spec.log_renderer = compile_logfmt(spec.log_fmt)
        self._steps.append(spec)
        return self

    def _remaining(self) -> float:
        if not self._deadline_fn:
            return float("inf")
        try:
            return max(0.0, float(self._deadline_fn()))
        except Exception:
            return float("inf")

    def run(self) -> Dict[str, Any]:
        for spec in self._steps:
            step_name = spec.name or spec.out or getattr(spec.func, "__name__", "step")
            start = time.perf_counter()
            attempt = 0
            delay = spec.backoff

            while True:
                try:
                    if self._before:
                        self._before(step=step_name, context=self._ctx)

                    logger.info("starting step: %s", step_name)

                    # Resolve args/kwargs from context (precompiled)
                    r_args = [resolver(self._ctx) for resolver in (spec.arg_resolvers or [])]
                    r_kwargs = {k: rf(self._ctx) for k, rf in (spec.kw_resolvers or {}).items()}

                    result = spec.func(*r_args, **r_kwargs)

                    if spec.validate:
                        try:
                            spec.validate(result)
                        except Exception as ve:
                            elapsed = round(time.perf_counter() - start, 3)
                            logger.error(
                                "validation failed in step '%s' after %ss: %s",
                                step_name,
                                elapsed,
                                ve,
                            )
                            raise ValidationFailedError(step=step_name, reason=str(ve)) from ve

                    # Commit and post-step logging
                    self._ctx[spec.out] = result

                    if spec.log:
                        try:
                            spec.log(self._ctx, result)
                        except Exception as le:
                            logger.warning("logging for step '%s' raised: %s", step_name, le)

                    # Guarded, precompiled logging (no cost when INFO disabled)
                    if spec.log_renderer and logger.isEnabledFor(20):  # logging.INFO
                        try:
                            msg = spec.log_renderer(self._ctx, result)
                            msg = self._redact(msg)
                            logger.info(msg)
                        except Exception as le:
                            logger.warning("log_fmt for step '%s' failed: %s", step_name, le)

                    elapsed = round(time.perf_counter() - start, 3)
                    logger.info("completed step: %s in %ss", step_name, elapsed)

                    if self._after:
                        self._after(
                            step=step_name,
                            context=self._ctx,
                            result=result,
                            elapsed=elapsed,
                        )

                    break

                except ValidationFailedError:
                    # bubble up (no retry)
                    raise

                except spec.retry_on as e:
                    remaining = self._remaining()
                    if attempt < spec.retries and remaining > self._safety_margin:
                        attempt += 1
                        # compute next delay with jitter & deadline awareness
                        delay = min(delay * spec.backoff, spec.max_backoff)
                        sleep_for = random.uniform(0, delay) if self._jitter else delay
                        # don't sleep past the deadline
                        sleep_for = min(sleep_for, max(0.0, remaining - self._safety_margin))
                        if self._on_retry:
                            self._on_retry(
                                step=step_name,
                                exc=e,
                                attempt=attempt,
                                next_delay=sleep_for,
                            )
                        logger.warning(
                            "step '%s' failed (attempt %d/%d): %s; retrying in %.3fs",
                            step_name,
                            attempt,
                            spec.retries,
                            e,
                            sleep_for,
                        )
                        # sleep only if time remains
                        if sleep_for > 0:
                            time.sleep(sleep_for)
                        continue
                    else:
                        elapsed = round(time.perf_counter() - start, 3)
                        reason = (
                            str(e) if attempt >= spec.retries else "deadline exceeded before retry"
                        )
                        logger.error("step '%s' failed after %ss: %s", step_name, elapsed, reason)
                        raise StepFailedError(step=step_name, reason=reason) from e
        return self._ctx

    @property
    def context(self) -> Dict[str, Any]:
        return dict(self._ctx)
