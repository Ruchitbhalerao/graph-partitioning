# Running Backend Tests

## Prerequisites

- Python 3.10+
- pip

## Setup

```bash
cd backend

# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt
pip install psutil pytest-asyncio
```

## Run Tests

```bash
# All tests (excluding slow benchmarks)
pytest tests/ -v

# With slow benchmarks
pytest tests/ -v --runslow

# Specific test file
pytest tests/test_engine.py -v

# Monitoring tests
pytest tests/test_monitoring.py -v

# Exclude slow + API tests (if fiona/GDAL not installed)
pytest tests/ -v -m "not slow" --ignore=tests/test_api.py
```

## Platform Notes

### macOS

```bash
# Install all dependencies (fiona/GDAL included)
pip install -r requirements.txt
pip install psutil pytest-asyncio

# Full test suite
pytest tests/ -v -m "not slow"
```

`fiona` may require GDAL. Install via Homebrew if needed:

```bash
brew install gdal
pip install fiona
```

### Windows

```bash
# Install dependencies
pip install -r requirements.txt
pip install psutil pytest-asyncio

# Run tests (skip API + export tests if fiona/GDAL unavailable)
pytest tests/ -v -m "not slow" --ignore=tests/test_api.py --ignore=tests/tests_export.py
```

`fiona` on Windows often requires a pre-built wheel from [PyPI](https://pypi.org/project/fiona/) or [Christoph Gohlke's site](https://www.lfd.uci.edu/~gohlke/pythonlibs/). If unavailable, API and export tests (`test_api.py`, `tests_export.py`) will be skipped.

For `shapely` issues on Windows, install via:

```bash
pip install shapely --only-binary=shapely
```

## Troubleshooting

| Error | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'fiona'` | Install GDAL, then `pip install fiona`, or skip `test_api.py`/`tests_export.py` |
| `async def functions are not natively supported` | `pip install pytest-asyncio` |
| `ModuleNotFoundError: No module named 'psutil'` | `pip install psutil` |
| Tests timeout on `test_large_dataset` | Marked `@pytest.mark.slow`; skip with `-m "not slow"` |
