#!/usr/bin/env python3
"""Run lint, format, type and YAML checks on a project and summarize results.

Usage:
    run_checks.py <project_dir> [--venv PATH] [--out DIR] [--only ruff,format,mypy,yaml]

Every check runs even if an earlier one fails. Full tool output goes to
<out>/<check>.log; a machine-readable summary goes to <out>/summary.json and
is also printed to stdout. Exit code is 0 only if every check that ran passed.

Standard library only, so it runs with any Python 3.8+.
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_YAMLLINT = SKILL_DIR / "assets" / "yamllint.yaml"
SKIP_DIRS = {".venv", "venv", "env", ".git", "node_modules", "build", "dist",
             ".tox", ".nox", ".mypy_cache", ".ruff_cache", "__pycache__",
             ".check-results", "site-packages"}


def tool(venv: Path, name: str) -> str:
    candidate = venv / "bin" / name
    return str(candidate) if candidate.exists() else name


def run(cmd: list[str], cwd: Path, log: Path, stdout_only: bool = False) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    output = proc.stdout + (("\n" + proc.stderr) if proc.stderr.strip() else "")
    log.write_text(f"$ {' '.join(cmd)}\n\n{output}")
    return proc.returncode, (proc.stdout if stdout_only else output)


def walk(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    found = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and path.suffix in suffixes:
            found.append(path)
    return sorted(found)


# --- individual checks -----------------------------------------------------

def check_ruff(root: Path, venv: Path, out: Path) -> dict:
    code, output = run([tool(venv, "ruff"), "check", "--output-format", "json", "."],
                       root, out / "ruff.log", stdout_only=True)
    try:
        issues = json.loads(output or "[]")
    except json.JSONDecodeError:
        return {"status": "error", "detail": "ruff output was not JSON; see ruff.log"}
    by_rule: dict[str, int] = {}
    for item in issues:
        by_rule[item.get("code") or "syntax"] = by_rule.get(item.get("code") or "syntax", 0) + 1
    fixable = sum(1 for i in issues if i.get("fix"))
    sample = [f"{Path(i['filename']).relative_to(root)}:{i['location']['row']} "
              f"{i.get('code') or 'syntax'} {i['message']}" for i in issues[:15]]
    return {"status": "pass" if not issues else "fail", "count": len(issues),
            "fixable": fixable, "by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
            "sample": sample}


def check_format(root: Path, venv: Path, out: Path) -> dict:
    code, output = run([tool(venv, "ruff"), "format", "--check", "."], root, out / "format.log")
    if code not in (0, 1):
        return {"status": "error", "detail": "ruff format failed; see format.log"}
    # Older ruff: "Would reformat: path". Newer ruff: a diff block headed "--> path:line:col".
    files = re.findall(r"^Would reformat: (.+)$", output, re.M)
    files += [f for f in re.findall(r"^\s*--> (.+?):\d+:\d+", output, re.M) if f not in files]
    m = re.search(r"(\d+) files? would be reformatted", output)
    count = int(m.group(1)) if m else len(files)
    return {"status": "pass" if code == 0 else "fail", "count": count, "sample": files[:15]}


def has_mypy_config(root: Path) -> bool:
    if (root / "mypy.ini").exists() or (root / ".mypy.ini").exists():
        return True
    pyproject = root / "pyproject.toml"
    if pyproject.exists() and re.search(r"^\[tool\.mypy\]", pyproject.read_text(), re.M):
        return True
    setup_cfg = root / "setup.cfg"
    if setup_cfg.exists():
        cfg = configparser.ConfigParser()
        try:
            cfg.read(setup_cfg)
            return cfg.has_section("mypy")
        except configparser.Error:
            pass
    return False


def check_mypy(root: Path, venv: Path, out: Path) -> dict:
    if not walk(root, (".py",)):
        return {"status": "skipped", "detail": "no Python files"}
    cmd = [tool(venv, "mypy"), "--python-executable", tool(venv, "python"),
           "--show-error-codes"]
    configured = has_mypy_config(root)
    if not configured:
        # Without project config, missing third-party stubs would drown out real findings.
        cmd += ["--ignore-missing-imports"]
    cmd += ["--exclude", r"(^|/)(\.venv|venv|build|dist|\.tox)/", "."]
    code, output = run(cmd, root, out / "mypy.log")
    errors = [line for line in output.splitlines() if ": error:" in line]
    if code not in (0, 1) or ("error:" in output and not errors and code != 0):
        return {"status": "error", "detail": "mypy could not run; see mypy.log",
                "sample": output.strip().splitlines()[-5:]}
    by_code: dict[str, int] = {}
    for line in errors:
        m = re.search(r"\[([\w-]+)\]\s*$", line)
        key = m.group(1) if m else "other"
        by_code[key] = by_code.get(key, 0) + 1
    return {"status": "pass" if not errors else "fail", "count": len(errors),
            "used_project_config": configured,
            "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
            "sample": errors[:15]}


def check_yaml(root: Path, venv: Path, out: Path) -> dict:
    files = walk(root, (".yaml", ".yml"))
    if not files:
        return {"status": "skipped", "detail": "no YAML files"}
    project_cfg = next((root / n for n in (".yamllint", ".yamllint.yaml", ".yamllint.yml")
                        if (root / n).exists()), None)
    cfg = project_cfg or DEFAULT_YAMLLINT
    cmd = [tool(venv, "yamllint"), "-f", "parsable", "-c", str(cfg)] + \
          [str(f.relative_to(root)) for f in files]
    code, output = run(cmd, root, out / "yaml.log")
    lines = [l for l in output.splitlines() if re.match(r".+:\d+:\d+: \[(error|warning)\]", l)]
    errors = [l for l in lines if "[error]" in l]
    warnings = [l for l in lines if "[warning]" in l]
    syntax = [l for l in errors if "syntax error" in l]
    return {"status": "fail" if errors else "pass", "files": len(files),
            "errors": len(errors), "warnings": len(warnings), "syntax_errors": len(syntax),
            "used_project_config": project_cfg is not None,
            "sample": list(dict.fromkeys(syntax + errors + warnings))[:15]}


CHECKS = {"ruff": check_ruff, "format": check_format, "mypy": check_mypy, "yaml": check_yaml}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--venv", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=",".join(CHECKS))
    args = ap.parse_args()

    root = Path(args.project).resolve()
    venv = Path(args.venv).resolve() if args.venv else root / ".venv"
    out = Path(args.out).resolve() if args.out else root / ".check-results"
    out.mkdir(parents=True, exist_ok=True)

    results = {}
    for name in [c.strip() for c in args.only.split(",") if c.strip()]:
        try:
            results[name] = CHECKS[name](root, venv, out)
        except FileNotFoundError as e:
            results[name] = {"status": "error", "detail": f"tool not found: {e.filename}"}

    summary = {"project": str(root), "logs": str(out), "checks": results}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if all(r["status"] in ("pass", "skipped") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
