# Comments

Comments say **why**, never what the code already says.

```python
# A GET first: its error body names the exact problem (bad key, bad signature, no
# such bucket, no permission). A HEAD can only say 403 or 404.
client.list_objects_v2(Bucket=bucket, MaxKeys=1)
```

- Prefer a comment that records a decision, a measurement or a trap that cost a
  round trip. Delete one that restates the line below it.
- A non-obvious behaviour of a library gets a comment naming what was observed,
  not what the docs claim.

## ponytail: markers

A deliberate shortcut with a known ceiling is marked, with its upgrade trigger:

```python
# ponytail: a local folder, so web and workers must share a disk (one Docker
# volume today). Move to object storage when they run on separate machines.
```

Format: `ponytail: <the ceiling>, <what should trigger revisiting it>`. A marker
with no trigger is the kind that rots. `/ponytail-debt` harvests these into a
ledger, which is also where the README's trade-offs come from.
