# Lawver

[中文](./README.md) | [English](./README.en.md) | 日本語

Lawver は、工大法智チームによる中国語法律 AI アシスタントプロジェクトです。法律相談、法令検索、類似判例検索、企業情報照会、契約書/PDF/Word 文書処理、会話単位の記憶、フロントエンドのワークスペースを一つのアプリケーションに統合します。目的は検証できない短い結論を返すことではなく、法律問題を事実、根拠、検索結果、さらに確認可能な分析手順へ整理することです。

このリポジトリには FastAPI バックエンド、React/Vite フロントエンド、ツール転送層、法律データクライアント、文書処理ツール、会話記憶システム、出力レビュー処理が含まれています。モジュール境界を重視しており、業務ツールは `mcps` を通して agent に公開します。業務コードがこのミドルウェアを迂回しないことを前提にしています。

## 位置づけ

- 中国語法律シナリオ向けの AI アシスタントプロトタイプ。
- タスクの複雑さに応じて、直接回答と Plan-and-Solve を使い分けます。
- 法令、判例、企業データ、文書処理能力をツール経由で agent に接続します。
- 会話単位の記憶により、安定した事実、ユーザー制約、作業境界を保持します。
- フロントエンドのワークスペースで、アップロードファイル、生成ファイル、会話コンテキストを管理します。

## 主な機能

- **法律検索**: 法条の精密検索、自然言語による法条検索、出典リンク確認、類似判例検索。
- **企業情報**: 企業概要、上場情報、連絡先、株主、登記情報、主要人物、対外投資情報。
- **文書処理**: PDF テキスト抽出、PDF の文単位注釈、Word 読み取り、Word 注釈書き込み。
- **Agent モード**: 標準回答と Plan-and-Solve ワークフロー。
- **会話ワークスペース**: ユーザーと会話ごとに `TEMP` と `Result` のファイル空間を分離。
- **会話記憶**: 安定した事実、目標、制約、セマンティックタグを記録・検索し、全履歴を無理にプロンプトへ詰め込みません。
- **認証と監査**: ログイン、ロール、管理者アカウント管理、API アクセスログ、基本的なレート制限。
- **フロントエンド体験**: React 19 + Vite によるチャット、ファイル、ワークスペース、テーマ、管理画面、Lawver ブランド UI。

## アーキテクチャ

```text
React / Vite frontend
    |
    | REST / stream / file workspace
    v
FastAPI application
    |
    | agent orchestration
    v
Default / Plan-and-Solve agents
    |
    | tool descriptions + calls
    v
mcps tool forwarding layer
    |
    | legal data / company data / document processors / memory client
    v
MCP clients and local services
```

主要パス：

| Path | 説明 |
| --- | --- |
| `agent.py` | FastAPI アプリ、認証依存、レート制限、ログ、ファイルワークスペース、主要 API |
| `function_calling.py` | モデル呼び出し、ツール呼び出し制御、複数 system prompt の転送 |
| `agents/` | 統一されたネイティブツールループと Plan-and-Solve 制御 |
| `mcps.py` | 業務ツールの統一転送層 |
| `mcp/` | 法律、企業、PDF、Word、記憶関連のツールクライアント |
| `memory_system/` | 会話単位の構造化記憶サービス |
| `RAG/` | ローカル法律データ検索ロジック |
| `src/` | React フロントエンドアプリ |
| `tests/` | 記憶システムと出力レビュー処理のテスト |

## 必要環境

- Python 3.13 以上。
- Node.js と pnpm。
- 必要なモデルサービスと業務データソースへアクセスできること。
- リポジトリルートの `.env` にモデル API キーなどのローカル設定を用意すること。

API Key、アカウント資格情報、実際のクライアント資料をリポジトリへコミットしないでください。`.env_example` を参考にローカル `.env` を作成します。

```env
API_KEY="your_api_key_here"
```

## インストール

```bash
pnpm install
pip install -r requirements.txt
```

リポジトリには `pyproject.toml` と `uv.lock` も含まれています。ローカルの運用で uv を使う場合は、チームの規約に従って Python 依存関係をインストールしてください。

## 開発実行

フロントエンド静的アセットをビルドします。

```bash
pnpm run build
```

アプリケーション全体を起動します。

```bash
pnpm run dev
```

このコマンドは `python agent.py` を実行します。Vite フロントエンド開発サーバーだけを起動する場合：

```bash
pnpm run dev:frontend
```

よく使うスクリプト：

| Command | 説明 |
| --- | --- |
| `pnpm run dev` | FastAPI アプリを起動 |
| `pnpm run dev:frontend` | フロントエンド開発サーバーを起動 |
| `pnpm run build` | フロントエンドをビルド |
| `pnpm run preview` | フロントエンドのビルド結果をプレビュー |
| `pnpm run lint` | TypeScript チェックを実行 |
| `pnpm run clean` | フロントエンドのビルド成果物を削除 |

## テスト

```bash
python -m pytest
```

現在の主なテスト対象：

- `tests/test_memory_system.py`: 会話記憶の記録、検索、制約処理、コンテキスト生成。
- `tests/test_ocp.py`: 出力レビューのフォールバック、完了状態、例外処理。

## バックエンド構成とツール登録

`agent.py` は `agent:app` の import 契約と `python agent.py` の起動入口だけを保持します。アプリの組み立ては `app_factory.py`、HTTP ルートは `routes/`、チャットパイプライン、履歴圧縮、記憶調整、清理タスクは `services/` にあります。

ルート登録順序は、認証、管理者、チャット、ワークスペース/アップロード/ダウンロード、SPA catch-all の順に固定します。`routes/spa.py` は最後に登録し、`/api/*` がフロントエンド fallback に吸われないようにします。

業務ツールは引き続き `mcps.py` を通じて agent に公開します。新しいツールを追加する流れ：

1. `mcp/` に実際のクライアントまたは handler を実装する。
2. `tools/__init__.py` に schema、handler、coercer、`exposure` を明示登録する。
3. 呼び出しは `mcps.use_tools()` 経由にし、agent、route、service が `mcps` を迂回しない。

`exposure` はツール可視性の唯一の宣言元です：

- `agent`: メイン LLM の tool schema に表示するツール。
- `plan_and_solve`: Plan-and-Solve モードに表示するツール。業務ツールと制御面ツールを含みます。
- `ocp_reviewer`: OCP が利用できる読み取り専用の法律信源ツール。
- `internal`: バックエンド内部では dispatch できるが、LLM tool schema には出さないツール。

ワークスペースのパス検証は `workspace.py` に集約し、`mcps.py` と `tools/*` が共有します。これにより registry 側が `mcps` を逆 import する必要がなくなります。

OCP は主回答後のフォーマット審査 pass です。主モデルの失敗は従来どおり主モデルのエラー経路で扱います。一方、OCP のタイムアウト、ネットワーク障害、ツール障害、審査モデル障害はユーザー経路へ投げず、主モデル本文を保った deterministic sanitizer-only fallback に降級します。

この構成変更には、Lawver の命名統一、ツール命名規約の書き換え、agent 推論戦略の書き換えは含みません。

## 会話記憶と RAG 重み

記憶システムは引き続き会話単位の構造化記憶です。検索ではキーワード、意味タグ、エンティティ、鮮度、優先度、現在の焦点など複数の信号を統合します。任意で embedding 検索を有効にした場合、ベクトル類似度は既存の多路検索を置き換えるのではなく、同じ RAG 重み付きランカー内の `embedding` 信号として扱われます。

任意の環境変数：

- `MEMORY_EMBEDDING_ENABLED=1`: embedding を検索重みとして有効化。既定では無効
- `EMBEDDING_API_KEY`: embedding サービスの API Key
- `EMBEDDING_BASE_URL`: OpenAI 互換 embedding Base URL。既定値は `https://api.siliconflow.cn/v1`
- `EMBEDDING_MODEL`: embedding モデル。既定値は `Qwen/Qwen3-Embedding-8B`
- `MEMORY_EMBEDDING_TIMEOUT`: embedding リクエストのタイムアウト。既定値は 8 秒

## 開発境界

- `mcps.py` は agent 向け業務ツールの統一入口です。新しいツールは `mcp/` クライアントに実装し、`mcps` から公開してください。agent や API ルートが直接迂回して呼び出すべきではありません。
- 記憶システムは会話単位の構造化記憶です。ユーザー単位の長期プロファイルではなく、任意の embedding は検索重み信号としてのみ利用します。
- アップロードファイルと生成ファイルは、ユーザー/会話ごとのワークスペース境界内に置く必要があります。
- 法律回答では、事実、法条、判例、出典リンクなどの検証可能な経路を残すべきです。
- フロントエンド移行や UI 調整は Lawver デザインシステムに従い、padding の小手先対応や互換レイヤーでレイアウト問題を隠さないでください。

## セキュリティメモ

- `.env`、実際の契約書、クライアント資料、生成結果、ログには機密情報が含まれる可能性があります。安易にコミットしないでください。
- 初回デプロイでは 32 文字以上のランダムな `SECRET_KEY` と一度限りの `INITIAL_ADMIN_PASSWORD` を設定してください。`data/account.json` 作成後は初期パスワード用の環境変数を削除します。
- 現在の CORS、レート制限、認証の既定値は内部プロトタイプ向けです。公開デプロイ前には実際のドメインと安全方針に合わせて強化してください。
- 管理者 API はアカウント管理とログ閲覧ができるため、信頼できる管理者だけに公開してください。
- ファイル注釈、文書読み取り、ダウンロード API では、パス分離と権限境界を継続的に確認してください。

## ライセンス

本プロジェクトのソースコードは GNU Affero General Public License v3.0（AGPL-3.0）に基づいて公開されています。詳細は [LICENSE](./LICENSE) を参照してください。

本プロジェクトを再利用、変更、再配布、またはネットワークサービスとして提供する場合は、AGPL-3.0 の条項に従ってください。業務データ、第三者データソース、モデルサービス、実際のクライアント資料は、このリポジトリのライセンスによって自動的に許諾されるものではありません。利用前にチームの許可とデータコンプライアンス要件を個別に確認してください。
