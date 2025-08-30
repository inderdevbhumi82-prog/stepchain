# examples/fastapi_sync.py
from fastapi import FastAPI
from stepchain import Chain

app = FastAPI(title="Stepchain Sync API")


def extract_users():
    return [
        {"id": 1, "name": "alice", "active": True},
        {"id": 2, "name": "bob", "active": False},
        {"id": 3, "name": "carrie", "active": True},
    ]


def transform_active(rows):
    return [{"id": r["id"], "name": r["name"].upper()} for r in rows if r["active"]]


def save(rows):
    # pretend DB insert; just echo back
    return {"inserted": len(rows), "rows": rows}


@app.get("/sync/etl")
def sync_etl():
    ctx = (
        Chain(strict=True)
        .next(extract_users, out="raw", log_fmt="raw={raw.__len__}")
        .next(transform_active, out="clean", args=["raw"], log_fmt="clean={clean.__len__}")
        .next(save, out="result", args=["clean"], log_fmt="inserted={result.inserted}")
        .run()
    )
    return ctx["result"]
