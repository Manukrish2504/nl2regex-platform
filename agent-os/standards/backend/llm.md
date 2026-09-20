# Using a Language Model

## Send the least the question allows

| Question | What is sent |
|---|---|
| Write a regex from a sentence | the sentence, nothing from the file |
| Which columns hold personal data | column names and value *shapes* (`aaaa.aaa@aaaaaaa.aaa`) |
| Standardise a column | that one column's distinct values, capped |

A cap is a privacy guard first and a cost guard second: a column with more than 300
distinct values is not categorical, and is refused *before* anything is sent.

## Never per row

The model works on something the size of the schema or of the distinct values.
Spark does the work that is the size of the data.

## The answer is untrusted

- A regex must compile, avoid Python-only syntax, pass the examples the model wrote
  for it, and survive a timed dry run in a killable subprocess.
- A finding must name a real column; a mapping key must be one of the values sent.
- A failure goes back to the model with the reason, three attempts at most. Only a
  verified answer is cached or run.

## Cache and configuration

Key = hash of exactly what was sent + the model + `INSTRUCTIONS_VERSION`. **Changing
the instructions requires bumping that version** and re-running
`scripts/eval_prompts.py`, which is how the model was chosen in the first place.
Structured outputs (`messages.parse`), thinking disabled, and one shared
`claude_api.ask()` so every adapter translates errors the same way.
