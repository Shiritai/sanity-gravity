# Sanity-Gravity: The Antigravity Sandbox

<p align="center">
  <img src="assets/logo.jpg" alt="Sanity-Gravity Logo" width="300">
</p>

[English](README.md) | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md)

**Sanity-Gravity** は、**Agentic AI IDEs** (Google Antigravityなど) のために特別に設計された、安全でコンテナ化されたサンドボックス環境です。AI エージェントの活動を使い捨ての Docker コンテナ内に閉じ込めることで、完全なグラフィカルデスクトップ体験を提供しながら、実行リスクを最小限に抑えます。

## デモ (Demo)

📺 **デモ動画を見る**: [YouTube Link](https://youtu.be/x0DGKuHyx2A)

## なぜ Sanity-Gravity なのか? (Why Sanity-Gravity?)

*   **🛡️ 安全第一 (Safety First)**: 「AI エージェント実行」のリスクを隔離します。エージェントが `rm -rf /` や悪意のあるコードを実行しても、影響を受けるのはコンテナだけで、ホストマシンは安全です。
*   **🖥️ 完全なデスクトップ GUI**: **Ubuntu 22.04 + XFCE4** と **KasmVNC** を内蔵しており、エージェントは実際の Web ブラウザ (Chrome) や GUI アプリケーションを人間と同じように自然に制御できます。
*   **🚀 ゼロ設定 (Zero Config)**: **Antigravity IDE**、Google Chrome、Git、および必須の開発ツールがプリインストールされています。
*   **🔌 シームレスな IO**: ホストユーザーの UID/GID を自動的にマッピングし、ワークスペースをマウントする際によくある「root 所有ファイルの権限地獄」を防ぎます。
*   **🧩 マルチインスタンス対応 (Multi-Instance Capable)**: 複数の独立したサンドボックス環境（例：開発、テスト、本番環境用）を同時に実行でき、ポートの競合も自動的に処理されます。

## クイックスタート

### 前提条件
*   Docker & Docker Compose (v2.0+)
*   Python 3.7+ (`sanity-cli` 用)
*   *(オプション)* **NVIDIA Container Toolkit** (GPU アクセラレーション用)

### インストール

1.  リポジトリをクローンします:
    ```bash
    git clone https://github.com/shiritai/sanity-gravity.git
    cd sanity-gravity
    ```

2.  サンドボックス環境をビルドします:
    ```bash
    ./sanity-cli build
    ```

3.  KasmVNC バリアントを実行します (推奨):
    ```bash
    ./sanity-cli run -v kasm --password mysecret
    ```

4.  **デスクトップにアクセス**:
    ブラウザを開き、以下にアクセスします: **[https://localhost:8444](https://localhost:8444)**
    *   **ユーザー**: `(あなたのホストユーザー名)`
    *   **パスワード**: `mysecret` (指定しない場合、デフォルトは `antigravity`)

> **注意**: 「自己署名証明書 (Self-signed certificate)」の警告が表示される場合があります。これはローカルサンドボックスでは正常な動作です。「詳細設定」->「進む」をクリックしてください。

## CLI の使用法 (`sanity-cli`)

このプロジェクトには、ライフサイクルを管理するためのヘルパースクリプト `sanity-cli` が含まれています:

```bash
./sanity-cli list           # 利用可能なバリアントを一覧表示
./sanity-cli build [name]   # 特定のバリアントをビルド (デフォルト: all)
./sanity-cli run -v [name] [options] # バリアントを実行
  # オプション:
  #   --password [pwd]    (SSH/VNC パスワードを設定, デフォルト: antigravity)
  #   --ssh-port [port]   (デフォルト: 2222)
  #   --kasm-port [port]  (デフォルト: 8444)
  #   --vnc-port [port]   (デフォルト: 5901)
  #   --novnc-port [port] (デフォルト: 6901)
  #   --gpu               (NVIDIA GPU サポートを有効化)
  #   --skip-check        (前提条件のチェックをスキップ)
  #   --workspace [path]  (カスタムワークスペースパスを設定, デフォルト: ./workspace)
  #   --name [name]       (マルチインスタンス用のプロジェクト名を設定, デフォルト: sanity-gravity)

./sanity-cli up -v core     # コンテナを作成して起動 (エイリアス: run)
./sanity-cli down           # コンテナを停止して削除
./sanity-cli stop           # コンテナを停止 (データは保持)
./sanity-cli start          # 停止したコンテナを起動
./sanity-cli restart        # コンテナを再起動
./sanity-cli status         # コンテナの状態を確認
```

### 🧩 マルチインスタンス・サポート

**複数のタスクを並行して実行する必要がありますか？** Sanity-Gravity は、複数の独立したサンドボックス・インスタンスの同時実行をサポートしています。`--name` 引数を使用して、異なるプロジェクト名を指定するだけです。

```bash
# 'dev-02' という名前の2つ目のインスタンスを開始
./sanity-cli up -v core --name dev-02 --workspace /tmp/dev02
```

**競合ゼロ**: カスタム名を使用する場合、`sanity-cli` は利用可能なランダムなポートを自動的に検出して割り当てるため、ポートの競合を心配する必要はありません。割り当てられたポートは出力に明確に表示されます。

特定のインスタンスを停止またはステータス確認するには：

```bash
./sanity-cli status --name dev-02
./sanity-cli stop --name dev-02   # 一時停止 (データ保持)
./sanity-cli down --name dev-02   # 削除 (コンテナ破棄)
```

## バリアント (Variants)

| バリアント | 技術スタック     | 最適な用途                          | アクセス                                   |
| :--------- | :--------------- | :---------------------------------- | :----------------------------------------- |
| **`kasm`** | KasmVNC          | **Web ベースのデスクトップ (推奨)** | `https://localhost:8444`                   |
| **`vnc`**  | TigerVNC + noVNC | レガシー VNC クライアント           | `localhost:5901` / `http://localhost:6901` |
| **`core`** | SSH のみ         | ヘッドレス / ターミナルエージェント | `ssh -p <port> developer@localhost`        |

## SSH アクセス

すべてのバリアント（GUI バリアントの Kasm/VNC を含む）で、デフォルトで SSH が有効になっています。これにより、強力なハイブリッドワークフローが可能になります:

*   **ヘッドレス制御**: デスクトップを開かずに CLI 経由で GUI ツールを自動化できます。
*   **ポートフォワーディング**: コンテナ内の Web アプリやデバッガをホストに転送できます (例: `ssh -L 3000:localhost:3000 ...`)。
*   **ファイル転送**: `scp` や `sftp` を使用して、ビルド成果物を簡単に移動できます。
*   **リモート開発**: エージェントがサンドボックスで実行されている間、ホスト上の VS Code / JetBrains IDE を SSH 経由で接続し、快適にコーディングできます。

**デフォルトポート**: `2222` (`--ssh-port` で設定可能)
**認証情報**: ユーザー `(あなたのホストユーザー名)` / パスワード `antigravity` (またはカスタム)

```bash
# 例: Kasm バリアントに接続
ssh -p 2222 developer@localhost
```

## プロジェクト構造

リポジトリ構成の概要:

```text
sanity-gravity/
├── sanity-cli          # 🛠️ メイン CLI エントリーポイント (Python スクリプト)
├── sandbox/            # 📦 Docker ビルドコンテキストと設定
│   ├── variants/       #    - 各バリアントの Dockerfile (core, kasm, vnc)
│   └── rootfs/         #    - 共有オーバーレイ (スクリプト, 設定ファイル)
├── tests/              # 🧪 Pytest 統合テストスイート
├── workspace/          # 📂 マウントされたユーザーディレクトリ (永続データ)
└── .github/            # 🐙 CI/CD ワークフローと Issue テンプレート
```

## 名前の由来 (What's in a Name?)

> **"Sanity-Gravity"** に込められた意味: 野生的な **Antigravity** (反重力/AI エージェント) の世界に強力な **Gravity** (重力/制約) を提供し、開発者の **Sanity** (正気) を保つこと。

*   **Sanity (正気)**: ホスト環境を「正常」に保ちます。予測不可能な Agentic AI の実行を使い捨てのコンテナに閉じ込めることで、偶発的な損害 (例: `rm -rf /`) や設定汚染を防ぎます。
*   **Gravity (重力)**: **Antigravity** システムに「接地」された実行環境を提供します。浮遊する AI エージェントに、物理法則 (隔離) に拘束されたまま、ツールと対話し世界に影響を与えるための具体的な着地点を与えます。

## ライセンス (License)

このプロジェクトは **Apache License 2.0** の下でライセンスされています。詳細については [LICENSE](LICENSE) を参照してください。
