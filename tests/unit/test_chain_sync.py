import logging
import pytest
from unittest.mock import patch
from stepchain import Chain, StepFailedError, ValidationFailedError


def test_run_happy_path_should_produce_expected_outputs():
    # Arrange
    def add(a, b):
        return a + b

    def square(x):
        return x * x

    # Act
    ctx = (
        Chain()
        .put("x", 2)
        .put("y", 3)
        .next(add, out="sum", args=["x", "y"])
        .next(square, out="sq", args=["sum"])
        .run()
    )

    # Assert
    assert ctx["sum"] == 5
    assert ctx["sq"] == 25


def test_run_validate_failure_should_raise_validationfailed():
    # Arrange
    def make_empty():
        return []

    def require_non_empty(res):
        if not res:
            raise ValueError("empty")

    # Act / Assert
    with pytest.raises(ValidationFailedError):
        Chain().next(make_empty, out="bad", validate=require_non_empty).run()


def test_run_retry_success_should_complete_after_retry(caplog):
    # Arrange
    caplog.set_level("INFO")
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    # Act
    with patch("random.uniform", lambda a, b: a), patch("time.sleep", lambda s: None):
        ctx = (
            Chain()
            .next(
                flaky,
                out="res",
                retries=1,
                retry_on=(RuntimeError,),
                backoff=1.5,
                max_backoff=2.0,
            )
            .run()
        )

    # Assert
    assert ctx["res"] == "ok"
    assert calls["n"] == 2
    assert any("retrying in" in r.message for r in caplog.records)


def test_run_retry_exhaustion_should_raise_stepfailed():
    # Arrange
    def always_fail():
        raise KeyError("nope")

    # Act / Assert
    with patch("time.sleep", lambda s: None):
        with pytest.raises(StepFailedError):
            (
                Chain()
                .next(
                    always_fail,
                    out="x",
                    retries=2,
                    retry_on=(KeyError,),
                    backoff=1.2,
                    max_backoff=2.0,
                )
                .run()
            )


def test_run_hooks_and_redaction_should_execute_and_redact(caplog):
    # Arrange
    caplog.set_level("INFO")
    seen = {"before": 0, "after": 0}

    def before_step(**_):
        seen["before"] += 1

    def after_step(**_):
        seen["after"] += 1

    def redact(msg: str) -> str:
        return msg.replace("secret", "******")

    # Act
    ctx = (
        Chain(before_step=before_step, after_step=after_step, redact=redact)
        .put("token", "secret")
        .next(lambda t: t, out="got", args=["token"], log_fmt="token={got}")
        .run()
    )

    # Assert
    assert ctx["got"] == "secret"
    assert seen == {"before": 1, "after": 1}
    assert any("token=******" in r.message for r in caplog.records)


def test_run_async_deadline_invalid_should_fail_fast():
    # Arrange
    def fail():
        raise RuntimeError("x")

    # Act / Assert
    with pytest.raises(StepFailedError) as ei:
        (
            Chain(deadline_fn=lambda: Exception("invalid"), safety_margin=0.05)
            .next(fail, out="x", retries=0, retry_on=(RuntimeError,))
            .run()
        )
    # Assert
    assert "Step 'x' failed" in str(ei.value)


def test_run_deadline_exceeded_should_fail_fast():
    # Arrange
    def fail_once():
        raise RuntimeError("transient")

    # Act / Assert
    with pytest.raises(StepFailedError) as ei:
        (
            Chain(deadline_fn=lambda: 0.05, safety_margin=0.05)
            .next(fail_once, out="x", retries=3, retry_on=(RuntimeError,))
            .run()
        )
    # Assert
    assert "deadline exceeded before retry" in str(ei.value)


def test_next_log_callback_error_should_be_swallowed(caplog):
    # Arrange
    caplog.set_level("INFO")

    def ok():
        return "result"

    def bad_log(_ctx, _res):
        raise RuntimeError("boom")

    # Act
    ctx = Chain().next(ok, out="x", log=bad_log).run()

    # Assert
    assert ctx["x"] == "result"
    assert any("logging for step 'x' raised" in r.message for r in caplog.records)


def test_run_logger_guard_should_skip_formatter():
    # Arrange
    import stepchain.chain.formatting as fmt_mod

    orig_compile = fmt_mod.compile_logfmt

    def raising_formatter(_fmt):
        return lambda *_: (_ for _ in ()).throw(RuntimeError("should not run"))

    # Act
    try:
        fmt_mod.compile_logfmt = raising_formatter  # formatter would raise if called
        from stepchain.chain.logging_setup import logger

        old = logger.level
        logger.setLevel(logging.WARNING)  # INFO disabled
        Chain().next(lambda: "v", out="x", log_fmt="won't be used").run()
    finally:
        logger.setLevel(old)
        fmt_mod.compile_logfmt = orig_compile

    # Assert
    # If formatter ran, we'd have crashed; reaching here means guard worked.
    assert True


def test_context_property_copy_should_not_reflect_mutation():
    # Arrange
    ch = Chain().put("a", 1).next(lambda a: a + 1, out="b", args=["a"])
    ch.run()

    # Act
    snap = ch.context
    snap["a"] = 999

    # Assert
    assert ch.context["a"] == 1


def test_run_logfmt_and_retry_continue_should_render_and_continue(caplog):
    # Arrange
    caplog.set_level("INFO")
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("oops")
        return {"ok": True}

    from unittest.mock import patch

    # Avoid real sleeping; choose deterministic jitter
    with (
        patch("time.sleep", lambda *_: None),
        patch("random.uniform", lambda a, b: (a + b) / 2),
    ):
        # Act
        ctx = (
            Chain()
            .next(
                flaky,
                out="res",
                retries=1,
                retry_on=(RuntimeError,),
                backoff=1.5,
                max_backoff=2.0,
                log_fmt="res={res}",
            )
            .run()
        )

    # Assert
    assert ctx["res"] == {"ok": True}
    assert calls["n"] == 2
    assert any(r.message == 'res={"ok": true}' for r in caplog.records)
