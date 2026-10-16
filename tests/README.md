# Engine tests

The tests exercise the generic reasoning engine's satisfiability and identity-query outcomes, conflict labels, temporary-assumption isolation, tracker-name collision handling, automatic labels, timeout validation, and inconsistent base constraints.

From the repository root, install the pinned dependency and run:

```sh
.venv/bin/python main.py test
```

The top-level `main.py` resolves the `tests/` directory relative to its own location, so the command also works when invoked from another current working directory, for example:

```sh
cd /tmp
/home/jing/repo/hackathon/.venv/bin/python /home/jing/repo/hackathon/main.py test
```
