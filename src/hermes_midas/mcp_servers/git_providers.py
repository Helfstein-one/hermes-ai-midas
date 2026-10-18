"""Git provider implementations for local filesystem and remote REST services.

Supports:
- LocalFilesystemGitProvider: Direct file inspection, git CLI manipulation, and
  .midas/pull_requests/ artifact persistence for offline and local environments.
- RemoteRestGitProvider: REST API integration with Gitea and GitHub API endpoints.
"""

from __future__ import annotations

import abc
import base64
import datetime
import hashlib
import json
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

import httpx


class GitProvider(abc.ABC):
    """Abstract Git provider contract."""

    @abc.abstractmethod
    def inspect_artifact(
        self,
        repo: str,
        file_path: str,
        ref: str = "main",
    ) -> dict[str, Any]:
        """Fetch file content and metadata."""

    @abc.abstractmethod
    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        changes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a branch, commit changes, and open a Pull Request."""

    @abc.abstractmethod
    def get_file_content(
        self,
        repo: str,
        file_path: str,
        ref: str = "main",
    ) -> str:
        """Get raw file content as string."""

    @abc.abstractmethod
    def check_existing_pr(
        self,
        repo: str,
        branch: str | None = None,
        workload_id: str | None = None,
    ) -> dict[str, Any]:
        """Check for existing open pull requests."""

    @abc.abstractmethod
    def list_open_prs(self, repo: str) -> list[dict[str, Any]]:
        """List open pull requests."""


class LocalFilesystemGitProvider(GitProvider):
    """Git provider operating directly on the local filesystem and git repository."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir).resolve() if base_dir else None

    def _resolve_repo_path(self, repo: str) -> Path:
        """Resolve a repo string to an absolute filesystem Path."""
        path = Path(repo)
        if not path.is_absolute() and self.base_dir:
            path = self.base_dir / repo
        return path.resolve()

    def inspect_artifact(
        self,
        repo: str,
        file_path: str,
        ref: str = "main",
    ) -> dict[str, Any]:
        """Inspect file content from a local directory or local git tree."""
        repo_path = self._resolve_repo_path(repo)
        target_file = (repo_path / file_path).resolve()

        if ref not in ("main", "master", "HEAD"):
            staged_branch_file = (repo_path / ".midas" / "branches" / ref / file_path).resolve()
            if staged_branch_file.is_file():
                target_file = staged_branch_file

        content = ""
        exists = False
        sha = ""
        line_count = 0

        if target_file.is_file():
            try:
                content = target_file.read_text(encoding="utf-8")
                exists = True
                line_count = len(content.splitlines())
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            except (OSError, UnicodeDecodeError):
                exists = False
        elif (repo_path / ".git").is_dir():
            # Try git show if file isn't directly in working tree
            proc = subprocess.run(
                ["git", "show", f"{ref}:{file_path}"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                content = proc.stdout
                exists = True
                line_count = len(content.splitlines())
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

        return {
            "repo": str(repo),
            "file_path": file_path,
            "path": file_path,
            "ref": ref,
            "content": content,
            "exists": exists,
            "line_count": line_count,
            "sha": sha,
            "backend": "local",
        }

    def get_file_content(
        self,
        repo: str,
        file_path: str,
        ref: str = "main",
    ) -> str:
        """Retrieve file content as string."""
        artifact = self.inspect_artifact(repo, file_path, ref)
        if not artifact["exists"]:
            raise FileNotFoundError(f"File '{file_path}' not found in repo '{repo}' at ref '{ref}'.")
        return str(artifact["content"])

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        changes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a branch, write changes, commit if git repo, and persist PR artifact."""
        repo_path = self._resolve_repo_path(repo)
        repo_path.mkdir(parents=True, exist_ok=True)
        is_git = (repo_path / ".git").is_dir()

        files_changed = list((changes or {}).keys())

        if is_git:
            proc = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            original_branch = proc.stdout.strip() or base
            subprocess.run(
                ["git", "checkout", "-B", branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            for rel_path, file_content in (changes or {}).items():
                out_file = repo_path / rel_path
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_text(file_content, encoding="utf-8")
                subprocess.run(
                    ["git", "add", str(out_file)],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if files_changed:
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=Midas Bot",
                        "-c",
                        "user.email=midas@hermes.ai",
                        "commit",
                        "-m",
                        title,
                    ],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            subprocess.run(
                ["git", "checkout", original_branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            branch_dir = repo_path / ".midas" / "branches" / branch
            for rel_path, file_content in (changes or {}).items():
                staged_file = branch_dir / rel_path
                staged_file.parent.mkdir(parents=True, exist_ok=True)
                staged_file.write_text(file_content, encoding="utf-8")

        # Persist PR in .midas/pull_requests
        pr_dir = repo_path / ".midas" / "pull_requests"
        pr_dir.mkdir(parents=True, exist_ok=True)

        existing_prs = self.list_open_prs(str(repo_path))
        matching_pr = next(
            (p for p in existing_prs if p.get("branch") == branch),
            None,
        )

        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        if matching_pr:
            pr_number = matching_pr["pr_number"]
            status = "UPDATED"
        else:
            pr_numbers = [p.get("pr_number", 0) for p in existing_prs]
            pr_number = (max(pr_numbers) + 1) if pr_numbers else 1
            status = "CREATED"

        pr_metadata = {
            "pr_number": pr_number,
            "title": title,
            "body": body,
            "branch": branch,
            "target_branch": branch,
            "base": base,
            "base_branch": base,
            "status": "OPEN",
            "files_changed": files_changed,
            "changes": changes or {},
            "created_at": matching_pr.get("created_at", now_iso) if matching_pr else now_iso,
            "updated_at": now_iso,
            "backend": "local",
        }

        json_path = pr_dir / f"pr_{pr_number}.json"
        md_path = pr_dir / f"pr_{pr_number}.md"
        json_path.write_text(json.dumps(pr_metadata, indent=2), encoding="utf-8")
        md_path.write_text(body, encoding="utf-8")

        return {
            "status": status,
            "pr_url": f"file://{md_path}",
            "pr_number": pr_number,
            "branch": branch,
            "target_branch": branch,
            "base": base,
            "base_branch": base,
            "title": title,
            "body": body,
            "files_changed": files_changed,
            "backend": "local",
        }

    def list_open_prs(self, repo: str) -> list[dict[str, Any]]:
        """List all open PR records from .midas/pull_requests."""
        repo_path = self._resolve_repo_path(repo)
        pr_dir = repo_path / ".midas" / "pull_requests"
        if not pr_dir.is_dir():
            return []

        prs: list[dict[str, Any]] = []
        for json_file in sorted(pr_dir.glob("pr_*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if data.get("status") in ("OPEN", "CREATED", "UPDATED", None):
                    prs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return prs

    def check_existing_pr(
        self,
        repo: str,
        branch: str | None = None,
        workload_id: str | None = None,
    ) -> dict[str, Any]:
        """Check if an open pull request already exists matching branch or workload."""
        prs = self.list_open_prs(repo)
        for pr in prs:
            if branch and pr.get("branch") == branch:
                return {
                    "has_existing_pr": True,
                    "existing_pr_number": pr.get("pr_number"),
                    "existing_pr_url": f"file://{self._resolve_repo_path(repo)}/.midas/pull_requests/pr_{pr.get('pr_number')}.md",
                    "status": "OPEN",
                    "title": pr.get("title"),
                    "branch": pr.get("branch"),
                }
            if workload_id:
                title = pr.get("title", "")
                body = pr.get("body", "")
                pr_branch = pr.get("branch", "")
                if workload_id in title or workload_id in body or workload_id in pr_branch:
                    return {
                        "has_existing_pr": True,
                        "existing_pr_number": pr.get("pr_number"),
                        "existing_pr_url": f"file://{self._resolve_repo_path(repo)}/.midas/pull_requests/pr_{pr.get('pr_number')}.md",
                        "status": "OPEN",
                        "title": title,
                        "branch": pr_branch,
                    }

        return {
            "has_existing_pr": False,
            "existing_pr_number": None,
            "existing_pr_url": None,
            "status": None,
        }


class RemoteRestGitProvider(GitProvider):
    """Git provider connecting to Gitea or GitHub REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        provider_type: str = "auto",
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("GITEA_URL") or os.environ.get("GITHUB_API_URL") or "http://localhost:3000").rstrip("/")
        self.token = token or os.environ.get("GITEA_TOKEN") or os.environ.get("GITHUB_TOKEN") or "midas-admin-token-12345"
        self.provider_type = provider_type
        self.timeout = timeout

    def _parse_repo(self, repo: str) -> tuple[str, str]:
        """Extract (owner, repo_name) from URL or owner/repo format."""
        clean_repo = repo.strip("/")
        if "://" in clean_repo:
            parsed = urllib.parse.urlparse(clean_repo)
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(parts) >= 2:
                return parts[-2], parts[-1].removesuffix(".git")
        parts = clean_repo.split("/")
        if len(parts) == 2:
            return parts[0], parts[1].removesuffix(".git")
        return "hermes", clean_repo.removesuffix(".git")

    def _get_headers(self) -> dict[str, str]:
        """Build HTTP authentication and content headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    def inspect_artifact(
        self,
        repo: str,
        file_path: str,
        ref: str = "main",
    ) -> dict[str, Any]:
        """Inspect file content via Gitea or GitHub REST API."""
        owner, repo_name = self._parse_repo(repo)
        url = f"{self.base_url}/api/v1/repos/{owner}/{repo_name}/raw/{file_path}"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    url,
                    headers=self._get_headers(),
                    params={"ref": ref},
                )
                if resp.status_code == 200:
                    content = resp.text
                    return {
                        "repo": repo,
                        "file_path": file_path,
                        "path": file_path,
                        "ref": ref,
                        "content": content,
                        "exists": True,
                        "line_count": len(content.splitlines()),
                        "sha": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "backend": "remote_rest",
                    }
                elif resp.status_code == 404:
                    return {
                        "repo": repo,
                        "file_path": file_path,
                        "path": file_path,
                        "ref": ref,
                        "content": "",
                        "exists": False,
                        "line_count": 0,
                        "sha": "",
                        "backend": "remote_rest",
                    }
                else:
                    return {
                        "repo": repo,
                        "file_path": file_path,
                        "path": file_path,
                        "ref": ref,
                        "content": "",
                        "exists": False,
                        "line_count": 0,
                        "sha": "",
                        "error": f"HTTP {resp.status_code}: {resp.text}",
                        "backend": "remote_rest",
                    }
        except (httpx.HTTPError, OSError, RuntimeError) as e:
            return {
                "repo": repo,
                "file_path": file_path,
                "path": file_path,
                "ref": ref,
                "content": "",
                "exists": False,
                "line_count": 0,
                "sha": "",
                "error": str(e),
                "backend": "remote_rest",
            }

    def get_file_content(
        self,
        repo: str,
        file_path: str,
        ref: str = "main",
    ) -> str:
        """Retrieve raw file content."""
        artifact = self.inspect_artifact(repo, file_path, ref)
        if not artifact["exists"]:
            raise FileNotFoundError(f"File '{file_path}' not found on remote repo '{repo}' (ref: {ref}).")
        return str(artifact["content"])

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        changes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a branch, update files, and submit a PR via Gitea/GitHub REST API."""
        owner, repo_name = self._parse_repo(repo)
        headers = self._get_headers()

        with httpx.Client(timeout=self.timeout) as client:
            # 1. Create branch from base
            create_branch_url = f"{self.base_url}/api/v1/repos/{owner}/{repo_name}/branches"
            client.post(
                create_branch_url,
                headers=headers,
                json={"new_branch_name": branch, "old_branch_name": base},
            )

            # 2. Update files on the branch
            files_changed = list((changes or {}).keys())
            for path, content in (changes or {}).items():
                content_b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
                file_url = f"{self.base_url}/api/v1/repos/{owner}/{repo_name}/contents/{path}"
                client.post(
                    file_url,
                    headers=headers,
                    json={
                        "branch": branch,
                        "content": content_b64,
                        "message": f"FinOps Midas Touch refactor: {path}",
                    },
                )

            # 3. Create pull request
            pull_url = f"{self.base_url}/api/v1/repos/{owner}/{repo_name}/pulls"
            pr_resp = client.post(
                pull_url,
                headers=headers,
                json={
                    "title": title,
                    "body": body,
                    "head": branch,
                    "base": base,
                },
            )

            if pr_resp.status_code in (200, 201):
                data = pr_resp.json()
                return {
                    "status": "CREATED",
                    "pr_url": data.get("html_url") or f"{self.base_url}/{owner}/{repo_name}/pulls/{data.get('number', 1)}",
                    "pr_number": data.get("number", 1),
                    "branch": branch,
                    "target_branch": branch,
                    "base": base,
                    "base_branch": base,
                    "title": title,
                    "body": body,
                    "files_changed": files_changed,
                    "backend": "remote_rest",
                }
            else:
                return {
                    "status": "ERROR",
                    "error": f"Failed to create PR: HTTP {pr_resp.status_code} - {pr_resp.text}",
                    "branch": branch,
                    "target_branch": branch,
                    "base": base,
                    "base_branch": base,
                    "title": title,
                    "files_changed": files_changed,
                    "backend": "remote_rest",
                }

    def list_open_prs(self, repo: str) -> list[dict[str, Any]]:
        """List open pull requests from remote REST API."""
        owner, repo_name = self._parse_repo(repo)
        pull_url = f"{self.base_url}/api/v1/repos/{owner}/{repo_name}/pulls"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    pull_url,
                    headers=self._get_headers(),
                    params={"state": "open"},
                )
                if resp.status_code == 200:
                    return resp.json()
        except (httpx.HTTPError, OSError):
            return []
        return []

    def check_existing_pr(
        self,
        repo: str,
        branch: str | None = None,
        workload_id: str | None = None,
    ) -> dict[str, Any]:
        """Check if an open pull request already exists on remote server."""
        prs = self.list_open_prs(repo)
        for pr in prs:
            pr_head = pr.get("head", {}).get("ref") or pr.get("branch")
            if branch and pr_head == branch:
                return {
                    "has_existing_pr": True,
                    "existing_pr_number": pr.get("number"),
                    "existing_pr_url": pr.get("html_url"),
                    "status": "OPEN",
                    "title": pr.get("title"),
                    "branch": pr_head,
                }
            if workload_id:
                title = pr.get("title", "")
                body = pr.get("body", "")
                if workload_id in title or workload_id in body or (pr_head and workload_id in pr_head):
                    return {
                        "has_existing_pr": True,
                        "existing_pr_number": pr.get("number"),
                        "existing_pr_url": pr.get("html_url"),
                        "status": "OPEN",
                        "title": title,
                        "branch": pr_head,
                    }
        return {
            "has_existing_pr": False,
            "existing_pr_number": None,
            "existing_pr_url": None,
            "status": None,
        }


def get_git_provider(
    repo_path_or_url: str = "",
    backend: str | None = None,
) -> GitProvider:
    """Factory creating the appropriate GitProvider instance based on configuration."""
    if backend:
        backend_lower = backend.lower()
        if backend_lower in ("remote", "remote_rest", "gitea", "github"):
            return RemoteRestGitProvider()
        if backend_lower in ("local", "filesystem"):
            return LocalFilesystemGitProvider()

    # Auto-detection
    if repo_path_or_url.startswith(("http://", "https://", "git@")):
        return RemoteRestGitProvider(base_url=repo_path_or_url)

    return LocalFilesystemGitProvider()
