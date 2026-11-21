# Sandbox Lifecycle Guide

Sanity-Gravity uses a robust, volume-based persistence model combined with strict isolation rules. Understanding the lifecycle of a sandbox instance ensures you never accidentally overwrite or lose data.

## Core Concepts

Every sandbox instance consists of two major components:
1. **The Container**: The ephemeral runtime environment (processes, OS layer, installed software).
2. **The Persistent Volume**: The permanent home directory (`/home/developer`) that stores your bash history, `.config`, `.gemini`, SSH keys, and workspace data.

An "Instance" is uniquely identified by the combination of its **Project Name** (`--name`) and its **Tag** (e.g., `ag-xfce-kasm`).

## Lifecycle Commands

### 1. `sanity-cli up`
* **What it does**: Creates and starts a sandbox container and its persistent volume.
* **Collision Detection**: If a sandbox with the same Project Name and Tag *already exists* (even if stopped), `up` will aggressively block execution to prevent accidental overrides.
  * **To apply configuration changes** (e.g. changing ports or environment variables) and force a recreation of the container while *keeping the volume data intact*, use `--recreate`:
    ```bash
    ./sanity-cli up -v ag-xfce-kasm --name my-project --recreate
    ```

### 2. `sanity-cli stop` & `sanity-cli start`
* **What they do**: Freezes (`stop`) or resumes (`start`) a running sandbox.
* **When to use**: Use this when you are taking a break and want to free up CPU/RAM resources without destroying the container. Your processes stop, but the container entity remains.

### 3. `sanity-cli down` (The "Soft Reset")
* **What it does**: Destroys the **Container**, but *retains* the **Persistent Volume**.
* **When to use**: Use this to fully stop the environment and remove it from Docker's active container list, but keep all your data safe.
* **Resuming**: To resume a sandbox that was `down`ed, run `up` with the exact same Project Name and Tag (you will need to pass `--recreate` if Docker still tracks the stopped container footprint, but typically `down` removes it). The new container will automatically reattach to the old volume, perfectly restoring your state.

### 4. `sanity-cli clean` (The "Nuclear Option")
* **What it does**: Destroys **both** the Container and the Persistent Volume.
* **When to use**: Use this when you want to wipe the slate clean and start from absolute zero. 
* **Warning**: All data inside the sandbox home directory (except your host-mounted `./workspace`) will be permanently lost!

## Common Scenarios & "Gotchas"

**Scenario A: I forgot to pass `--name` when opening a second sandbox.**
* **Result**: `sanity-cli` detects that the default `sanity-gravity` sandbox already exists and **blocks the action**. You are protected from accidentally destroying your first sandbox. To open a second one, run `up` with a new name: `-n sandbox-2`.

**Scenario B: I ran `down` yesterday. Today I run `up` with the same name. What happens?**
* **Result**: Because you used `down` and not `clean`, the volume was saved. Today's `up` command will automatically find the orphaned volume and mount it. **You will inherit yesterday's entire state.**

**Scenario C: I ran `ide update`, then `down` and `up`. Which IDE do I get?**
* **Result**: The one the image pins. `ide update` changes the container, not the volume, so it lasts through `stop`, `start` and `restart` but not through `down`. Software comes from the image and data from the volume; to keep a newer IDE, pull or build a newer image and `up` from it.

**Scenario D: I want a completely fresh environment for a new task.**
* **Result**: Either use a brand new project name (`-n fresh-task`), or if you want to reuse an old name, run `sanity-cli clean -n old-task` first to vaporize the leftover volume before running `up`.

## The Explicit Isolation Guarantee

Sanity-Gravity explicitly forces Docker Compose to name persistent volumes as `sg-<project_name>-<tag>`.
This guarantees perfect isolation:
- `projectA` and `projectB` using the same tag will never share data.
- `ag-xfce-kasm` and `ag-xfce-ssh` in the same project will never share data (preventing database locks and corrupted desktop state between different connection methods).
