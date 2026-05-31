# Sanity-Gravity: The Antigravity Sandbox

<p align="center">
  <img src="assets/logo.jpg" alt="Sanity-Gravity Logo" width="300">
</p>

<p align="center">
  <em>為 Agentic AI 打造的容器化沙箱 — 完整桌面、無頭 CLI 或純 SSH，數秒內就緒。</em>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh-TW.md">繁體中文</a> | <a href="README_ja.md">日本語</a>
</p>

<p align="center">
  <a href="https://github.com/shiritai/sanity-gravity/actions"><img src="https://github.com/shiritai/sanity-gravity/actions/workflows/ci-pr.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
</p>

## 系統需求

* Docker & Docker Compose (v2.0+)
* Python 3.7+
* **已驗證環境**：Ubuntu (amd64/arm64)、macOS (Apple Silicon)

## TL;DR

```bash
# 1. 複製專案
git clone https://github.com/shiritai/sanity-gravity.git
cd sanity-gravity

# 2. (可選) 本地建置映像檔（若不想依賴 GHCR 自動拉取）
# ./sanity-cli build

# 3. 啟動沙箱（若本地無映像檔，會自動從 GHCR 拉取！）
./sanity-cli up -v ag-xfce-kasm --password mysecret
```

開啟 **https://localhost:8444** — 沙箱桌面已就緒！

* **帳號**：你的主機作業系統使用者名稱
* **密碼**：`mysecret`（預設：`antigravity`）

> localhost 出現的自簽憑證警告為正常現象，請點擊「進階」繼續。

## 為什麼選擇 Sanity-Gravity？

AI 代理會執行任意程式碼。一個意外的 `rm -rf /` 就足以讓你的主機化為灰燼。Sanity-Gravity 將所有代理行為限制在用完即棄的 Docker 容器內，同時將完整的桌面體驗串流至你的瀏覽器 — 或只提供最輕量的 SSH 終端機環境。

| 核心特色              | 說明                                                                                                     |
| :-------------------- | :------------------------------------------------------------------------------------------------------- |
| **主機絕對安全**      | 即使 AI 代理執行了 `rm -rf /` 或下載了惡意程式碼，只有沙箱會被摧毀。你的主機始終安然無恙。              |
| **完整圖形桌面**      | Ubuntu 24.04 + XFCE4 + KasmVNC。代理能如同真人一般操作瀏覽器及 GUI 應用程式。                            |
| **無頭 CLI 代理**     | 專為 Gemini CLI 與 Claude Code 設計的最小化映像 — 無桌面負擔，僅需 SSH 即可運行。                        |
| **開箱即用**          | 預先安裝 Antigravity IDE、Google Chrome 與 Git 等關鍵套件。零等待立即開始。                               |
| **無縫磁碟 I/O**     | 智慧 UID/GID 對應。Volume 掛載後不會產生 root 擁有權的檔案災難。                                        |
| **多重實例**          | 平行建立各種隔離沙箱，未指定時系統自動分配連接埠，保證零衝突；也支援手動指定連接埠。                                                   |
| **容器凍結快照**      | 將目前環境狀態（已安裝軟體、登入狀態）凍結為全新的映像檔分支。                                           |
| **IDE 安全升級**      | 內建 `dpkg-divert` 防護層，防止 `apt upgrade` 破壞 Antigravity 或 Chrome。                               |
| **SSH 代理穿透**      | 在容器內直接使用主機的 SSH 金鑰 — 完全不需要複製任何私鑰。                                              |
| **多架構支援**        | 所有映像檔同時支援 `amd64` 與 `arm64`。                                                                  |

📺 **[進入觀看 YouTube 展示影片](https://youtu.be/x0DGKuHyx2A)**

## 選擇你的沙箱

每個映像檔由一個標籤描述：**`{agent}-{desktop}-{connector}`**。根據你的用途選擇：

| 我想要...                       | 標籤             | 連線方式                   |
| :------------------------------ | :--------------- | :------------------------- |
| 用瀏覽器開啟 Antigravity IDE    | `ag-xfce-kasm`   | `https://localhost:8444`   |
| 用 VNC 開啟 Antigravity IDE     | `ag-xfce-vnc`    | `localhost:5901`           |
| 在終端機使用 Gemini CLI         | `gc-none-ssh`    | `ssh -p 2222 ...`         |
| 搭配桌面使用 Gemini CLI         | `gc-xfce-kasm`   | `https://localhost:8444`   |
| 在終端機使用 Claude Code        | `cc-none-ssh`    | `ssh -p 2222 ...`         |
| 搭配桌面使用 Claude Code        | `cc-xfce-kasm`   | `https://localhost:8444`   |

> **第一次使用？** 從 **`ag-xfce-kasm`** 開始 — 直接在瀏覽器中獲得完整的桌面體驗。

共有 **11 個有效組合**。完整矩陣、維度模型與約束規則請參考 [模組化標籤系統](docs/tags.md)。

## 命令參考

### 生命週期

```bash
./sanity-cli up -v <tag>        # 啟動沙箱
  --password <pwd>              #   SSH/VNC 密碼（預設：antigravity）
  --workspace <path>            #   掛載的主機目錄（預設：./workspace）
  --name <name>                 #   多重實例的專案名稱（預設：sanity-gravity）
  --cpus <n> --memory <n>       #   資源限制（例：--cpus 2 --memory 4G）
  --image <img>                 #   使用快照映像檔取代預設映像

./sanity-cli down               # 停止並移除容器
./sanity-cli stop / start       # 暫停 / 恢復
./sanity-cli restart            # 強制重啟
./sanity-cli clean              # 深度清理：容器、卷與本地映像
```

### 狀態檢視

```bash
./sanity-cli status             # 顯示運行中的實例
./sanity-cli shell              # 進入容器 Shell（預設 zsh，失敗時自動退回 bash）
  --use {zsh,bash}              #   明確指定 shell（停用自動退回）
./sanity-cli open               # 用瀏覽器開啟網頁桌面
```

### 建置

```bash
./sanity-cli build [tag...]     # 建置映像檔（預設：全部）
  --no-cache                    #   停用 Docker 層快取
./sanity-cli list               # 顯示所有有效標籤
./sanity-cli list --json        # JSON 輸出（供 CI 矩陣使用）
./sanity-cli check              # 驗證 Docker 前置需求
```

所有旗標與環境變數的完整參考：[CLI 完整手冊](docs/cli-reference.md)

## 進階功能

### IDE 維護與安全升級

Sanity-Gravity 內建嚴密的防護機制，能夠防止 `apt upgrade` 意外解除安裝 IDE 或瀏覽器。

- **宿主機端**：`sanity-cli` 管理容器的整體生命週期。維護指令會 **自動將最新版的防護腳本熱注入** 至目標容器，確保與舊版快照的向下相容性。
- **容器內部**：`gravity-cli`（內建工具）透過 `dpkg-divert` 安全地管理 Antigravity IDE 與 Google Chrome，確保它們的 `--no-sandbox` 啟動特權不會被後續系統更新所抹除。

#### 從宿主機操作

```bash
# 安全地將 IDE 更新至最新版本
./sanity-cli ide update --name sanity-gravity

# 核彈級修復：完整清除並重新安裝以修復持續性崩潰
./sanity-cli ide reinstall --name sanity-gravity
```

#### 在容器內部操作

```bash
sudo gravity-cli update-ide     # 等同 'ide update'
sudo gravity-cli reinstall-ide  # 等同 'ide reinstall'
```

### SSH 代理穿透

內建的代理服務會在主機與容器之間橋接 SSH Agent Socket。這代表在容器內可以直接使用主機的私鑰進行 `git push` / `git pull`，**完全不需要複製任何金鑰**。

`./sanity-cli up` 會自動設置。如需手動介入：

```bash
./sanity-cli proxy status       # 檢查代理及連線狀態
./sanity-cli proxy setup        # 手動啟動/修復代理
./sanity-cli proxy remove       # 終止代理服務
```

### 多重實例

透過 `--name` 參數平行運行無限個隔離沙箱：

```bash
# 啟動第二個實例
./sanity-cli up -v ag-xfce-kasm --name dev-02 --workspace /tmp/dev02
```

**零衝突保證**：使用自訂名稱時，`sanity-cli` 會自動偵測並分配空閒的主機連接埠。透過 `./sanity-cli status` 查看分配的連接埠，以 `--name` 指定操作目標（例：`./sanity-cli down --name dev-02`）。

### 容器快照

將目前的環境狀態 — 已安裝的軟體、登入會話、自訂設定 — 凍結為可重複使用的映像檔。

1. **建立快照**：
   ```bash
   ./sanity-cli snapshot --name my-base-env --tag my-verified-state:v1
   ```

2. **從快照啟動**：
   ```bash
   ./sanity-cli up -v ag-xfce-kasm --name new-experiment --image my-verified-state:v1
   ```

## SSH 存取

所有映像檔 — 包含 GUI 版本 — 預設在連接埠 `2222` 開放 SSH。可用於：

- **無頭自動化** — 從主機腳本控制任務，無需開啟桌面
- **通訊埠轉發** — `ssh -L 3000:localhost:3000 -p 2222 $USER@localhost`
- **遠端開發** — VS Code Remote SSH、JetBrains Gateway

```bash
ssh -p 2222 $USER@localhost
```

## 專案結構

```
sanity-gravity/
├── sanity-cli                  # CLI 入口（Python 3，無外部相依）
├── sandbox/
│   ├── Dockerfile.base         # 基底層：Ubuntu 24.04 + SSH + supervisord
│   ├── layers/
│   │   ├── desktops/           # xfce、none
│   │   ├── agents/             # ag（Antigravity）、gc（Gemini CLI）、cc（Claude Code）
│   │   └── connectors/         # kasm（KasmVNC）、vnc（TigerVNC）、ssh
│   └── rootfs/                 # 共用覆疊層（entrypoint、gravity-cli、supervisor 設定）
├── lib/                        # Proxy Manager 模組
├── config/                     # 動態產生的 docker-compose 檔（git-ignored）
├── tests/                      # Pytest 整合測試套件
├── workspace/                  # 預設掛載的工作目錄
└── .github/workflows/          # CI/CD 管線
```

關於四層 FROM 鏈式建置系統與 CI 架構的詳細說明，請參考 [建置架構](docs/architecture.md) 及 [CI/CD](docs/ci-cd.md)。

## 名稱的意義

> **"Sanity-Gravity"** — 在不可預測的 **Antigravity**（AI 代理）世界中，提供堅實的 **Gravity**（約束），以維護開發者的 **Sanity**（理智）。

我們將所有未經檢驗的 AI 執行行為拘禁於用完即棄的沙箱中，徹底杜絕不可逆的損害：意外刪除檔案、憑證劫持、環境污染。

## 授權條款

[Apache License 2.0](LICENSE)
