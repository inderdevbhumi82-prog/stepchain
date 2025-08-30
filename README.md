# StepChain 🪢

> **Composable step orchestrator for Python.**  
> Write clean, declarative pipelines for synchronous **and** asynchronous workflows — with retries, validation, logging, and hooks — all in a tiny, dependency-free package.

---

## Why StepChain?

Every real system has **orchestration glue code**:

- “extract → transform → load” ETL jobs  
- “fetch → enrich → push” API calls  
- “validate → save → notify” business workflows  

Without structure, these pipelines quickly become:
- ❌ Nested try/except spaghetti  
- ❌ Repeated logging boilerplate  
- ❌ Retry logic scattered everywhere  
- ❌ Hard to test, hard to extend  

**StepChain** exists to fix that.  
It gives you a **fluent API** to compose steps into a pipeline that is:

- 🔒 Safe — retries, validation hooks, deadlines, error classes  
- 📊 Transparent — precompiled logging, redaction, before/after hooks  
- ⚡ Fast — near-zero runtime overhead, tiny dependency footprint (great for Lambdas & microservices)  
- 🧩 Universal — works in **basic Python**, **FastAPI/asyncio**, or inside your **ETL jobs**  

---

## Use Cases

- **Data pipelines**  
  ETL/ELT flows with retries, validation, and logging baked in.  

- **APIs & async services**  
  Orchestrate async calls (HTTP, DB, queues) with retries and deadlines.  

- **Business workflows**  
  Chaining validation → save → publish → notify in web apps.  

- **Serverless (AWS Lambda, GCP Cloud Functions)**  
  Tiny cold-start friendly orchestrator (no heavy deps).  

- **Testing & prototyping**  
  Express multi-step flows declaratively, without external schedulers.  

---

## Install

```bash
pip install py-stepchain
```

## Usage

### Sync example (basic Python ETL)

```python
from stepchain import Chain

data = [
    {"id": 1, "name": "alice", "active": True},
    {"id": 2, "name": "bob",   "active": False},
]

def extract():
    return data

def transform(rows):
    return [r["name"].upper() for r in rows if r["active"]]

def load(names):
    print("Loaded:", names)
    return {"count": len(names)}

ctx = (
    Chain()
    .next(extract, out="raw", log_fmt="raw_n={raw.__len__}")
    .next(transform, out="clean", args=["raw"], log_fmt="clean_n={clean.__len__}")
    .next(load, out="loadres", args=["clean"], log_fmt="loaded={loadres.count}")
    .run()
)

print(ctx["loadres"])
# → {"count": 1}

```

### Async example (FastAPI)

```python
from fastapi import FastAPI
from stepchain.chain.async_chain import AsyncChain

app = FastAPI()

async def fetch_user(user_id: int):
    return {"id": user_id, "name": "Alice"}

async def enrich(user):
    user["greeting"] = f"Hello {user['name']}!"
    return user

@app.get("/hello/{user_id}")
async def hello(user_id: int):
    ctx = await (
        AsyncChain()
        .put("id", user_id)
        .next(fetch_user, out="user", args=["id"])
        .next(enrich, out="enriched", args=["user"], log_fmt="User={enriched.name}")
        .run()
    )
    return ctx["enriched"]

```

---

## Features

✅ Sync + Async APIs

✅ Retries with backoff + jitter

✅ Validation hooks per step

✅ Logging templates with {dotted.refs} and JSON serialization

✅ Before/After hooks for metrics and tracing

✅ Context redaction for secrets

✅ Strict mode: unresolved refs cause errors

✅ 100% type hints (mypy-friendly)

✅ Dependency-free (only stdlib)


---

## Why not Airflow/Prefect/dbt/etc?

- Those are **heavy DAG engines** for distributed orchestration.

- **StepChain is for the inner loop**: inside your function, microservice, or Lambda.

- It complements those tools, not replaces them.


