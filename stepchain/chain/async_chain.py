from __future__ import annotations
import asyncio
import random
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple, Awaitable, Type

from .logging_setup import logger
from .step import StepSpec
from .context import compile_ref, compile_kwargs
from .formatting import compile_logfmt
from ..exceptions import StepFailedError, ValidationFailedError

HooksFn = Callable[..., Awaitable[None]] | Callable[..., None]
Func = Callable[..., Any] | Callable[..., Awaitable[Any]]


async def _maybe_await(x):
    if asyncio.iscoroutine(x):
        return await x
    return x


async def _call_func(func: Func, *args, allow_sync: bool = True, **kwargs):
    if asyncio.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    if allow_sync:
        # Run sync steps without blocking the event loop
        return await asyncio.to_thread(func, *args, **kwargs)
    # caller doesn’t allow sync functions
    raise TypeError("Synchronous step used in AsyncChain with allow_sync=False")


class AsyncChain:
    """
    Async version of Chain:
      - awaits async steps
      - optional offloading of sync steps via asyncio.to_thread
      - jittered, deadline-aware retries
      - async or sync hooks supported
    """

    def __init__(
        self,
        *,
        strict: bool = False,
        before_step: HooksFn | None = None,
        after_step: HooksFn | None = None,
        on_retry: HooksFn | None = None,
        redact: Callable[[str], str] | None = None,
        deadline_fn: Callable[[], float] | None = None,  # returns seconds remaining
        safety_margin: float = 0.25,
        jitter: bool = True,
        allow_sync: bool = True,  # allow sync steps (run in thread)
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
        self._allow_sync = allow_sync

    def put(self, key: str, value: Any) -> "AsyncChain":
        self._ctx[key] = value
        return self

    def next(
        self,
        func: Func,
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
    ) -> "AsyncChain":
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

    async def run(self) -> Dict[str, Any]:
        for spec in self._steps:
            step_name = spec.name or spec.out or getattr(spec.func, "__name__", "step")
            start = time.perf_counter()
            attempt = 0
            delay = spec.backoff

            while True:
                try:
                    if self._before:
                        await _maybe_await(self._before(step=step_name, context=self._ctx))

                    logger.info("starting step: %s", step_name)

                    r_args = [resolver(self._ctx) for resolver in (spec.arg_resolvers or [])]
                    r_kwargs = {k: rf(self._ctx) for k, rf in (spec.kw_resolvers or {}).items()}

                    result = await _call_func(
                        spec.func, *r_args, allow_sync=self._allow_sync, **r_kwargs
                    )

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

                    self._ctx[spec.out] = result

                    if spec.log:
                        try:
                            spec.log(self._ctx, result)
                        except Exception as le:
                            logger.warning("logging for step '%s' raised: %s", step_name, le)

                    if spec.log_renderer and logger.isEnabledFor(20):
                        try:
                            msg = spec.log_renderer(self._ctx, result)
                            msg = self._redact(msg)
                            logger.info(msg)
                        except Exception as le:
                            logger.warning("log_fmt for step '%s' failed: %s", step_name, le)

                    elapsed = round(time.perf_counter() - start, 3)
                    logger.info("completed step: %s in %ss", step_name, elapsed)

                    if self._after:
                        await _maybe_await(
                            self._after(
                                step=step_name,
                                context=self._ctx,
                                result=result,
                                elapsed=elapsed,
                            )
                        )

                    break

                except ValidationFailedError:
                    raise

                except spec.retry_on as e:
                    remaining = self._remaining()
                    if attempt < spec.retries and remaining > self._safety_margin:
                        attempt += 1
                        delay = min(delay * spec.backoff, spec.max_backoff)
                        sleep_for = random.uniform(0, delay) if True else delay
                        sleep_for = min(sleep_for, max(0.0, remaining - self._safety_margin))
                        if self._on_retry:
                            await _maybe_await(
                                self._on_retry(
                                    step=step_name,
                                    exc=e,
                                    attempt=attempt,
                                    next_delay=sleep_for,
                                )
                            )
                        logger.warning(
                            "step '%s' failed (attempt %d/%d): %s; retrying in %.3fs",
                            step_name,
                            attempt,
                            spec.retries,
                            e,
                            sleep_for,
                        )
                        if sleep_for > 0:
                            await asyncio.sleep(sleep_for)
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
