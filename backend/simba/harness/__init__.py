"""
simba/harness — the checks that guard what Simba reads and writes, and the runner that wires them
into the graph as hooks (#32, D22/D23/D26).

  guard.py        pure, code-only checks on the incoming message: size, injection regexes
  classifier.py   the local prompt-injection model, wrapped as a hook (#8)
  output_guard.py pure, code-only checks on the finished reply: secrets, internal tags, prompt leaks
  hooks.py        `HookResult`, `Hook` and `run_hooks`: the shared shape every check above returns,
                  and the loop that runs a list of them at one hook point
  settings.py     which hooks run at each hook point, in which order — the one place that lists them

`simba/nodes/hook_points.py` is the LangGraph glue: it turns `settings.py`'s lists into the graph's
`before_model` / `after_model` nodes.
"""
