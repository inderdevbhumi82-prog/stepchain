import asyncio
import pytest
from unittest.mock import patch
from stepchain.chain.async_chain import AsyncChain
from stepchain.exceptions import StepFailedError, ValidationFailedError

pytestmark = pytest.mark.asyncio


async def _no_sleep(*_a, **_k):
    return None


async def test_run_async_happy_path_should_produce_expected_outputs():
    # Arrange
    async def add(a, b):
        return a + b

    async def square(x):
        return x * x

    # Act
    ctx = await (
        AsyncChain()
        .put("x", 2)
        .put("y", 3)
        .next(add, out="sum", args=["x", "y"])
        .next(square, out="sq", args=["sum"])
        .run()
    )

    # Assert
    assert ctx["sum"] == 5
    assert ctx["sq"] == 25


async def test_run_async_validate_failure_should_raise_validationfailed():
    # Arrange
    async def empty():
        return []

    def validator(res):
        if not res:
            raise ValueError("bad")

    # Act / Assert
    with pytest.raises(ValidationFailedError):
        await AsyncChain().next(empty, out="x", validate=validator).run()


async def test_run_async_retry_success_should_complete_after_retry():
    # Arrange
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    # Act
    with (
        patch("asyncio.sleep", new=_no_sleep),
        patch("random.uniform", lambda a, b: (a + b) / 2),
    ):
        ctx = await (
            AsyncChain()
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


async def test_run_async_retry_exhaustion_should_raise_stepfailed():
    # Arrange
    async def always_fail():
        raise KeyError("nope")

    # Act / Assert
    with patch("asyncio.sleep", new=_no_sleep), patch("random.uniform", lambda a, b: b):
        with pytest.raises(StepFailedError):
            await (
                AsyncChain()
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


async def test_run_async_allow_sync_false_should_raise_stepfailed():
    # Arrange
    def sync_step(x):
        return x + 1

    # Act / Assert
    with pytest.raises(StepFailedError):
        await AsyncChain(allow_sync=False).put("x", 1).next(sync_step, out="y", args=["x"]).run()


async def test_run_async_hooks_variants_should_be_invoked(caplog):
    # Arrange
    caplog.set_level("INFO")
    seen = {"before": 0, "after": 0, "retry": 0}

    async def before_step(**_):
        seen["before"] += 1

    async def after_step(**_):
        seen["after"] += 1

    async def on_retry(**_):
        seen["retry"] += 1

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("once")
        return "ok"

    # Act
    with patch("asyncio.sleep", new=_no_sleep), patch("random.uniform", lambda a, b: a):
        ctx = await (
            AsyncChain(before_step=before_step, after_step=after_step, on_retry=on_retry)
            .next(flaky, out="res", retries=1, retry_on=(RuntimeError,), log_fmt="const")
            .run()
        )

    # Assert
    assert ctx["res"] == "ok"
    assert seen == {"before": 2, "after": 1, "retry": 1}
    assert any(r.message == "const" for r in caplog.records)


async def test_run_async_deadline_invalid_should_fail_fast():
    # Arrange
    async def fail():
        raise RuntimeError("x")

    # Act / Assert
    with pytest.raises(StepFailedError) as ei:
        await (
            AsyncChain(deadline_fn=lambda: Exception("invalid"), safety_margin=0.05)
            .next(fail, out="x", retries=0, retry_on=(RuntimeError,))
            .run()
        )
    # Assert
    assert "Step 'x' failed" in str(ei.value)


async def test_run_async_deadline_exceeded_should_fail_fast():
    # Arrange
    async def fail():
        raise RuntimeError("x")

    # Act / Assert
    with pytest.raises(StepFailedError) as ei:
        await (
            AsyncChain(deadline_fn=lambda: 0.05, safety_margin=0.05)
            .next(fail, out="x", retries=3, retry_on=(RuntimeError,))
            .run()
        )
    # Assert
    assert "deadline exceeded before retry" in str(ei.value)


async def test_context_property_should_return_copy():
    # Arrange
    ch = AsyncChain().put("a", 1)
    await ch.next(lambda a: a, out="b", args=["a"]).run()

    # Act
    c = ch.context
    c["a"] = 999  # mutate copy

    # Assert
    assert ch.context["a"] == 1


async def test_run_async_sync_hooks_and_log_success_should_execute_without_await(
    caplog,
):
    # Arrange
    caplog.set_level("INFO")
    seen = {"before": 0, "after": 0, "log": 0}

    def before_step(**_):  # sync hook triggers _maybe_await "return x" path
        seen["before"] += 1

    def after_step(**_):  # sync hook again
        seen["after"] += 1

    def ok_log(ctx, res):  # successful log callback (no warning path)
        assert ctx["out"] == res
        seen["log"] += 1

    async def produce():
        return "value"

    # Act
    ctx = await (
        AsyncChain(before_step=before_step, after_step=after_step)
        .next(produce, out="out", log=ok_log, log_fmt="const")
        .run()
    )

    # Assert
    assert ctx["out"] == "value"
    assert seen == {"before": 1, "after": 1, "log": 1}
    assert any(r.message == "const" for r in caplog.records)


async def test_run_async_retry_with_positive_sleep_should_sleep_and_continue(
    monkeypatch,
):
    # Arrange
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return "ok"

    async def _no_sleep(*_a, **_k):
        return None

    # make jitter mid-way (positive) and plenty of time remaining
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    with patch("random.uniform", lambda a, b: (a + b) / 2):
        # Act
        ctx = await (
            AsyncChain(deadline_fn=lambda: 999.0, safety_margin=0.05)
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


async def test_run_async_logfmt_info_enabled_should_render_and_log(caplog):
    # Arrange
    caplog.set_level("INFO")

    async def make():
        return {"k": 1}

    # Act
    ctx = await AsyncChain().next(make, out="out", log_fmt="out={out}").run()

    # Assert
    assert ctx["out"] == {"k": 1}
    assert any(r.message == 'out={"k": 1}' for r in caplog.records)


async def test_run_async_retry_with_positive_sleep_should_call_sleep(monkeypatch):
    # Arrange
    calls = {"n": 0, "slept": []}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return "ok"

    async def fake_sleep(s):
        calls["slept"].append(s)

    # jitter mid-way to guarantee > 0 sleep; large deadline so we don't clamp to 0
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    from unittest.mock import patch

    with patch("random.uniform", lambda a, b: (a + b) / 2):
        # Act
        ctx = await (
            AsyncChain(deadline_fn=lambda: 999.0, safety_margin=0.01)
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
    assert len(calls["slept"]) == 1 and calls["slept"][0] > 0


async def test_run_async_logfmt_result_token_should_render_non_len_value(caplog):
    # Arrange
    caplog.set_level("INFO")

    class User:
        def __init__(self, name):
            self.name = name

    async def make_user():
        return User("alice")

    # Act
    ctx = await AsyncChain().next(make_user, out="user", log_fmt="user={result.name}").run()

    # Assert
    assert isinstance(ctx["user"], User)
    assert any(r.message == "user=alice" for r in caplog.records)


async def test_run_async_log_callback_fails_should_execute_with_warning(caplog):
    # Arrange
    caplog.set_level("INFO")

    async def make():
        return {"a": 1}

    def fail_log(ctx, res):
        raise RuntimeError("bad log")

    # Act
    ctx = await AsyncChain().next(make, out="out", log=fail_log, log_fmt="out={out}").run()

    # Assert
    for r in caplog.records:
        print(r.message)
        print(r.levelname)
    assert any(
        r.levelname == "WARNING" and r.message == "logging for step 'out' raised: bad log"
        for r in caplog.records
    )
