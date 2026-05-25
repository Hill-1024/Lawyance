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

- **法律検索とウェブ検索**: 法条の精密検索、自然言語による法条検索、出典リンク確認、類似判例検索、自前運用の SearXNG による公開ウェブ検索。
- **企業情報**: 企業概要、上場情報、連絡先、株主、登記情報、主要人物、対外投資情報。
- **文書処理**: PDF テキスト抽出、PDF の文単位注釈、Word 読み取り、Word 注釈書き込み。
- **Agent モード**: 標準回答と Plan-and-Solve ワークフロー。
- **模擬法廷**: 民事・行政・刑事の三類型の法廷シミュレーション。裁判官、相手方弁護士、復盤員、ユーザー側 AI 代理の四役を内蔵し、段階別の状態機械に従って進行します。公開記録と私的ブリーフのあいだに事実の境界があり、巻き戻しと分岐セッションに対応します。
- **会話ワークスペース**: ユーザーと会話ごとに `TEMP` と `Result` のファイル空間を分離。
- **会話記憶**: 安定した事実、目標、制約、セマンティックタグを記録・検索し、全履歴を無理にプロンプトへ詰め込みません。
- **認証と監査**: ログイン、ロール、管理者アカウント管理、API アクセスログ、基本的なレート制限。
- **フロントエンド体験**: React 19 + Vite によるメインチャット、模擬法廷、ファイルワークスペース、テーマ、管理画面、Lawver ブランド UI。

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
Default / Plan-and-Solve / Court agents
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
| `agent.py` | `agent:app` の import 契約と `python agent.py` の起動入口のみを保持。`PORT` と `UVICORN_WORKERS` 環境変数に対応 |
| `app_factory.py` | FastAPI アプリケーションファクトリ。ミドルウェア、ルート、ライフサイクル処理を集約 |
| `routes/` | 認証、管理者、チャット、模擬法廷、ワークスペース、SPA フォールバックの HTTP ルート |
| `services/` | チャットと法廷のパイプライン、履歴圧縮、記憶調整、法令キャッシュ、ワークスペース清理、セキュリティミドルウェア |
| `agents/tool_loop.py` | 標準モードと Plan-and-Solve を駆動する統一 tool_calls エージェントループ |
| `function_calling.py` | OpenAI 互換モデル呼び出しのラッパーと tool メッセージのペアリング |
| `tools/` | 業務ツールの明示登録（schema / handler / coercer / exposure） |
| `mcps.py` | 業務ツールの統一転送エントリーポイント |
| `mcp/` | 法律、企業、PDF、Word、記憶、SearXNG ウェブ検索のクライアント |
| `memory_system/` | 会話単位の構造化記憶サービス |
| `RAG/` | ローカル法令検索エンジン |
| `prompts/lawver/` | core / modes / focus / tasks / court の動的 prompt リソース |
| `workspace.py` | ワークスペースのパス境界とアップロード/生成ファイル検証 |
| `ocp.py` | 出力レビュー（OCP）パイプライン |
| `src/` | React フロントエンド。メインチャットと模擬法廷の二つのワークフローを含む |
| `tests/` | 記憶、OCP、ツールループ、模擬法廷、セキュリティ、prompt ローダーなどを網羅 |

## 必要環境

- Python 3.13 以上。
- Node.js と pnpm。
- Android クライアントのビルドには JDK 21 と Android SDK が必要です。
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
| `pnpm run mobile:doctor` | Capacitor Android 環境を確認 |
| `pnpm run mobile:android:sync` | フロントエンドをビルドして Android アセットを同期 |
| `pnpm run mobile:android:test` | Android debug ユニットテストを実行 |
| `pnpm run mobile:android:apk` | Android debug APK をビルド |

## Android APK リリースと更新

Android の正式リリースは GitHub Actions の `vX.Y.Z` タグ workflow でビルドします。workflow は tag と `package.json.version` の一致を確認し、GitHub Secrets の長期 release keystore で APK に署名し、`Lawver-${version}.apk` と `android-version.json` を GitHub Release にアップロードします。

本番バックエンドは起動時に GitHub 最新 Release から Android APK をローカルキャッシュへ同期します。既定ディレクトリは `data/releases/android/` です。公開・未ログインの読み取り専用配布 API は以下です：

- `GET /api/releases/android/latest`: キャッシュ済みバージョン情報を返し、`apkUrl` を本番バックエンドのダウンロード URL に書き換えます。
- `GET /api/releases/android/apk`: キャッシュ済み APK を返し、単一 IP あたり既定 6 RPM の制限を適用します。

任意の環境変数：

- `LAWVER_RELEASE_SYNC_ON_STARTUP`: 起動時に GitHub Release を同期するか。既定値は `1`
- `LAWVER_RELEASE_REPO`: GitHub Release の取得元。既定値は `Hill-1024/Lawyance`
- `LAWVER_RELEASE_DIR`: APK キャッシュディレクトリ。既定値は `data/releases/android/`
- `LAWVER_PUBLIC_BASE_URL`: 外部公開 URL。本番では `https://law.mutsumi.moe` を推奨
- `LAWVER_APK_DOWNLOAD_RPM`: APK ダウンロードの単一 IP RPM 制限。既定値は `6`
- `LAWVER_GITHUB_TOKEN`: private repository または GitHub API rate limit 用の読み取り専用 token

## テスト

```bash
python -m pytest
```

現在のテストスイートは約 170 ケースで、代表的なカバレッジは以下のとおりです：

- `tests/test_memory_system.py`、`tests/test_prompt_loader.py`: 会話単位の記憶と動的 prompt の組み立て。
- `tests/test_ocp.py`、`tests/test_tool_loop_agent.py`: 出力レビューと統一ツールループ。
- `tests/test_court_mode.py`: 模擬法廷の状態機械と役割境界。
- `tests/test_security_hardening.py`、`tests/test_mcps_workspace_paths.py`、`tests/test_remaining_vulnerability_fixes.py`: CSRF、レート制限、ワークスペースのパスと過去の脆弱性回帰。
- `tests/test_function_calling_tools.py`、`tests/test_tool_schema_compatibility.py`、`tests/test_tool_exposure.py`: ツール schema、exposure、OpenAI 互換性。
- `tests/test_law_data_search.py`、`tests/test_law_cache_startup.py`、`tests/test_searxng_tool.py`: ローカル法令検索、キャッシュ増分構築、SearXNG クライアント。

## バックエンド構成とツール登録

`agent.py` は `agent:app` の import 契約と `python agent.py` の起動入口だけを保持します。アプリの組み立ては `app_factory.py`、HTTP ルートは `routes/`、チャットパイプライン、履歴圧縮、記憶調整、清理タスクは `services/` にあります。

ルート登録順序は、認証 → 管理者 → チャット → 模擬法廷 → APK リリース配布 → ワークスペース/アップロード/ダウンロード → SPA catch-all の順に固定します。`routes/spa.py` は最後に登録し、`/api/*` がフロントエンド fallback に吸われないようにします。

業務ツールは引き続き `mcps.py` を通じて agent に公開します。新しいツールを追加する流れ：

1. `mcp/` に実際のクライアントまたは handler を実装する。
2. `tools/__init__.py` に schema、handler、coercer、`exposure` を明示登録する。
3. 呼び出しは `mcps.use_tools()` 経由にし、agent、route、service が `mcps` を迂回しない。

`exposure` はツール可視性の唯一の宣言元です：

- `agent`: メイン LLM の tool schema に表示するツール。
- `plan_and_solve`: Plan-and-Solve モードに表示するツール。業務ツールと制御面ツールを含みます。
- `court`: 模擬法廷パイプライン（`registry.schemas("court")`）に表示するツール。法律信源、企業、文書処理、ウェブ検索、記憶、ワークスペースを含みます。
- `ocp_reviewer`: OCP が利用できる読み取り専用の法律信源ツール。
- `internal`: バックエンド内部では dispatch できるが、LLM tool schema には出さないツール。

ワークスペースのパス検証は `workspace.py` に集約し、`mcps.py` と `tools/*` が共有します。これにより registry 側が `mcps` を逆 import する必要がなくなります。

OCP は主回答後のフォーマット審査 pass です。主モデルの失敗は従来どおり主モデルのエラー経路で扱います。一方、OCP のタイムアウト、ネットワーク障害、ツール障害、審査モデル障害はユーザー経路へ投げず、主モデル本文を保った deterministic sanitizer-only fallback に降級します。

この構成変更には、Lawver の命名統一、ツール命名規約の書き換え、agent 推論戦略の書き換えは含みません。

ウェブ検索ツールは自前運用の SearXNG を使い、Tavily や SerpAPI などの第三者検索 API には依存しません。`web_search` は構造化された検索結果と snippets のみを返し、本文が必要な場合はモデルが `web_fetch` を追加で呼び出します。`web_fetch` の本文は非信頼のウェブデータとして扱い、指示として従ってはいけません。

任意の環境変数：

- `SEARXNG_BASE_URL`: SearXNG インスタンス URL。既定値は `https://serp.mutsumi.moe/`
- `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`: Cloudflare Access Service Auth ヘッダー。旧名の `SEARXNG_CF_ACCESS_CLIENT_ID` / `SEARXNG_CF_ACCESS_CLIENT_SECRET` も互換対応
- `SEARXNG_ENGINES`、`SEARXNG_CATEGORIES`、`SEARXNG_LANGUAGE`、`SEARXNG_SAFE_SEARCH`: 既定検索パラメータの上書き。通常はサーバー側の `settings.yml` と `categories` に engine ルーティングを任せ、正確に engine を固定したい場合だけ `SEARXNG_ENGINES` を設定します
- `SEARXNG_TIMEOUT`、`SEARXNG_MAX_RESULTS`、`SEARXNG_MAX_RESPONSE_BYTES`: リクエストと結果サイズの制限。既定値は 20 秒、10 件

## 会話記憶と RAG 重み

記憶システムは引き続き会話単位の構造化記憶です。検索ではキーワード、意味タグ、エンティティ、鮮度、優先度、現在の焦点など複数の信号を統合します。任意で embedding 検索を有効にした場合、ベクトル類似度は既存の多路検索を置き換えるのではなく、同じ RAG 重み付きランカー内の `embedding` 信号として扱われます。

任意の環境変数：

- `MEMORY_EMBEDDING_ENABLED=1`: embedding を検索重みとして有効化。既定では無効
- `EMBEDDING_API_KEY`: embedding サービスの API Key
- `EMBEDDING_BASE_URL`: OpenAI 互換 embedding Base URL。既定値は `https://api.siliconflow.cn/v1`
- `EMBEDDING_MODEL`: embedding モデル。既定値は `Qwen/Qwen3-Embedding-8B`
- `MEMORY_EMBEDDING_TIMEOUT`: embedding リクエストのタイムアウト。既定値は 8 秒

## 模擬法廷

模擬法廷は複数の AI 役が共同で行う法廷シミュレーションのワークフローです。ワークスペースとツールはメインチャットと共有しますが、prompt とパイプラインは独立しています。

- **三つの案件類型**: 民事、行政、刑事。それぞれが段階別の状態機械で進行します（開廷 → 訴え・起訴陳述 → 法廷調査 → 証拠調べ／合法性審査 → 法廷弁論 → 最終陳述 → 法廷意見 → 法廷後の復盤）。
- **役ごとの記憶分離**: 裁判官、相手方弁護士、復盤員、ユーザー側 AI 代理（任意で有効化）はそれぞれ独立した私的記憶 scope を持ち、公開発言だけが共有の法廷記録に入ります。
- **事実と法源の境界**: 発言は共有案件記録、公開法廷記録、ツールの返却結果のみを根拠にできます。未公開の事実は「要確認」と明示する必要があり、相手方弁護士は仮定事実を提示できますが「可能性」「排除しない」などの限定語が必須です。
- **巻き戻しと分岐**: 任意の公開イベントまで巻き戻すと構造化状態が再計算され、AI 側の私的記憶も消去されます。同じ地点から共有案件を引き継いだ新しい法廷セッションへ分岐することもできます。

バックエンドの入口は `routes/court.py`、パイプラインは `services/court_pipeline.py` と `services/court_fsm.py`。フロントエンドは `src/components/CourtPage.tsx` と `src/hooks/useCourtSession.ts`。

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
- GET 以外の `/api` リクエストは信頼できる Origin か Referer を必須とします。本番のフロントエンドドメインは `LAWVER_ALLOWED_ORIGINS`（旧名 `ALLOWED_ORIGINS` も互換）で追加してください。ローカルのループバックアドレスは既定で許可されます。
- レート制限のカウンタはプロセス内状態です。`UVICORN_WORKERS>1` で動かす場合、各 worker が個別にカウントするため、公開デプロイでは Redis などの共有ストアに移行することを推奨します。
- 管理者 API はアカウント管理とログ閲覧ができるため、信頼できる管理者だけに公開してください。
- ファイル注釈、文書読み取り、ダウンロード API では、パス分離と権限境界を継続的に確認してください。

## ライセンス

本プロジェクトのソースコードは GNU Affero General Public License v3.0（AGPL-3.0）に基づいて公開されています。詳細は [LICENSE](./LICENSE) を参照してください。

本プロジェクトを再利用、変更、再配布、またはネットワークサービスとして提供する場合は、AGPL-3.0 の条項に従ってください。業務データ、第三者データソース、モデルサービス、実際のクライアント資料は、このリポジトリのライセンスによって自動的に許諾されるものではありません。利用前にチームの許可とデータコンプライアンス要件を個別に確認してください。
