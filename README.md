# Local Git MCP Server

MCPプロトコルを使用してローカルGitリポジトリを管理するサーバーです。

## 機能

- ローカルGitリポジトリの作成
- リポジトリ一覧の取得
- リポジトリ詳細情報の取得（ブランチ、最新コミット、リモート情報など）
- リモートリポジトリの設定

## インストール

1. 依存パッケージのインストール:
```bash
pip install -r requirements.txt
```

## 使い方

1. サーバーの起動:
```bash
# デフォルトのリポジトリディレクトリを使用
python git_server.py

# カスタムディレクトリを指定
python git_server.py --repositories-dir /path/to/repos
```

2. 新しいリポジトリの作成:
```json
{
    "name": "my-project",
    "init_commit": true,
    "remote_url": "https://github.com/username/my-project.git"
}
```

3. リポジトリ情報の取得:
- URI形式: `git://リポジトリ名`
- 返り値の例:
```json
{
    "name": "my-project",
    "active_branch": "main",
    "last_commit": {
        "hash": "abc123...",
        "message": "Initial commit",
        "author": "User Name",
        "date": "2025-01-06T12:00:00+00:00"
    },
    "remotes": [
        {
            "name": "origin",
            "url": "https://github.com/username/my-project.git"
        }
    ]
}
```

## エラー処理

- リポジトリ作成に失敗した場合、作成されたディレクトリは自動的に削除されます
- エラーは適切にログ記録され、クライアントに通知されます