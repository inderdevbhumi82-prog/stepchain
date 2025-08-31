# Why not Airflow/Prefect/dbt/etc?

Those are **heavy DAG engines** for distributed orchestration.

**StepChain is for the inner loop**: inside your function, microservice, or Lambda.  
It complements those tools, not replaces them.

Use StepChain when you want:
- Minimal dependencies and tiny cold start
- Functional composition and fast unit tests
- Inline retries, deadlines, hooks, and logging — without a platform
