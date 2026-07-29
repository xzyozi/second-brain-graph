# OSS ライセンス・モデル利用規約管理ポリシー

文書番号: SBOS-LICENSE-001  
最終更新: 2026年7月29日  

---

## 1. 概要
本ドキュメントは、`second-brain-graph` （母艦）および関連システムで利用するオープンソースソフトウェア（OSS）ライブラリ、外部ツール、およびローカルLLM（オープンウェイトモデル）の**ライセンス遵守規定および管理ポリシー**を定義するものです。

法的なリスク（著作権侵害、コピーレフト性によるソースコード開示義務の伝播等）を防止し、安全かつ堅牢な環境構築・運用を保障します。

---

## 2. ライセンス選定方針（許容基準）

本プロジェクトで採用するパッケージおよびツールは、原則として以下の**パーミッシブ（寛容型）ライセンス**に限定します。

### 2.1 許可されるライセンス (商用・非商用ともに自由利用可)
- **MIT License**: 制約が極めて少なく、商用利用・改変・再配布が自由。
- **Apache License 2.0**: 商用利用・改変可。特許権の許諾条項を含み安全。
- **BSD License (2-Clause / 3-Clause)**: 商用利用・改変可。
- **ISC License / Unlicense / CC0**: 権利放棄型・パブリックドメイン同等。

### 2.2 慎重な検証が必要なライセンス (要確認)
- **商用利用制限付きオープンウェイトモデルライセンス** (例: Qwen License, Llama 3 Community License):
  - 特定の利用規模（例: 月間アクティブユーザー1億人超など）で商用ライセンス契約が必要となる場合があるため、利用規約を個別に確認する。

### 2.3 原則禁止とされるライセンス (強コピーレフト)
- **AGPL (GNU Affero General Public License)**: ネットワーク越し利用でもソースコード開示義務が発生するため、原則採用禁止。
- **GPL (GNU General Public License v2 / v3)**: 派生物にGPLが伝播するため、ライブラリとしての直接依存は禁止。

---

## 3. 主要コンポーネント・OSS ライセンス一覧

本プロジェクトで利用されている主要スタックのライセンス状況は以下の通りです。すべて商用利用およびローカル環境構築において安全性が確認されています。

| レイヤー | コンポーネント / OSS名 | バージョン範囲 | ライセンス | 備考 |
| :--- | :--- | :--- | :--- | :--- |
| **LLM Orchestrator** | `langgraph` | `>=0.1.0` | **MIT License** | LangChain公式。商用利用可 |
| **LLM Gateway** | `litellm` | `>=1.30.0` | **MIT License** | マルチモデルラッパー。商用利用可 |
| **Code Agent** | `aider-chat` | `>=0.30.0` | **Apache License 2.0** | Aiderエンジン。商用利用可 |
| **Data Validation** | `pydantic` | `>=2.0.0` | **MIT License** | データ構造検証。商用利用可 |
| **Development** | `pytest`, `ruff`, `mypy` | 最新安定版 | **MIT / Apache 2.0** | 開発・テスト用ツール |
| **External Tool** | `Ollama` | `>=0.3.0` | **MIT License** | ローカルLLM実行基盤 |
| **External Tool** | `Reviewdog` | 最新版 | **MIT License** | レビューアノテーションエンジン |
| **Local LLM Model** | `Gemma 4 12B IT` | - | **Gemma License** | 汎用・計画・監査モデル（利用規約準拠） |
| **Local LLM Model** | `Gemma 4 Py Coder` | - | **Gemma License** | Pythonコード特化モデル（利用規約準拠） |

---

## 4. ライセンスの自動検証手順 (`pip-licenses`)

環境構築時およびパッケージ追加時に、依存関係に不適切なライセンス（GPL/AGPL等）が紛れ込んでいないか自動スキャンする手順です。

### 4.1 ライセンス確認ツールの実行
```bash
# 仮想環境内でライセンス一覧を取得
uv run pip-licenses --ignore-packages second-brain-graph

# 強コピーレフト (GPL / AGPL) のチェック
uv run pip-licenses | grep -iE "GPL|Affero"
```

---

## 5. ライセンス表記の維持と著作権表示
1. 依存ライブラリの `LICENSE` ファイルおよび著作権表示（Copyright Notice）は改変・削除せず維持すること。
2. 他のOSSコードを直接コピー＆ペーストして組み込む場合は、元コードのライセンスおよび著者表示をコメントまたはヘッダーに明記すること。
