# Transform Engines

Two implementations of one port: `SparkEngine` does the work, `StreamingEngine` is
the reference the tests compare it against, and the fallback.

## Rules every engine obeys

- **Every cell is text.** Nothing is type-converted: `00123` never becomes `123`.
- **The replacement is literal.** `$1` and `\1` stay as written (Java reads them as
  group references, so they are escaped).
- **Empty cells are `None`**, quoted or not. Ragged rows are padded and trimmed.
  Blank lines are not rows. "Changed" means the text differs, not that a pattern
  matched.
- **Column names match exactly first**, then ignoring case, spaces, underscores and
  hyphens (`domain/tables.py: column_indexes`). An unmatched name fails the job; it
  never silently means "every column".

## Shape

`open(job)` yields a handle for the length of the job: `columns`, `sample()`,
`distinct_values()`, `rewrite(operations)`. An operation is `Replace`, `MaskCells`
or `MapValues`. Add an operation, not an engine method.

## Spark

- Built-ins only (`regexp_replace`). A Python UDF ships every row out of the JVM.
- `(?Ud)` pins Java's regex to Python's semantics.
- Map-only by default; the one shuffle is counting distinct values, and a mapping
  is applied with a broadcast join so rows are never shuffled.
- Bind SQL parameters **by name**: PySpark 4.1 binds positional `?` in reverse,
  silently.
- One Spark application per job, started lazily at the first pass.
