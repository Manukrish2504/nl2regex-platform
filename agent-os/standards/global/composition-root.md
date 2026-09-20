# Composition Root

`backend/config/container.py` is the only place that wires adapters into services.

```python
@cache
def job_service() -> JobService:
    return JobService(connections=connection_service(), jobs=DjangoJobRepository(), ...)
```

- Views and Celery tasks call a factory. They never construct an adapter.
- `@cache` makes each service a singleton; tests clear it (`factory.cache_clear()`
  in `tests/conftest.py`) so settings changes take effect.
- Import a heavy adapter *inside* the factory (PySpark, anthropic), so a process
  that does not use it never loads it.

**Why:** one file to read to know what the running system is made of, and one file
to change to swap an implementation.
