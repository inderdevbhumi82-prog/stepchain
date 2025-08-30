# examples/basic_sync.py
import logging
from stepchain import Chain, ValidationFailedError, StepFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE = [
    {"id": 1, "name": "alice", "active": True},
    {"id": 2, "name": "bob", "active": False},
    {"id": 3, "name": "carrie", "active": True},
]


def extract():
    return SOURCE


def transform(rows):
    return [{"id": r["id"], "name": r["name"].upper()} for r in rows if r["active"]]


TARGET = []
calls = {"load": 0}


def load(rows):
    calls["load"] += 1
    if calls["load"] == 1:
        # force a retry once
        raise RuntimeError("transient sink issue")
    TARGET.extend(rows)
    return {"loaded": len(rows)}


def validate_non_empty(load_result):
    if not load_result or not load_result.get("loaded"):
        raise ValueError("no rows loaded")


def redact(msg: str) -> str:
    # example: mask secrets if any appear in logs
    return msg.replace("SECRET", "****")


if __name__ == "__main__":
    try:
        ctx = (
            Chain(redact=redact, strict=True)
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
                lambda r: r["loaded"],
                out="count",
                args=["loadres"],
                log_fmt="count={count}",
            )
            .run()
        )
        print("pipeline ok:", ctx["count"], "rows loaded; target:", TARGET)
    except ValidationFailedError as e:
        print("validation error:", e)
    except StepFailedError as e:
        print("step failed:", e)
