# Jobs

## The state machine lives on the entity

`domain/jobs.py` owns every allowed move (`start`, `succeed`, `fail`, `cancel`,
`requeue_for_retry`) and raises `InvalidTransition` for the rest. No service
assigns `job.status` directly.

## Every change is a compare-and-set

```sql
UPDATE jobs SET ... WHERE id = ? AND status = ? AND attempts = ?
```

Two workers, or a cancel racing a finish, cannot both win, and no locks are
needed. `save()` returns whether the row changed; the caller must handle `False`.

- **Progress writes touch only the progress columns.** A full-row save from a
  worker would erase a `cancel_requested` flag the API had just set.
- `cancel_requested` is written by `request_cancel()` alone, and is excluded from
  `_MUTABLE_FIELDS`.

## Ownership

A job belongs to the connection that created it. Another connection gets a 404,
never a 403: a job that is not yours looks exactly like one that does not exist.

## Celery

`acks_late` + `reject_on_worker_lost`, `worker_prefetch_multiplier=1`, a Redis
visibility timeout above the hard time limit, and a stale-job rule applied on read
(the hard limit acknowledges the message, so nothing redelivers it). A redelivered
message takes over a `RUNNING` job; a first delivery never does.
