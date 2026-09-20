# Agent OS

Standards discovered from this codebase, in the format Agent OS 3.0 expects.

- `standards/index.yml` names every standard in one line each.
- `standards/<area>/<standard>.md` is the standard itself.

Each one is a rule this code already follows, with the reason it exists. They are
written to be injected into an agent's context, so they are short by design: state
the rule, show it, and give the why only where the why is not obvious.

Use `/inject-standards` before working in an area, and `/discover-standards` after
a pattern has proved itself often enough to be worth writing down.
