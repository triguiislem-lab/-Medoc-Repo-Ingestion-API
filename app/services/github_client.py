from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class GitHubFile:
    path: str
    sha: str | None
    text: str
    html_url: str | None = None
    download_url: str | None = None
    content_type: str | None = None


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": settings.http_user_agent,
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    async def compare_commits(self, owner: str, repo: str, before: str, after: str) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/compare/{before}...{after}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_latest_branch_commit(self, owner: str, repo: str, branch: str) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_text_file(self, owner: str, repo: str, path: str, ref: str) -> GitHubFile:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers, params={"ref": ref})
            response.raise_for_status()
            payload = response.json()

        encoding = payload.get("encoding")
        content = payload.get("content") or ""
        if encoding == "base64":
            text = base64.b64decode(content).decode("utf-8")
        else:
            text = content

        return GitHubFile(
            path=payload["path"],
            sha=payload.get("sha"),
            text=text,
            html_url=payload.get("html_url"),
            download_url=payload.get("download_url"),
            content_type=None,
        )
