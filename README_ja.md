# Sanity-Gravity: The Antigravity Sandbox

<p align="center">
  <img src="assets/logo.jpg" alt="Sanity-Gravity Logo" width="300">
</p>

<p align="center">
  <em>Agentic AI IDE 向けに構築された最新の安全なコンテナサンドボックス環境</em>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh-TW.md">繁體中文</a> | <a href="README_ja.md">日本語</a>
</p>

---

## TL;DR

**Sanity-Gravity** は、Antigravity ワークフローに特化して構築された、最新の「設定不要」の GUI サンドボックスです。高リスクな可能性のあるすべての操作を使い捨ての Docker コンテナ内に完全に隔離し、シームレスな XFCE4 デスクトップ体験をブラウザに直接ストリーミングします。

**数秒で安全な Antigravity 開発環境を起動：**

```bash
# 1. ベースイメージを構築
./sanity-cli build

# 2. 永続的なワークスペースボリュームでサンドボックスを起動
./sanity-cli up -v kasm --name my-agent-task --workspace ./ai-workspace
```

安全なデスクトップの準備が完了しました。**https://localhost:8444** にアクセスしてください！
- **ユーザー名**: `(ホスト OS の実際のユーザー名)`
- **パスワード**: `antigravity` (`--password` で設定した値)

📺 **[実際のデモ動画を見る](https://youtu.be/x0DGKuHyx2A)**

## 目次

- [なぜ Sanity-Gravity なのか？](#なぜ-sanity-gravity-なのか)
- [クイックスタート](#クイックスタート)
  - [システム要件](#システム要件)
  - [インストール手順](#インストール手順)
- [コマンドリファレンス (`sanity-cli`)](#コマンドリファレンス-sanity-cli)
- [高度な機能](#高度な機能)
  - [IDE のメンテナンスと安全なアップグレード](#️-ide-のメンテナンスと安全なアップグレード)
    - [ホストシステムから使用する場合](#ホストシステムから使用する場合)
    - [コンテナ内部で使用する場合](#コンテナ内部で使用する場合)
  - [SSH プロキシ](#-ssh-プロキシ)
  - [マルチインスタンス](#-マルチインスタンス)
  - [コンテナスナップショット](#-コンテナスナップショット)
  - [ランタイム設定同期](#-ランタイム設定同期)
- [バリアント](#バリアント)
- [SSH アクセス](#ssh-アクセス)
- [プロジェクト構造](#プロジェクト構造)
- [名前の由来](#名前の由来)
- [ライセンス](#ライセンス-license)

---

## なぜ Sanity-Gravity なのか？

| 機能                             | 説明                                                                                                                                                             |
| :------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **🛡️ 絶対的な安全性**             | ホスト環境を完全に保護。Antigravity エージェントが `rm -rf /` を実行したり、危険なコードをダウンロードしても、サンドボックスが破壊されるだけでホストは安全です。 |
| **🖥️ 完全な GUI デスクトップ**    | **Ubuntu 24.04 + XFCE4** と **KasmVNC** を内蔵。Antigravity は人間と同じようにブラウザや GUI を操作できます。                                                    |
| **🚀 すぐに使える**               | **Antigravity IDE**、Google Chrome や Git などの中核ソフトが事前インストール済みで、待ち時間なくすぐに始められます。                                             |
| **🔌 シームレスなディスク I/O**   | 現在のホストの UID および GID にスマートに対応し、マウント後にファイルが root 所有になってしまうトラブルを完全に回避します。                                     |
| **🧩 マルチインスタンス**         | 隔離された環境でタスクを並行処理可能。システムが未使用のポートを自動で割り当て、ポートの競合を防ぎます。                                                         |
| **📸 凍結スナップショット**       | 現在の環境状態（インストール済みのソフトウェアやログイン状態）を迅速に凍結し、新しいイメージとして保存できます。                                                 |
| **🔄 IDE の安全なアップグレード** | 組み込みの管理機能により、リモートで安全に IDE をアップグレード。システムの更新によって発生するクラッシュを未然に防ぎます。                                      |
| **🔑 SSH プロキシ**               | ホスト側の認証情報を安全にコンテナへ引き継ぐことで、プライベートキーを複製せずコンテナ内で快適に Git 操作が行えます。                                            |

## クイックスタート

### システム要件

* Docker & Docker Compose (v2.0+)
* Python 3.7+ (`sanity-cli` 用)
* *(オプション)* **NVIDIA Container Toolkit** (GPU サポート用)
* **サポート環境**: **Ubuntu (amd64/arm64)** および **macOS 26.0.1 (Apple Silicon M1)** にて完全な動作検証済みです。

### インストール手順

1. このリポジトリの複製:
   ```bash
   git clone https://github.com/shiritai/sanity-gravity.git
   cd sanity-gravity
   ```

2. サンドボックスのベースイメージの構築:
   ```bash
   ./sanity-cli build
   ```

3. KasmVNC バリアントの起動 (スムーズなウェブ体験のために推奨):
   ```bash
   ./sanity-cli up -v kasm --password mysecret
   ```

4. **デスクトップへのアクセス**:
   ブラウザを開き、以下にアクセスします: **[https://localhost:8444](https://localhost:8444)**
   * **ユーザー名**: `(ホストのユーザー名)`
   * **パスワード**: `mysecret` (デフォルトは `antigravity`)

> **注意**: localhost での "自己署名証明書" の警告は完全に正常です。"詳細設定" をクリックして進んでください。

## コマンドリファレンス (`sanity-cli`)

`sanity-cli` は、中央のオーケストレーターとして以下のコマンドを提供します。

```bash
# ライフサイクル管理
./sanity-cli up -v [name]   # コンテナの起動 (以下のオプションを付加可能)
  --password [pwd]          # カスタム SSH/VNC パスワード (デフォルト: antigravity)
  --workspace [path]        # ワークスペースディレクトリの割り当て (デフォルト: ./workspace)
  --name [name]             # プロジェクト名によるインスタンスの分離 (デフォルト: sanity-gravity)
  --cpus [limit]            # CPU クォータ (例: 1.5)
  --memory [limit]          # メモリ クォータ (例: 4G)
  --gpu                     # NVIDIA GPU サポートを有効化
./sanity-cli down           # コンテナとネットワークの完全な停止と削除
./sanity-cli stop           # コンテナの一時停止 (データは保持)
./sanity-cli start          # 一時停止したコンテナの開始
./sanity-cli restart        # 実行中のコンテナの強制再起動

# 環境と状態の監視
./sanity-cli status         # すべての実行中のインスタンスの確認
./sanity-cli shell          # コンテナ内のシェル (zsh) へ即座に接続
./sanity-cli open           # デフォルトブラウザで Web VNC デスクトップを起動

# メンテナンスとネットワーク同期
./sanity-cli ide <action>   # コンテナへの IDE メンテナンスのリモートデプロイ
./sanity-cli proxy <action> # SSH Proxy Daemon サービスの管理
./sanity-cli sync_config    # ホスト側設定ファイルを実行中のコンテナにプッシュ
./sanity-cli snapshot       # コンテナ状態を新しいローカライズイメージとして凍結
```

---

## 高度な機能

### 🛠️ IDE のメンテナンスと安全なアップグレード

Sanity-Gravity には、システムレベルの `apt upgrade` によって IDE や Google Chrome ブラウザが誤ってアンインストールされたり、権限を喪失してクラッシュすることを防ぐための厳密な保護機能が組み込まれています。

ホスト側の管理と、コンテナ内部のソフトウェア管理を明確に分けて設計しています：

- **ホスト側**：`sanity-cli` はコンテナのライフサイクル全体を管理します。メンテナンスコマンドの実行時、最新の保護スクリプトを対象のコンテナに**自動的に注入**し、古いコンテナイメージとの後方互換性を維持したまま修正を適用します。
- **コンテナ内部**：`gravity-cli` （コンテナに内蔵された管理スクリプト）が下層保護 (`dpkg-divert`) を通じて Antigravity IDE と Google Chrome ブラウザを管理します。今後のシステム更新によって `--no-sandbox` などの重要な起動権限が消されたり破壊されたりするのを確実に防ぎます。

#### ホストシステムから使用する場合

IDE の異常終了（Google Gemini の強制更新に伴うブラウザ障害など）に直面したときや、単に安全に IDE を最新版へ更新したい場合は、ホスト側から `ide` コマンドを実行します。
> **注意**: 稼働中のインスタンスの名称は `./sanity-cli status` で確認できます。

```bash
# APT を利用し、安全に Antigravity IDE を最新パッケージへと更新する
./sanity-cli ide update --name sanity-gravity

# 強力な修復策：継続的なひどいクラッシュを修正するため、完全に消去してクリーンインストールを行う
./sanity-cli ide reinstall --name sanity-gravity
```
*(これらのコマンドは、対象のコンテナ内部において管理者権限で `gravity-cli` スクリプトを呼び出します。すべての保護およびアップグレード手順はコンテナ内部で行われるため、ホスト環境はクリーンに保たれます。)*

#### コンテナ内部で使用する場合

すでにコンテナのターミナルに接続している場合（`./sanity-cli shell` を使用した場合など）、ターミナルから直接 `gravity-cli` ツールを呼び出すことができます。実行には管理者権限が必要となるため `sudo` を付加してください。

```bash
sudo gravity-cli update-ide    # 'ide update' と同等
sudo gravity-cli reinstall-ide # 'ide reinstall' と同等
```

### 🔌 SSH プロキシ

Sanity-Gravity は、ホストとコンテナ間で安全な接続を確立する高性能なプロキシマネージャーを搭載しています。これにより、わざわざプライベートキーをコンテナ内にコピーしなくても、**コンテナ内部から直接ホスト側の認証情報を利用して Git 操作を行えます**。

通常は `./sanity-cli up` によってすべてが自動処理されます。手動による修復を行う場合：

```bash
./sanity-cli proxy status   # デーモンとアクティブな接続の確認
./sanity-cli proxy setup    # プロキシサービスの手動起動 / 修復
./sanity-cli proxy remove   # プロキシサービスの終了
```

### 🧩 マルチインスタンス

**いくつかのタスクを並行して進めたいですか？** `--name` パラメータを使うことで、完全に隔絶された無数のサンドボックス環境を同時に動かすことが可能です。

```bash
# 'dev-02' という名前で 2 番目のインスタンスを起動
./sanity-cli up -v core --name dev-02 --workspace /tmp/dev02
```
**確実な競合防止**：任意の名前を指定した場合、システムが現在のホストで空いているポートを自動的に探し出して割り当てます。以後の操作は指定した名前のタグを付けるだけで済みます（例: `./sanity-cli down --name dev-02`）。

### 📸 コンテナスナップショット

作業中の環境状態（インストールしたソフトウェアや、すでにログイン済みの認証状態など）を一つのイメージとして「凍結」し、そこから新しい隔離環境を分岐させることができます。

1. **スナップショットの作成**:
   ```bash
   ./sanity-cli snapshot --name my-base-env --tag my-verified-state:v1
   ```

2. **スナップショットからの分岐**:
   ```bash
   ./sanity-cli up -v kasm --name new-experiment --image my-verified-state:v1
   ```

### 🔄 ランタイム設定同期

システムを再起動することなく、更新した `host_config.py` を適用したい場合、ただ `./sanity-cli sync_config` を実行するだけで、稼働中のコンテナに変更を即座に反映させることができます。

---

## バリアント

| バリアント | 技術スタック     | 最適な用途                                         | アクセス方法                               |
| :--------- | :--------------- | :------------------------------------------------- | :----------------------------------------- |
| **`kasm`** | KasmVNC          | **最高のスムーズさを誇る Web デスクトップ (推奨)** | `https://localhost:8444`                   |
| **`vnc`**  | TigerVNC + noVNC | 従来の VNC クライアントおよび端末の直接接続        | `localhost:5901` / `http://localhost:6901` |
| **`core`** | SSH のみサポート | ヘッドレス制御 / ターミナルオンリーの開発環境      | `ssh -p <port> developer@localhost`        |

## SSH アクセス

すべてのバージョン（グラフィカルな GUI を搭載したバージョンも含む）において、デフォルトで `2222` 番ポートからの SSH 接続が許可されています。これにより、さらに高度な開発が行えます。

* **ヘッドレス実行**: ウィンドウを開くことなくコンソール経由でバックグラウンドからツールを操作できます。
* **ポート転送**: `-L` パラメータを使って、テスト用の Web サーバーやデータベースを簡単に自機へ転送できます（例: `ssh -L 3000:localhost:3000 ...`）。
* **リモート開発**: お手元の VS Code や JetBrains IDE から Remote SSH 拡張機能を使うことで、とても快適かつ安全な環境でコーディングができます。

```bash
# 接続の例 (パスワードは設定値 または antigravity)
ssh -p 2222 developer@localhost
```

## プロジェクト構造

```text
sanity-gravity/
├── sanity-cli          # 🛠️ メインとなる管理および入力用 CLI (Python)
├── sandbox/            # 📦 Docker 構築コンテキストと設定
│   ├── variants/       #    - 各バリアント用の Dockerfiles (core, kasm, vnc)
│   └── rootfs/         #    - 共有オーバーレイファイル (スクリプトと設定情報)
├── tests/              # 🧪 Pytest 統合テストスイート
├── workspace/          # 📂 永続化された作業領域 (マウント先)
└── .github/            # 🐙 CI/CD ルールと Git バージョンテンプレート
```

## 名前の由来

> **"Sanity-Gravity"** は、予測不能なリスクを伴う **「反重力 (Antigravity)」** と呼ばれる人工知能エージェントに対し、確固たる **「重力 (Gravity)」** の制約をもたらすことで、開発者たちの **「正気 (Sanity)」** を守り抜く、というメッセージが込められています。

暴走しかねない AI プログラムを、使い捨てのサンドボックス空間に閉じ込めることで、`rm -rf /` などの予期せぬ破壊行為や、パスワード等のセキュアな情報の流出といった取り返しのつかない事態を未然に防ぎます。

## ライセンス (License)

MIT License
