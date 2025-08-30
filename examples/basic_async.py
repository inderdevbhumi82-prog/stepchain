# examples/basic_async.py
import asyncio
import logging
from stepchain.chain.async_chain import AsyncChain
from stepchain.exceptions import ValidationFailedError, StepFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE = [
    {"id": 10, "name": "dave", "active": True},
    {"id": 11, "name": "ellen", "active": True},
    {"id": 12, "name": "frank", "active": False},
]


async def extract():
    return list(SOURCE)


async def transform(rows):
    return [{"id": r["id"], "name": r["name"].title()} for r in rows if r["active"]]


calls = {"n": 0}


async def load(rows):
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("flaky sink")
    return {"loaded": len(rows), "rows": rows}


def validate(res):
    if not res.get("loaded"):
        raise ValueError("no rows loaded")


async def main():
    try:
        ctx = await (
            AsyncChain(jitter=False)  # deterministic; set backoff=0 to avoid sleeping
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
            .run()
        )
        print("pipeline ok:", ctx["loadres"]["loaded"], "rows:", ctx["loadres"]["rows"])
    except ValidationFailedError as e:
        print("validation error:", e)
    except StepFailedError as e:
        print("step failed:", e)


if __name__ == "__main__":
    asyncio.run(main())
