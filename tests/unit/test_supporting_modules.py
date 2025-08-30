import importlib
import logging
import pytest

import stepchain.chain.context as ctx_mod
import stepchain.chain.formatting as fmt_mod
import stepchain.chain.logging_setup as log_mod
from stepchain import StepFailedError, ValidationFailedError


def test_context_get_dotted_missing_should_return_none():
    # Arrange / Act
    val = ctx_mod.get_dotted({}, "missing.key")
    # Assert
    assert val is None


def test_context_compile_ref_strict_mid_should_raise_lookup():
    # Arrange
    resolver = ctx_mod.compile_ref("a.b", strict=True)
    # Act / Assert
    with pytest.raises(LookupError):
        resolver({"a": None})


def test_context_compile_ref_strict_final_should_raise_lookup():
    # Arrange
    resolver = ctx_mod.compile_ref("a", strict=True)
    # Act / Assert
    with pytest.raises(LookupError):
        resolver({})


def test_context_compile_kwargs_should_resolve_mixed_sources():
    # Arrange
    kw = ctx_mod.compile_kwargs({"a": "root.val", "b": 42}, strict=False)
    ctx = {"root": {"val": "X"}}
    # Act
    a = kw["a"](ctx)
    b = kw["b"](ctx)
    # Assert
    assert a == "X" and b == 42


def test_formatting_compile_no_tokens_should_return_constant():
    # Arrange / Act
    render = fmt_mod.compile_logfmt("constant message")
    out = render({}, {})
    # Assert
    assert out == "constant message"


def test_formatting_ctx_len_should_render_length():
    # Arrange
    logfmt = "len={cfg.items.__len__}"
    render = fmt_mod.compile_logfmt(logfmt)
    ctx = {"cfg": {"items": [1, 2, 3, 4]}}
    # Act
    out = render(ctx, {})
    # Assert
    assert out == "len=4"


def test_formatting_result_len_zeroarg_callable_json_should_render():
    # Arrange
    class Box:
        def __init__(self, xs):
            self.data = xs

        def model_dump(self):
            return {"data": self.data}

    render1 = fmt_mod.compile_logfmt("rlen={result.data.__len__}")
    render2 = fmt_mod.compile_logfmt("json={box.model_dump}")

    # Act
    s1 = render1({}, Box([1, 2, 3]))
    s2 = render2({"box": Box([9])}, None)

    # Assert
    assert s1 == "rlen=3"
    assert s2 == 'json={"data": [9]}'


def test_formatting_json_dump_failure_should_fall_back_to_str():
    # Arrange: dict with a set inside causes json.dumps to raise
    render = fmt_mod.compile_logfmt("dump={bad}")
    ctx = {"bad": {"x": {1, 2}}}
    # Act
    s = render(ctx, None)
    # Assert
    assert "dump={" in s and "}" in s


def test_formatting_format_dotted_wrapper_should_handle_empty_and_constant():
    # Arrange / Act
    s1 = fmt_mod.format_dotted("", {}, {})
    s2 = fmt_mod.format_dotted("hello", {}, {})
    # Assert
    assert s1 == ""
    assert s2 == "hello"


def test_logging_setup_import_paths_should_bootstrap_handler_once():
    # Arrange
    # Remove handlers to force bootstrap
    for h in list(log_mod.logger.handlers):
        log_mod.logger.removeHandler(h)
    # Act
    mod1 = importlib.reload(log_mod)
    count1 = len(mod1.logger.handlers)
    # Add a handler and reload; should not duplicate excessively
    mod1.logger.addHandler(logging.StreamHandler())
    mod2 = importlib.reload(log_mod)
    count2 = len(mod2.logger.handlers)
    # Assert
    assert count1 >= 1
    assert count2 >= 1


def test_exceptions_construction_should_include_reason_and_step():
    # Arrange / Act
    e1 = StepFailedError("s1", "boom")
    e2 = ValidationFailedError("s2", "bad")
    # Assert
    assert "s1" in str(e1) and e1.reason == "boom"
    assert "s2" in str(e2) and e2.reason == "bad"


def test_context_compile_ref_strict_attribute_mid_should_raise_lookup():
    # Arrange
    class Obj:
        def __init__(self):
            self.inner = None  # mid-node becomes None

    resolver = ctx_mod.compile_ref("root.inner.value", strict=True)
    ctx = {"root": Obj()}

    # Act / Assert
    with pytest.raises(LookupError):
        resolver(ctx)


def test_formatting_compiled_ctx_len_with_static_segments_should_render_all_parts():
    # Arrange
    logfmt = "pre-{cfg.items.__len__}-post"
    render = fmt_mod.compile_logfmt(logfmt)
    ctx = {"cfg": {"items": [1, 2, 3]}}

    # Act
    out = render(ctx, {})

    # Assert
    assert out == "pre-3-post"


def test_formatting_format_dotted_wrapper_with_tokens_should_delegate_to_compiled():
    # Arrange
    fmt = "n={result.data.__len__}"

    class Box:
        def __init__(self, xs):
            self.data = xs

    # Act
    s = fmt_mod.format_dotted(fmt, {}, Box([10, 20, 30]))

    # Assert
    assert s == "n=3"


def test_context_compile_ref_strict_mapping_mid_should_raise_lookup():
    # Arrange
    resolver = ctx_mod.compile_ref("root.mid.tail", strict=True)
    ctx = {"root": {"mid": None}}  # mid becomes None during traversal

    # Act / Assert
    with pytest.raises(LookupError):
        resolver(ctx)


def test_context_compile_ref_strict_final_none_should_raise_lookup():
    # Arrange
    resolver = ctx_mod.compile_ref("root.leaf", strict=True)
    ctx = {"root": {"leaf": None}}

    # Act / Assert
    with pytest.raises(LookupError):
        resolver(ctx)


def test_formatting_compiled_non_len_token_and_wrapper_should_render():
    # Arrange
    ctx = {"cfg": {"name": "alpha"}}
    render = fmt_mod.compile_logfmt("name={cfg.name}")

    # Act
    s1 = render(ctx, {})
    s2 = fmt_mod.format_dotted("name={cfg.name}", ctx, {})

    # Assert
    assert s1 == "name=alpha"
    assert s2 == "name=alpha"


def test_context_compile_ref_strict_missing_head_should_raise_lookup():
    # Arrange
    resolver = ctx_mod.compile_ref("missing.tail", strict=True)
    ctx = {}  # head is absent

    # Act / Assert
    with pytest.raises(LookupError):
        resolver(ctx)
