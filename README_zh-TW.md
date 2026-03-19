# Sanity-Gravity: The Antigravity Sandbox

<p align="center">
  <img src="assets/logo.jpg" alt="Sanity-Gravity Logo" width="300">
</p>

<p align="center">
  <em>專為 Agentic AI IDEs 打造的現代化安全容器沙箱環境</em>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh-TW.md">繁體中文</a> | <a href="README_ja.md">日本語</a>
</p>

---

## TL;DR

**Sanity-Gravity** 是一個專為 Antigravity 工作流程量身打造的現代化「零設定」GUI 沙箱。它能將所有潛在的高風險動作徹底限制在用完即棄的 Docker 容器中，並同時順暢地將完整的 XFCE4 桌面體驗串流至您的瀏覽器。

**數秒內啟動安全的 Antigravity 開發環境：**

```bash
# 1. 建置基底映像檔
./sanity-cli build

# 2. 啟動沙箱並無縫掛載持久化工作目錄
./sanity-cli up -v kasm --name my-agent-task --workspace ./ai-workspace
```

您的安全桌面已就緒，請前往 **https://localhost:8444**！
- **登入帳號**: `(您主機上的實際 User 名稱)`
- **登入密碼**: `antigravity` (或是您透過 `--password` 所設定的密碼)

📺 **[進入觀看實際展示](https://youtu.be/x0DGKuHyx2A)**

## 目錄

- [Sanity-Gravity: The Antigravity Sandbox](#sanity-gravity-the-antigravity-sandbox)
  - [TL;DR](#tldr)
  - [目錄](#目錄)
  - [為什麼選擇 Sanity-Gravity？](#為什麼選擇-sanity-gravity)
  - [快速開始](#快速開始)
    - [系統需求](#系統需求)
    - [安裝步驟](#安裝步驟)
  - [指令參考 (`sanity-cli`)](#指令參考-sanity-cli)
  - [進階功能](#進階功能)
    - [🛠️ IDE 維護與安全升級](#️-ide-維護與安全升級)
      - [從宿主機使用 Sanity-CLI](#從宿主機使用-sanity-cli)
      - [在容器內使用 Gravity-CLI](#在容器內使用-gravity-cli)
    - [🔌 SSH 代理穿透](#-ssh-代理穿透)
    - [🧩 多重實例](#-多重實例)
    - [📸 容器快照](#-容器快照)
    - [🔄 動態設定同步](#-動態設定同步)
  - [版本選擇](#版本選擇)
  - [SSH 存取](#ssh-存取)
  - [專案結構](#專案結構)
  - [名稱的意義](#名稱的意義)
  - [Licence](#licence)

---

## 為什麼選擇 Sanity-Gravity？

| 核心特色           | 設計對應的好處                                                                                           |
| :----------------- | :------------------------------------------------------------------------------------------------------- |
| **🛡️ 絕對安全隔離** | 徹底保護主機本身。即使 AI 代理執行 `rm -rf /` 或下載了危險程式碼，只有沙箱會被破壞，主機能保持安然無恙。 |
| **🖥️ 完整圖形桌面** | 內置 **Ubuntu 24.04 + XFCE4** 與高效 **KasmVNC**。AI 代理能如同人類一樣操作瀏覽器及 GUI 介面。           |
| **🚀 開箱即用基底** | 預裝 **Antigravity IDE**、Google Chrome 和 Git 等關鍵核心套件，讓您零等待直接開始。                      |
| **🔌 無縫磁碟 I/O** | 智慧對應主機當前的 UID 和 GID，完全避免了 Volume 掛載後檔案變成 root 擁有權的麻煩。                      |
| **🧩 多開獨立實例** | 可平行建立各種任務環境，支援多專案隔離，且系統會自動分配未使用的連接埠，保證永遠不發生衝突。             |
| **📸 凍結還原快照** | 將目前的環境狀態（如已安裝的軟體、登入狀態）快速凍結，變成全新的映像檔分支。                             |
| **🔄 IDE 安全升級** | 透過 `sanity-cli ide` 進行遠端安全升級與修復，內建的防護層能確保更新過程中不會發生崩潰。                 |
| **🔑 SSH 代理穿透** | 完全不需要複製任何私鑰進容器，就能在沙箱內安全地使用主機的憑證，自由進行常規的 Git 操作。                |

## 快速開始

### 系統需求

* Docker & Docker Compose (v2.0+)
* Python 3.7+ (用於驅動 `sanity-cli`)
* *(選用)* **NVIDIA Container Toolkit** (用來支援 GPU 加速)
* **支援環境**: 已在 **Ubuntu (amd64/arm64)** 以及 **macOS 26.0.1 (Apple Silicon M1)** 上通過完整驗證與測試。

### 安裝步驟

1. 複製本專案庫:
   ```bash
   git clone https://github.com/shiritai/sanity-gravity.git
   cd sanity-gravity
   ```

2. 建置您專屬的沙箱基底映像檔:
   ```bash
   ./sanity-cli build
   ```

3. 啟動 KasmVNC 變體版本 (推薦使用該版本以獲得網頁流暢體驗):
   ```bash
   ./sanity-cli up -v kasm --password mysecret
   ```

4. **存取您的桌面**:
   打開瀏覽器並前往: **[https://localhost:8444](https://localhost:8444)**
   * **使用者名稱**: `(您主機上的實際 User 名稱)`
   * **密碼**: `mysecret` (預設為 `antigravity`)

> **注意**: 如果遇到「自簽署憑證」警告，這在本地端為正常現象，請點選「進階」並繼續前往。

## 指令參考 (`sanity-cli`)

`sanity-cli` 作為管理沙箱群生命週期的中央調度工具，提供以下指令：

```bash
# 生命週期管理
./sanity-cli up -v [name]   # 建立並啟動容器 (附帶以下選用引數)
  --password [pwd]          # 自訂 SSH/VNC 密碼 (預設: antigravity)
  --workspace [path]        # 指派專案的工作區 (預設: ./workspace)
  --name [name]             # 指定全域辨識的專案名稱 (預設: sanity-gravity)
  --cpus [limit]            # 啟用 CPU 配額 (例: 1.5)
  --memory [limit]          # 限制記憶體用量 (例: 4G)
  --gpu                     # 啟用 NVIDIA GPU 支援
./sanity-cli down           # 停止並完全刪除容器與網路
./sanity-cli stop           # 僅暫停容器 (保留運行資料)
./sanity-cli start          # 將已暫停的容器重新喚醒
./sanity-cli restart        # 強制重啟運行中的容器

# 狀態與環境監控
./sanity-cli status         # 查看所有線上實例與 Health 狀態
./sanity-cli shell          # 一鍵進入容器內部的 Shell (zsh)
./sanity-cli open           # 以預設瀏覽器打開桌面 VNC 介面

# 維護與網路同步
./sanity-cli ide <action>   # 自動派送容器內部 IDE 的系統更新與維修
./sanity-cli proxy <action> # 管理核心 SSH Proxy Daemon 狀態
./sanity-cli sync_config    # 將主機最新設定推送至正在運行的容器中
./sanity-cli snapshot       # 將當前狀態凍結為新映像檔
```

---

## 進階功能

### 🛠️ IDE 維護與安全升級

Sanity-Gravity 內建了嚴密的防護機制，能夠防止因為系統層級的 `apt upgrade` 而導致 IDE 或 Google Chrome 瀏覽器被意外解除安裝、喪失特權，進而引發崩潰。

我們將宿主機的管理與容器內部的軟體管理進行了嚴格的劃分：

- **宿主機**：`sanity-cli` 負責管理所有容器的生命週期。當執行維護指令時，它會 **自動將最新版的防護腳本熱注入** 進目標容器，以確保舊版容器映像檔的向下相容性，並自動部署修補措施。
- **容器內部**：`gravity-cli` (容器內建的守護腳本) 負責安全地管理 Antigravity IDE 以及 Google Chrome 瀏覽器。它透過底層封裝 (`dpkg-divert`) 確保它們的 `--no-sandbox` 啟動特權與捷徑不會被後續的系統更新給抹除或破壞。

#### 從宿主機使用 Sanity-CLI

如果您遇到 IDE 崩潰 (例如 Google Gemini 強制更新所引發的瀏覽器異常) 或是單純想安全地將 IDE 更新到最新版，請在宿主機使用對應的 `ide` 指令。
> **注意**: `--name` 參數用於指定目標實例 (預設為 `sanity-gravity`)。若您同時運行多套隔離環境，請透過 `./sanity-cli status` 確認名稱。

```bash
# 安全地透過 apt 將 Antigravity IDE 更新至最新版
./sanity-cli ide update --name sanity-gravity

# 核彈級修復：徹底清除並重新乾淨安裝 IDE 以解決持續性的極端崩潰問題
./sanity-cli ide reinstall --name sanity-gravity
```
*(這些指令會自動在目標容器內部以 root 身分呼叫 `gravity-cli` 腳本，所有的防護與升級程序都在容器內部，維持您的主機環境乾淨無染。)*

#### 在容器內使用 Gravity-CLI

如果您已經在容器的終端機環境中 (例如透過 `./sanity-cli shell`)，您可以直接呼叫 `gravity-cli` 工具。請注意，您必須以系統管理員身分 (例如加上 `sudo`) 來執行這些功能。

```bash
sudo gravity-cli update-ide    # 等同於 'sanity-cli ide update'
sudo gravity-cli reinstall-ide # 等同於 'sanity-cli ide reinstall'
```

### 🔌 SSH 代理穿透

Sanity-Gravity 內建了一個智慧型的代理管理器，能在主機與容器之間建立安全橋接。這代表在容器內部進行 `git` 相關操作時，能夠**直接打通並使用您主機上的憑證，完全不需要把私鑰帶入容器內**。

一般而言，`./sanity-cli up` 會妥善為您包辦一切。如遇異常需要手動重啟：

```bash
./sanity-cli proxy status   # 檢查連線以及守護行程狀態
./sanity-cli proxy setup    # 手動啟動/修復 Proxy 服務
./sanity-cli proxy remove   # 終止 Proxy 服務
```

### 🧩 多重實例

**需要平行處理好幾個不同的任務？** Sanity-Gravity 支援透過 `--name` 參數，同時運行無數個完全獨立的沙箱環境。

```bash
# 啟動名為 'dev-02' 的第二個實例
./sanity-cli up -v core --name dev-02 --workspace /tmp/dev02
```
**保證不發生衝突**：當您指定自訂名稱時，`sanity-cli` 會自動偵測並為您分配主機端尚未被佔用的連接埠。後續進行操作時，只需加上對應的名稱標籤即可 (例如: `./sanity-cli down --name dev-02`)。

### 📸 容器快照

您可以將目前的環境狀態（例如您精心調整好的設定檔或已登入認證的服務狀態）完整凍結，建立一個**快照映像檔**，並以此為基礎衍生出全新的隔離專案。

1. **建立快照**:
   ```bash
   ./sanity-cli snapshot --name my-base-env --tag my-verified-state:v1
   ```

2. **基於快照建立新分支**:
   ```bash
   ./sanity-cli up -v kasm --name my-new-project --image my-verified-state:v1
   ```

### 🔄 動態設定同步

如果您更新了 `host_config.py` 但不想重啟環境，只需要執行 `./sanity-cli sync_config` 即可將這些設定熱更新至運行中的容器內。

---

## 版本選擇

| 版本       | 技術堆疊         | 最佳用途                                 | 存取方式                                   |
| :--------- | :--------------- | :--------------------------------------- | :----------------------------------------- |
| **`kasm`** | KasmVNC          | **順暢度最高之 Web 網頁桌面 (推薦使用)** | `https://localhost:8444`                   |
| **`vnc`**  | TigerVNC + noVNC | 傳統舊版 VNC 方案及終端軟體直接連線      | `localhost:5901` / `http://localhost:6901` |
| **`core`** | 僅支援 SSH       | 背景調度 / 純終端機開發情境              | `ssh -p <port> developer@localhost`        |

## SSH 存取

所有的版本，**包含具備圖形介面的映像檔**，預設都會對外開放連接埠 `2222` 作為 SSH 連線之用。這為整套環境解除了更多進階開發模式的限制：

*   **無頭控制**：能結合命令列，在背景操作工具而不需開啟完整的桌面視窗。
*   **通訊埠轉發**：透過 `-L` 參數，輕易將測試用的 Web 伺服器與資料庫透傳至本機 (例如: `ssh -L 3000:localhost:3000 ...`)。
*   **遠端開發**：您可以使用電腦本身的 VS Code 或 JetBrains IDE 搭配 Remote SSH 套件連入，獲得最流暢且安全的編輯體驗。

```bash
# 連線範例 (密碼採用設定密碼或 antigravity)
ssh -p 2222 developer@localhost
```

## 專案結構

```text
sanity-gravity/
├── sanity-cli          # 🛠️ 管理中樞的命令列入口
├── sandbox/            # 📦 Docker 建置環境檔
│   ├── variants/       #    - 變體描述與專用 Dockerfiles (core, kasm, vnc)
│   └── rootfs/         #    - 共用系統重疊覆寫區塊 (所有安全腳本及環境變數)
├── tests/              # 🧪 專案的全面 Pytest 整合測試套件
├── workspace/          # 📂 預設綁定的持久化工作熱區
└── .github/            # 🐙 CI/CD 與原始碼管理工具
```

## 名稱的意義

> **"Sanity-Gravity"** 象徵著：在這個可能充滿失控與未知風險的 **「反重力 (Antigravity)」** 人工智慧時代，為您的環境提供最穩固的 **「引力 (Gravity)」** 拘束，同時保護開發人員的 **「理智 (Sanity)」**。

我們將所有未經檢驗的 AI 測試拘禁於用完即棄的沙箱中，徹底拔除意外刪除重要檔案或是憑證劫持等各式不可逆的極端傷害。

## Licence

MIT License
