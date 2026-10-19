---
name: python-env-check
description: Set up a Python virtual environment for a code base, install its dependencies (auto-detecting uv, Poetry or pip), then run lint, formatting, type-checking and YAML checks and summarize what's wrong. Use whenever the user wants to check, audit, health-check or "run the checks on" a Python project or repo — a GitHub URL, an uploaded zip, or a folder — or asks to set up a venv and run ruff, mypy, yamllint, linting or type checking across a whole code base, even if they don't say "virtual environment". For a single pasted snippet or one .py file, a lighter lint pass is enough.
---

# Python environment + code checks

Gets a Python project into a clean, isolated environment and runs four checks against it:

| Check  | Tool                  | Catches                                               |
|--------|-----------------------|-------------------------------------------------------|
| ruff   | `ruff check`          | Bugs and lint: unused imports, undefined names, etc.  |
| format | `ruff format --check` | Files that don't match the formatter's style          |
| mypy   | `mypy`                | Type errors                                           |
| yaml   | `yamllint`            | Broken or badly-formed YAML (CI configs, settings)    |

The point of building a real venv (rather than running the tools globally) is that mypy needs the project's actual dependencies installed to check types correctly, and the project's own tool settings in `pyproject.toml`, `setup.cfg`, `mypy.ini` or `.yamllint` should be honoured. The bundled scripts handle both.

## 1. Get the code into a working folder

- **GitHub repo**: clone it (shallow is fine: `git clone --depth 1 <url> <dir>`). If the shell can't reach GitHub, try adding the repo to the session; failing that, ask the user to upload a zip.
- **Uploaded zip/tarball**: extract into its own new, empty directory. Many archives wrap everything in one top-level folder — use that folder as the project root.
- **Uploaded loose files**: copy them into a new directory, never check them in place.

The project root is the directory containing `pyproject.toml`, `setup.py`, `requirements*.txt` or similar. If there are several (a monorepo), ask which one or check each separately.

Installing a project's dependencies can run its build code, so treat a repo the user doesn't own with the same care as any downloaded code: work inside the workspace, not on their machine, unless they've asked otherwise.

## 2. Build the environment

```bash
bash <skill-dir>/scripts/setup_env.sh <project_dir>
```

It picks the manager the project already uses — `uv.lock` → uv, `poetry.lock` or `[tool.poetry]` → Poetry, otherwise a plain `.venv` with pip installing the package (trying `[dev]`-style extras first) and any `requirements*.txt` — then adds ruff, mypy and yamllint into that same venv. The last two lines of output are `MANAGER=…` and `VENV=…`.

If installation fails, read the error before retrying. Common causes and fixes:
- **Needs a different Python** (`requires-python` mismatch): `uv python install <version>` then re-run, or tell the user.
- **System library missing** (e.g. building psycopg2, lxml): try the `-binary` wheel variant, or note it and continue — the lint, format and YAML checks don't need dependencies installed; only mypy's accuracy suffers.
- **Private package index**: say so and continue with what installed.

A partial install is still worth checking. Note the gap in the summary rather than stopping.

## 3. Run the checks

```bash
python3 <skill-dir>/scripts/run_checks.py <project_dir>
```

Every check runs even if one fails. Output is a JSON summary (also saved to `<project_dir>/.check-results/summary.json`), with full tool output in `.check-results/<check>.log`. Use `--only ruff,mypy` to run a subset when the user asks for particular checks.

Behaviour worth knowing:
- Project config always wins. With no mypy config, `--ignore-missing-imports` is added so missing third-party stubs don't swamp real findings. With no `.yamllint`, the bundled `assets/yamllint.yaml` is used: it keeps real problems (syntax errors, duplicate keys, bad indentation) as errors and downgrades style nits to warnings.
- mypy `import-untyped` errors mean a dependency ships without type hints. If the project's config makes these errors, install the stubs (`<venv>/bin/mypy --install-types --non-interactive`, or `pip install types-<pkg>`) and re-run mypy, then report that you did so — those are environment gaps, not code problems.
- Checks report `skipped` when there's nothing to check (e.g. no YAML files), and `error` when the tool itself couldn't run — that's different from finding problems, so say which.

When a count is large, open the relevant log and look at the actual findings before summarizing. A sample of 15 from the JSON is a start, but the user benefits most from knowing *what kind* of problems dominate and whether any look like real bugs.

## 4. Report back in chat

Keep it short and lead with the verdict. Shape:

```
**<project name>** — 2 of 4 checks passed  (env: Poetry, Python 3.12)

✅ Formatting — clean
✅ YAML — 6 files, no errors (3 style warnings)
❌ Lint — 23 issues (19 auto-fixable). Mostly unused imports (F401 ×14); 2 undefined names in `app/routes.py` look like real bugs.
❌ Types — 8 errors, 5 of them in `services/billing.py` (passing `str | None` where `str` is expected)

Worth fixing first:
- `app/routes.py:42` F821 undefined name `reqest` — typo, will crash at runtime
- `services/billing.py:88` arg-type: `customer.email` may be None
```

Guidelines:
- Separate likely bugs (undefined names, syntax errors, YAML syntax errors, `None` misuse) from style noise. The user's next action depends on that split.
- Mention how many issues are auto-fixable, and offer to fix them (`ruff check --fix`, `ruff format`) — but don't modify the user's files unless they ask.
- Name anything that limited the run: deps that failed to install, a check that errored, the project config that was used or absent.
- Point to `.check-results/` only if the user will want the full logs; if the code was uploaded, offer to send the logs as files.
- End with one natural next step (usually: "want me to apply the auto-fixes and look at the type errors?").
