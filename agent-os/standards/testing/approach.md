# Testing

One rule per layer:

| Layer | Tested with |
|---|---|
| domain, services | in-memory fakes (`tests/fakes.py`) |
| adapters | the real thing against a fake backend (moto), or the **wire** replaced (`httpx2.MockTransport`) |
| task layer | the real Celery task, service, repository and result store |
| engines | every behaviour case runs on **both** engines |

- **No test reaches the network or a language model.** `settings_test.py` blanks the
  API key so a developer's environment cannot leak into a run.
- **Pin what leaves the process.** An adapter test asserts the exact shape of the
  request, so sending more would have to be done on purpose.
- **The oracle.** Every engine case is parametrised over both engines, and a
  differential test compares them on generated messy data. This is what caught a
  silent PySpark parameter-binding bug.
- **Prove a test works by breaking its guarantee** on purpose (mutation check)
  before trusting it. If nothing fails, the test is decoration.
- **A skip in CI is a failure.** Tests that need a JVM skip locally with a message
  and raise in CI.
- Name a test after the behaviour it protects, not the function it calls.
