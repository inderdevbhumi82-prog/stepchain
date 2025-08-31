# Local Development Guide

This document explains how to set up a local environment for working on **py-stepchain**.

---

## 1. Prerequisites

- **Python 3.10** (recommended for consistency with CI and PyPI release)
- **pip** (latest version)
- **virtualenv** (comes with Python ≥3.10)

Check versions:

```bash
python3 --version
pip --version
```

---

## 2. Create and Activate Virtual Environment

### Create

```bash
python3.10 -m venv .venv
```

If that does not work then install python 3.10 and use its location, e.q. `$HOME/.pyenv/versions/3.10.14/bin/python3.10 -m venv .venv`


### Activate

```bash
source .venv/bin/activate
```

Once activated, your prompt should show (.venv).

---

## 3. Upgrade Pip

```bash
pip install --upgrade pip
```

---

## 4. Install Development Dependencies
Install package + dev tools:

```bash
pip install -e ".[dev]"
```

This installs:

- pytest → testing

- pytest-cov → coverage reporting

- black → code formatting

- mypy → static typing

---

## 5. Run Tests

```bash
pytest --cov=stepchain --cov-report=term-missing --cov-branch
```

---

## 6. Linting and Type Checking

### Format with black

```bash
black .
```

### Check formatting only

```bash
black --check .
```

### Type checks with mypy

```bash
mypy .
```
