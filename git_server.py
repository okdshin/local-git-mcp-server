import json
import logging
import re
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

    def _validate_repo_name(self, repo_name: str) -> None:
        """
        リポジトリ名のバリデーションを行う
        
        Args:
            repo_name (str): 検証するリポジトリ名
            
        Raises:
            ValueError: リポジトリ名が無効な場合
        """
        if not repo_name:
            raise ValueError("Repository name cannot be empty")
            
        # 長さの制限（一般的なファイルシステムの制限を考慮）
        if len(repo_name) > 255:
            raise ValueError("Repository name is too long (max 255 characters)")
            
        # 基本的な文字のバリデーション
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9-_.]*$', repo_name):
            raise ValueError("Repository name must start with alphanumeric character and can only contain alphanumeric characters, hyphens, underscores, and dots")
            
        # 危険な文字列のチェック
        forbidden_patterns = ['..', '//', '\\\\', '.git', '.lock']
        if any(pattern in repo_name for pattern in forbidden_patterns):
            raise ValueError(f"Repository name contains forbidden pattern: {repo_name}")
            
        # 予約された名前のチェック
        reserved_names = ['git', 'temp', 'tmp', 'aux', 'con', 'prn', 'nul', 'com1', 'com2', 'com3', 'com4', 'lpt1', 'lpt2', 'lpt3']
        if repo_name.lower() in reserved_names:
            raise ValueError(f"Repository name '{repo_name}' is reserved and cannot be used")
            
        # パスインジェクション対策
        repo_path = Path(repo_name)
        if '..' in repo_path.parts or '/' in repo_name or '\\' in repo_name:
            raise ValueError("Repository name cannot contain path traversal characters")

    def _check_repository_exists(self, repo_name: str) -> Path:
        """
        リポジトリの存在確認を行う
        
        Args:
            repo_name (str): 確認するリポジトリ名
            
        Returns:
            Path: リポジトリのパス
            
        Raises:
            ValueError: リポジトリが存在しない場合
        """
        self._validate_repo_name(repo_name)
        repo_path = self.repositories_dir / repo_name
        if not repo_path.exists() or not (repo_path / ".git").exists():
            raise ValueError(f"Repository not found: {repo_name}")
        return repo_path

    def _setup_routes(self):
        @self.app.list_resources()
        async def list_resources() -> list[Resource]:
            resources = []
            for repo_path in self.repositories_dir.glob("*"):
                if repo_path.is_dir() and (repo_path / ".git").exists():
                    try:
                        repo_name = repo_path.name
                        self._validate_repo_name(repo_name)
                        uri = AnyUrl(f"git://{repo_name}")
                        resources.append(
                            Resource(
                                uri=uri,
                                name=f"Git repository dir: {repo_path.absolute()}",
                                mimeType="application/x-git",
                                description=f"Local git repository at {repo_path}",
                            )
                        )
                    except ValueError as e:
                        logger.warning(f"Skipping invalid repository: {str(e)}")
                        continue
            return resources

        @self.app.read_resource()
        async def read_resource(uri: AnyUrl) -> str:
            if not str(uri).startswith("git://"):
                raise ValueError(f"Unknown resource: {uri}")

            repo_name = str(uri).split("://")[1]
            repo_path = self._check_repository_exists(repo_name)

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
                ),
                Tool(
                    name="git_add",
                    description="Add files to git staging area",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {"type": "string", "description": "Repository name"},
                            "files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of files to add"
                            }
                        },
                        "required": ["repo_name", "files"]
                    }
                ),
                Tool(
                    name="git_commit",
                    description="Commit staged changes",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {"type": "string", "description": "Repository name"},
                            "message": {"type": "string", "description": "Commit message"}
                        },
                        "required": ["repo_name", "message"]
                    }
                ),
                Tool(
                    name="git_pull",
                    description="Pull changes from remote repository",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {"type": "string", "description": "Repository name"},
                            "remote": {
                                "type": "string",
                                "description": "Remote name",
                                "default": "origin"
                            },
                            "branch": {
                                "type": "string",
                                "description": "Branch name",
                                "default": "main"
                            }
                        },
                        "required": ["repo_name"]
                    }
                ),
                Tool(
                    name="git_push",
                    description="Push changes to remote repository",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {"type": "string", "description": "Repository name"},
                            "remote": {
                                "type": "string",
                                "description": "Remote name",
                                "default": "origin"
                            },
                            "branch": {
                                "type": "string",
                                "description": "Branch name",
                                "default": "main"
                            }
                        },
                        "required": ["repo_name"]
                    }
                ),
                Tool(
                    name="git_diff",
                    description="Show differences between commits, commit and working tree, etc.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {"type": "string", "description": "Repository name"},
                            "commit1": {
                                "type": "string", 
                                "description": "First commit hash (optional, default is HEAD)",
                                "default": "HEAD"
                            },
                            "commit2": {"type": "string", "description": "Second commit hash (optional)"}
                        },
                        "required": ["repo_name"]
                    }
                )
            ]

        @self.app.call_tool()
        async def call_tool(
            name: str, arguments: Any
        ) -> list[TextContent | ImageContent | EmbeddedResource]:
            try:
                if name == "create_repository":
                    if not isinstance(arguments, dict) or "name" not in arguments:
                        raise ValueError("Invalid repository creation arguments")
                    
                    repo_name = arguments["name"]
                    self._validate_repo_name(repo_name)
                    repo_path = self.repositories_dir / repo_name
                    
                    if repo_path.exists():
                        raise ValueError(f"Repository already exists: {repo_name}")

                    init_commit = arguments.get("init_commit", True)
                    remote_url = arguments.get("remote_url")

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

                # その他のGit操作の共通処理
                repo_name = arguments["repo_name"]
                repo_path = self._check_repository_exists(repo_name)
                repo = Repo(repo_path)

                if name == "git_add":
                    files = arguments["files"]
                    repo.index.add(files)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "status": "success",
                                    "message": f"Added files to staging area: {', '.join(files)}",
                                    "repo": repo_name
                                },
                                indent=2
                            )
                        )
                    ]

                elif name == "git_commit":
                    message = arguments["message"]
                    commit = repo.index.commit(message)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "status": "success",
                                    "message": "Commit created successfully",
                                    "commit_hash": str(commit),
                                    "commit_message": message,
                                    "repo": repo_name
                                },
                                indent=2
                            )
                        )
                    ]

                elif name == "git_pull":
                    remote = arguments.get("remote", "origin")
                    branch = arguments.get("branch", "main")
                    remote_obj = repo.remote(name=remote)
                    remote_obj.pull(branch)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "status": "success",
                                    "message": f"Pulled changes from {remote}/{branch}",
                                    "repo": repo_name
                                },
                                indent=2
                            )
                        )
                    ]

                elif name == "git_push":
                    remote = arguments.get("remote", "origin")
                    branch = arguments.get("branch", "main")
                    remote_obj = repo.remote(name=remote)
                    remote_obj.push(branch)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "status": "success",
                                    "message": f"Pushed changes to {remote}/{branch}",
                                    "repo": repo_name
                                },
                                indent=2
                            )
                        )
                    ]

                elif name == "git_diff":
                    commit1 = arguments.get("commit1", "HEAD")
                    commit2 = arguments.get("commit2")

                    # diffコマンドの実行
                    if commit2:
                        diff_result = repo.git.diff(commit1, commit2)
                    else:
                        # コミット済みの変更とワーキングツリーの差分を表示
                        diff_result = repo.git.diff(commit1)

                    return [
                        TextContent(
                            type="text",
                            text=json.dumps({"diff": diff_result}, indent=2)
                        )
                    ]


                else:
                    raise ValueError(f"Unknown tool: {name}")

            except GitCommandError as e:
                logger.error(f"Git operation failed: {str(e)}")
                raise RuntimeError(f"Git operation failed: {str(e)}")
            except Exception as e:
                logger.error(f"Operation failed: {str(e)}")
                raise RuntimeError(f"Operation failed: {str(e)}")

    async def run(self):
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self.app.run(
                read_stream, write_stream, self.app.create_initialization_options()
            )


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