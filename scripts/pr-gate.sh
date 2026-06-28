#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel)"
cd "$ROOT_DIR"

if [[ -z "${VIRTUAL_ENV:-}" && -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

BASE_BRANCH="main"
TIMEOUT_SECONDS="1800"
NO_OPEN="false"

usage() {
  printf '%s\n' "Usage: scripts/pr-gate.sh [--no-open] [--timeout SECONDS] [--base BRANCH]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-open)
      NO_OPEN="true"
      shift
      ;;
    --timeout)
      TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --base)
      BASE_BRANCH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '%s\n' "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${TIMEOUT_SECONDS}" || ! "${TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]]; then
  printf '%s\n' "--timeout expects an integer number of seconds" >&2
  exit 2
fi

if [[ ! -f ".opencode/github-token" && -z "${GH_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
  printf '%s\n' "Missing GitHub token: set GH_TOKEN/GITHUB_TOKEN or keep .opencode/github-token in place." >&2
  exit 1
fi

printf '%s\n' "Running preflight checks"
make preflight

export CARDRE_GIT_ROOT="$ROOT_DIR"
export CARDRE_BASE_BRANCH="$BASE_BRANCH"
export CARDRE_TIMEOUT_SECONDS="$TIMEOUT_SECONDS"
export CARDRE_NO_OPEN="$NO_OPEN"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(os.environ["CARDRE_GIT_ROOT"])
BASE_BRANCH = os.environ["CARDRE_BASE_BRANCH"]
TIMEOUT_SECONDS = int(os.environ["CARDRE_TIMEOUT_SECONDS"])
NO_OPEN = os.environ["CARDRE_NO_OPEN"].lower() == "true"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    token_path = ROOT / ".opencode" / "github-token"
    TOKEN = token_path.read_text(encoding="utf-8").strip()


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def api(method: str, path: str, payload: dict | None = None) -> object:
    url = f"https://api.github.com{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cardre-pr-gate",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code} {body}") from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def parse_origin(url: str) -> tuple[str, str]:
    https_match = re.match(r"https://github.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1), https_match.group(2)
    ssh_match = re.match(r"git@github.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)
    raise RuntimeError(f"Unsupported origin URL: {url}")


def write_job_log(pr_number: int, job: dict) -> Path:
    log_dir = ROOT / ".opencode" / "pr-gate-logs" / str(pr_number)
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", job["name"]).strip("-") or f"job-{job['id']}"
    log_path = log_dir / f"{safe_name}.log"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cardre-pr-gate",
    }
    req = urllib.request.Request(job["logs_url"], headers=headers)
    raw = urllib.request.urlopen(req, timeout=60).read()
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            if not members:
                log_path.write_text("<empty log archive>\n", encoding="utf-8")
            else:
                content = archive.read(members[0]).decode("utf-8", errors="replace")
                log_path.write_text(content, encoding="utf-8")
    else:
        log_path.write_bytes(raw)
    return log_path


def latest_ci_run(owner: str, repo: str, sha: str) -> dict | None:
    runs = api("GET", f"/repos/{owner}/{repo}/actions/runs?head_sha={sha}&per_page=20")
    workflow_runs = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    if not workflow_runs:
        return None
    return sorted(workflow_runs, key=lambda item: item.get("created_at", ""), reverse=True)[0]


def ensure_pr(owner: str, repo: str, branch: str) -> dict:
    query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open", "base": BASE_BRANCH, "per_page": "1"})
    prs = api("GET", f"/repos/{owner}/{repo}/pulls?{query}")
    if isinstance(prs, list) and prs:
        return prs[0]
    if NO_OPEN:
        raise RuntimeError(f"No open PR found for branch {branch!r} and --no-open was set")
    title = run_git("log", "-1", "--pretty=%s") or f"Update {branch}"
    body = "Opened by scripts/pr-gate.sh after local preflight passed."
    return api(
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        {
            "title": title,
            "head": branch,
            "base": BASE_BRANCH,
            "body": body,
            "maintainer_can_modify": True,
        },
    )


origin = run_git("remote", "get-url", "origin")
owner, repo = parse_origin(origin)
branch = run_git("branch", "--show-current")
if not branch:
    raise RuntimeError("Detached HEAD: checkout a branch before running scripts/pr-gate.sh")

print(f"Pushing {branch} to origin")
subprocess.run(["git", "push", "-u", "origin", branch], cwd=ROOT, check=True)

pr = ensure_pr(owner, repo, branch)
pr_number = int(pr["number"])
pr_url = pr["html_url"]
print(f"Tracking PR #{pr_number}: {pr_url}")

deadline = time.time() + TIMEOUT_SECONDS
sleep_seconds = 10

while True:
    if time.time() > deadline:
        print(f"CI still running after {TIMEOUT_SECONDS} seconds for PR #{pr_number}", file=sys.stderr)
        sys.exit(3)

    pr = api("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
    head_sha = pr["head"]["sha"]
    run = latest_ci_run(owner, repo, head_sha)
    if run is None:
        print("Waiting for GitHub Actions run to appear...")
        time.sleep(sleep_seconds)
        continue

    if run.get("status") != "completed":
        print(f"CI status: {run.get('status')} ({run.get('name')})")
        time.sleep(sleep_seconds)
        continue

    jobs = api("GET", f"/repos/{owner}/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
    job_items = jobs.get("jobs", []) if isinstance(jobs, dict) else []
    if not job_items:
        print("Waiting for workflow jobs to materialize...")
        time.sleep(sleep_seconds)
        continue

    failed_jobs = []
    pending_jobs = []
    for job in job_items:
        if job.get("status") != "completed":
            pending_jobs.append(job)
            continue
        if job.get("conclusion") not in {"success", "neutral", "skipped"}:
            failed_jobs.append(job)

    if pending_jobs:
        print("Waiting for jobs: " + ", ".join(job["name"] for job in pending_jobs))
        time.sleep(sleep_seconds)
        continue

    if failed_jobs:
        print("CI RED")
        print(pr_url)
        for job in failed_jobs:
            log_path = write_job_log(pr_number, job)
            print(f"{job['name']}: {job.get('conclusion')} -> {log_path}")
        sys.exit(1)

    print("CI GREEN")
    print(pr_url)
    print("Ready for human review")
    break
PY
