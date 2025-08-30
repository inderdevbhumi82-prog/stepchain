# examples/fastapi_async.py
from fastapi import FastAPI
from stepchain.chain.async_chain import AsyncChain

app = FastAPI(title="Stepchain Async API")


async def fetch_items():
    return [
        {"sku": "A1", "price": 10.0, "active": True},
        {"sku": "B2", "price": 0.0, "active": False},
        {"sku": "C3", "price": 25.5, "active": True},
    ]


async def to_invoice_lines(items):
    return [
        {"sku": x["sku"], "amount": x["price"]} for x in items if x["active"] and x["price"] > 0
    ]


async def post_invoice(lines):
    # pretend call to billing service; return summary
    return {"lines": len(lines), "total": sum(l["amount"] for l in lines)}


@app.get("/async/invoice")
async def async_invoice():
    ctx = await (
        AsyncChain(jitter=False)
        .next(fetch_items, out="items", log_fmt="n_items={items.__len__}")
        .next(
            to_invoice_lines,
            out="lines",
            args=["items"],
            log_fmt="n_lines={lines.__len__}",
        )
        .next(post_invoice, out="summary", args=["lines"], log_fmt="total={summary.total}")
        .run()
    )
    return ctx["summary"]
