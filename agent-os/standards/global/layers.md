# Layers and Import Direction

Four layers. Imports only ever point inward.

```
api/ tasks/        presentation: translate and delegate, nothing else
services/          use-cases: stdlib + domain only
domain/            entities, errors, ports (typing.Protocol): stdlib only
infrastructure/    adapters: boto3, Django ORM, Celery, PySpark, anthropic
```

- `domain/` imports nothing but the standard library and itself.
- `services/` may import `domain/`. Never `infrastructure/`, never Django.
- `api/` and `tasks/` import `config.container` and `domain/`. Never `infrastructure/`.
- `infrastructure/` implements the ports the domain declares.

`backend/tests/test_architecture.py` parses every import with `ast` and fails the
build when a rule is broken. Add the rule there before arguing about it in review.

**Why:** the brief weights "a clear, deliberate architecture" heavily, and the rule
is what lets a service be tested with small fakes and an engine be swapped
(streaming to PySpark) without touching a use-case.
