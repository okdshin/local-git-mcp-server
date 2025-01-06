import json
import logging
from datetime import datetime
from typing import Any
from pathlib import Path
from git import Repo
from git.exc import GitCommandError
from pydantic import AnyUrl
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent, ImageContent, EmbeddedResource

# ログの準備
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("git-server")


class GitServer:
    def __init__(self, repositories_dir: str = "./repositories"):
        self.repositories_dir = Path(repositories_dir)
        self.repositories_dir.mkdir(parents=True, exist_ok=True)
        self.app = Server("git-server")
        self._setup_routes()

    def _setup_routes(self):
        @self.app.list_resources()
        async def list_resources() -> list[Resource]:
            resources = []
            for repo_path in self.repositories_dir.glob("*"):
                if repo_path.is_dir() and (repo_path / ".git").exists():
                    uri = AnyUrl(f"git://{repo_path.name}")
                    resources.append(
                        Resource(
                            uri=uri,
                            name=f"Git repository dir: {repo_path.absolute()}",
                            mimeType="application/x-git",
                            description=f"Local git repository at {repo_path}",
                        )
                    )
            return resources

        @self.app.read_resource()
        async def read_resource(uri: AnyUrl) -> str:
            if not str(uri).startswith("git://"):
                raise ValueError(f"Unknown resource: {uri}")

            repo_name = str(uri).split("://")[1]
            repo_path = self.repositories_dir / repo_name

            if not repo_path.exists() or not (repo_path / ".git").exists():
                raise ValueError(f"Repository not found: {repo_name}")

            try:
                repo = Repo(repo_path)
                return json.dumps(
                    {
                        "name": repo_name,
                        "active_branch": str(repo.active_branch),
                        "last_commit": {
                            "hash": str(repo.head.commit),
                            "message": repo.head.commit.message,
                            "author": str(repo.head.commit.author),
                            "date": repo.head.commit.committed_datetime.isoformat(),
                        },
                        "remotes": [
                            {"name": remote.name, "url": remote.url}
                            for remote in repo.remotes
                        ],
                    },
                    indent=2,
                )
            except GitCommandError as e:
                raise RuntimeError(f"Git error: {str(e)}")

        @self.app.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="create_repository",
                    description="Create a new git repository",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Repository name",
                            },
                            "init_commit": {
                                "type": "boolean",
                                "description": "Create initial commit",
                                "default": True,
                            },
                            "remote_url": {
                                "type": "string",
                                "description": "Remote repository URL (optional)",
                            },
                        },
                        "required": ["name"],
                    },
                )
            ]

        @self.app.call_tool()
        async def call_tool(
            name: str, arguments: Any
        ) -> list[TextContent | ImageContent | EmbeddedResource]:
            if name != "create_repository":
                raise ValueError(f"Unknown tool: {name}")

            if not isinstance(arguments, dict) or "name" not in arguments:
                raise ValueError("Invalid repository creation arguments")

            repo_name = arguments["name"]
            init_commit = arguments.get("init_commit", True)
            remote_url = arguments.get("remote_url")

            try:
                repo_path = self.repositories_dir / repo_name
                if repo_path.exists():
                    raise ValueError(f"Repository already exists: {repo_name}")

                repo_path.mkdir(parents=True)
                repo = Repo.init(repo_path)

                if init_commit:
                    # Create README.md
                    readme_path = repo_path / "README.md"
                    readme_path.write_text(
                        f"# {repo_name}\n\nCreated on {datetime.now().isoformat()}"
                    )

                    # Initial commit
                    repo.index.add(["README.md"])
                    repo.index.commit("Initial commit")

                if remote_url:
                    repo.create_remote("origin", remote_url)

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "status": "success",
                                "message": f"Repository '{repo_name}' created successfully",
                                "path": str(repo_path.absolute()),
                                "has_initial_commit": init_commit,
                                "remote_url": remote_url,
                            },
                            indent=2,
                        ),
                    )
                ]
            except (GitCommandError, Exception) as e:
                logger.error(f"Failed to create repository: {str(e)}")
                if repo_path.exists():
                    import shutil

                    shutil.rmtree(repo_path)
                raise RuntimeError(f"Repository creation failed: {str(e)}")

    async def run(self):
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self.app.run(
                read_stream, write_stream, self.app.create_initialization_options()
            )


# メイン実行用関数
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Git Repository Management Server")
    parser.add_argument(
        "--repositories-dir",
        type=str,
        default="./repositories",
        help="Directory to store git repositories (default: ./repositories)",
    )

    args = parser.parse_args()
    server = GitServer(repositories_dir=args.repositories_dir)
    await server.run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
