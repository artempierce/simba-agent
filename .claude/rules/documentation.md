---
paths:
  - "backend/**/*.py"
  - "frontend/src/**/*.{ts,tsx}"
---

# Documentation standard (required for every code change)

This overrides any general "keep comments minimal" preference. The owner learns by reading the code.

1. **Every file** starts with a header comment: what the file is, where it sits in the message flow,
   and the key idea a reader needs.
2. **Every function / component** has a docstring: what it does, inputs and outputs, and *why* it
   exists or is shaped that way. Add a small example when it helps (see `model.cost_usd`).
3. **Main logic** gets numbered step comments that match the docstring's steps. Explain a library
   concept on first use (reducers, stream modes, structured output, SSE…).
4. **Constants** say what they control and why that value.
5. **Tests** have a docstring saying what behaviour they protect and why it matters.
6. Plain words for a learner; don't comment the obvious.
7. Keep `README.md` in sync in the same change.
