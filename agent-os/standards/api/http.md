# HTTP Layer

Thin views. A view validates, calls one service method and shapes the response.

- **Serializers validate; services decide.** A rule that needs the database or a
  port lives in the service.
- **Named fields only** in responses (`_job_json`, `_describe`). Never
  `dataclasses.asdict()`: it would serialise credentials and connection IDs.
- **One error shape**, from `api/exception_handler.py`:
  `{"error": {"code", "message"}}`, with a status per error type. DRF's own errors
  are wrapped in the same envelope.
- **JSON only** (`DEFAULT_PARSER_CLASSES = [JSONParser]`): a browser can post an
  HTML form cross-site without a preflight, which would let another site connect a
  visitor's browser to an attacker's bucket.
- **Submit returns `202`** with the job, never the work.
- **The connection cookie** is `HttpOnly`, `SameSite=Strict`, `Secure` outside
  DEBUG, `Path=/api`, no `Max-Age` (the vault is the only expiry clock).
- **Throttle what costs money**: connecting (stolen-key testing) and submitting.
