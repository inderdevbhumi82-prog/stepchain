import pytest
from stepchain import Chain
from stepchain.chain.async_chain import AsyncChain


def test_etl_sync_end_to_end_should_load_transformed_rows(caplog):
    # Arrange
    caplog.set_level("INFO")

    # In-memory “source” (e.g., extracted from some file or API)
    SOURCE = [
        {"id": 1, "name": "alice", "active": True},
        {"id": 2, "name": "bob", "active": False},
        {"id": 3, "name": "carrie", "active": True},
    ]

    # Hooks (client wants metrics/traceability)
    hooks = {"before": 0, "after": 0}

    def before_step(**_):
        hooks["before"] += 1

    def after_step(**_):
        hooks["after"] += 1

    # Extract
    def extract():
        # imagine reading from S3/DB/etc. — here it’s just the in-memory list
        return SOURCE

    # Transform (filter + map)
    def transform(rows):
        # filter active == True, uppercase name
        out = [{"id": r["id"], "name": r["name"].upper()} for r in rows if r["active"]]
        return out

    # Load (simulate sink; fail once for retry)
    LOAD_TARGET: list[dict] = []
    calls = {"load": 0}

    def load(rows):
        calls["load"] += 1
        if calls["load"] == 1:  # transient failure to exercise retry/continue
            raise RuntimeError("transient-load-error")
        LOAD_TARGET.extend(rows)
        return {"loaded": len(rows)}

    # Optional: build a report-ish model with zero-arg callable
    class Report:
        def __init__(self, rows):
            self.rows = rows

        def model_dump(self):
            return {"rows": self.rows, "count": len(self.rows)}

    def build_report(rows):
        return Report(rows)

    # Simple validation (client wants non-empty loads)
    def validate_non_empty(result):
        if not result or not result.get("loaded"):
            raise ValueError("no rows loaded")

    # Redaction (mask secrets in logs if present)
    def redact(msg: str) -> str:
        return msg.replace("SECRET", "******")

    # Act
    ctx = (
        Chain(before_step=before_step, after_step=after_step, redact=redact, strict=True)
        .next(extract, out="raw", log_fmt="raw_n={raw.__len__}")
        .next(transform, out="clean", args=["raw"], log_fmt="clean_n={clean.__len__}")
        .next(
            load,
            out="loadres",
            args=["clean"],
            retries=1,
            retry_on=(RuntimeError,),
            backoff=0.0,
            max_backoff=0.0,
            log_fmt="loaded={loadres.loaded}",
        )
        .next(
            build_report,
            out="report",
            args=["clean"],
            log_fmt="report={report.model_dump}",
        )
        .run()
    )

    # Assert (one concern: the ETL completed with the expected loaded rows)
    assert LOAD_TARGET == [{"id": 1, "name": "ALICE"}, {"id": 3, "name": "CARRIE"}]
    assert ctx["loadres"]["loaded"] == 2

    # before runs for every attempt (4 steps + 1 retry) => 5
    # after runs once per completed step (4)
    assert hooks["before"] == 5
    assert hooks["after"] == 4
    # Logging signals (lengths, retry warning, JSON rendering)
    assert any("raw_n=3" in r.message for r in caplog.records)
    assert any("clean_n=2" in r.message for r in caplog.records)
    assert any("loaded=2" in r.message for r in caplog.records)
    assert any("report=" in r.message and '"count": 2' in r.message for r in caplog.records)
    assert any("retrying in" in r.message for r in caplog.records)  # transient load failure retried


@pytest.mark.asyncio
async def test_etl_async_end_to_end_should_load_transformed_rows(caplog):
    # Arrange
    caplog.set_level("INFO")

    SOURCE = [
        {"id": 10, "name": "dave", "active": True},
        {"id": 11, "name": "ellen", "active": True},
        {"id": 12, "name": "frank", "active": False},
        {"id": 13, "name": "grace", "active": True},
    ]

    # Extract (async)
    async def extract():
        return list(SOURCE)  # copy

    # Transform (async)
    async def transform(rows):
        return [{"id": r["id"], "name": r["name"].title()} for r in rows if r["active"]]

    # Load (async, fail once to exercise retry)
    TARGET: list[dict] = []
    calls = {"n": 0}

    async def load(rows):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("load-bounce")
        TARGET.extend(rows)
        return {"loaded": len(rows)}

    # Zero-arg callable on a simple wrapper object
    class Box:
        def __init__(self, rows):
            self.rows = rows

        def model_dump(self):
            return {"rows": self.rows, "n": len(self.rows)}

    async def boxify(rows):
        return Box(rows)

    def validate_loaded(res):
        if not res or not res.get("loaded"):
            raise ValueError("no rows loaded")

    # Act
    ctx = await (
        AsyncChain(jitter=False)  # deterministic; with backoff=0.0 ensures no sleeps
        .next(extract, out="raw", log_fmt="raw_n={raw.__len__}")
        .next(transform, out="clean", args=["raw"], log_fmt="clean_n={clean.__len__}")
        .next(
            load,
            out="loadres",
            args=["clean"],
            retries=1,
            retry_on=(RuntimeError,),
            backoff=0.0,
            max_backoff=0.0,
            log_fmt="loaded={loadres.loaded}",
        )
        .next(boxify, out="boxed", args=["clean"], log_fmt="boxed={boxed.model_dump}")
        .run()
    )

    # Assert (one concern: async ETL completed and loaded the expected rows)
    assert ctx["loadres"]["loaded"] == 3
    # Confirm the transformation + filter were applied
    assert any(r["name"] in ("Dave", "Ellen", "Grace") for r in ctx["boxed"].rows)
    # Logging signals for counts and JSON rendering
    assert any("raw_n=4" in r.message for r in caplog.records)
    assert any("clean_n=3" in r.message for r in caplog.records)
    assert any("loaded=3" in r.message for r in caplog.records)
    assert any("boxed=" in r.message and '"n": 3' in r.message for r in caplog.records)
    # Retry warning logged (first load attempt failed)
    assert any("retrying in" in r.message for r in caplog.records)
