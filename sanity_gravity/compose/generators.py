"""Compose-file generators shared by ``up`` and ``upgrade``.

These take the parsed plugin manifest plus runtime args and write a
``docker-compose.*.yml`` overlay into ``config/``. They live next to
the verbs because they're verb-side glue — the pure
:class:`~sanity_gravity.compose.builder.ComposeBuilder` knows nothing
about the registry / proxy / git config.
"""
from __future__ import annotations

import os
import sys

from sanity_gravity.cli.colors import Colors
from sanity_gravity.cli.io import (
    print_error,
    print_info,
    print_success,
    print_warning,
)
from sanity_gravity.cli.registry import VALID_TAGS, get_registry, parse_tag
from sanity_gravity.compose.builder import ComposeBuilder, ComposeService

try:
    from sanity_gravity.infra.proxy_manager import ProxyManager
except ImportError:  # pragma: no cover - lib is shipped with the repo
    ProxyManager = None


def generate_compose_for_tag(tag):
    """Generate the per-tag docker-compose YAML, driven by plugin manifests.

    Ports / compose params / environment overrides are merged from the
    agent, desktop, and connector manifests — any kind may contribute
    any optional section. Merge order is **connector first, then agent,
    then desktop** (last-write-wins on collisions). Connectors typically
    own the network-facing ports; agents and desktops typically only add
    env vars, but the schema places no restriction.
    """
    agent, desktop, connector = parse_tag(tag)
    reg = get_registry()
    connector_m = reg.connectors[connector]
    agent_m = reg.agents.get(agent)
    desktop_m = reg.desktops.get(desktop)

    service_name = tag

    image = (
        f"${{SANITY_IMAGE_{tag.upper().replace('-', '_')}"
        f":-sanity-gravity:{tag}}}"
    )

    environment = {
        "HOST_UID": "${HOST_UID:-1000}",
        "HOST_GID": "${HOST_GID:-1000}",
        "HOST_USER": "${HOST_USER:-developer}",
        "HOST_PASSWORD": "${HOST_PASSWORD:-antigravity}",
    }
    # Merge order: connector, then agent, then desktop. Last-write-wins.
    for plugin_m in (connector_m, agent_m, desktop_m):
        if plugin_m is None:
            continue
        for k, v in plugin_m.environment:
            environment[k] = v

    # Ports: union across kinds, keyed by internal port to avoid duplicate
    # publish entries (a host:container line is identified by its container
    # port). Connector wins on conflicts since it's first in the merge.
    seen_internal: dict[int, str] = {}
    for plugin_m in (connector_m, agent_m, desktop_m):
        if plugin_m is None:
            continue
        for p in plugin_m.ports:
            if p.internal in seen_internal:
                continue
            seen_internal[p.internal] = f"${{{p.env_var}:-{p.default}}}:{p.internal}"
    ports = list(seen_internal.values())

    # Compose overlay: same connector-then-agent-then-desktop precedence.
    # Last non-None wins for each scalar field.
    shm_size = connector_m.compose.shm_size
    restart = connector_m.compose.restart
    stop_grace_period = connector_m.compose.stop_grace_period
    for plugin_m in (agent_m, desktop_m):
        if plugin_m is None:
            continue
        ov = plugin_m.compose
        if ov.shm_size is not None:
            shm_size = ov.shm_size
        if ov.restart is not None:
            restart = ov.restart
        if ov.stop_grace_period is not None:
            stop_grace_period = ov.stop_grace_period

    svc = ComposeService(
        name=service_name,
        image=image,
        command=["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"],
        environment=environment,
        # Persistence model: the whole home dir lives on a per-project
        # named volume (explicitly defined as sg-<project>-<tag>)
        # so agent state outside ./workspace — ~/.gemini, ~/.config,
        # ~/.antigravity, ~/.claude, logins, history — survives container
        # recreation / upgrade instead of dying with the writable layer.
        # Docker seeds an empty volume from the image's /home; entrypoint
        # chowns it each start. The workspace host bind is nested inside
        # and stays the source of truth for code. ``home-volume`` label
        # lets `upgrade` tell migrated containers from un-migrated ones.
        volumes=[
            f"sg_{tag}:/home/${{HOST_USER:-developer}}",
            "${WORKSPACE_DIR:-./workspace}:/home/${HOST_USER:-developer}/workspace",
        ],
        ports=ports,
        network_mode="bridge",
        shm_size=shm_size,
        restart=restart,
        stop_grace_period=stop_grace_period,
        cap_drop=["ALL"],
        cap_add=[
            "CHOWN",
            "DAC_OVERRIDE",
            "FOWNER",
            "KILL",
            "SETGID",
            "SETUID",
            "NET_BIND_SERVICE",
            "SYS_CHROOT",
            "AUDIT_WRITE",
        ],
        pids_limit=2048,
        ulimits={
            "nofile": {"soft": 65536, "hard": 65536},
            "core": {"soft": 0, "hard": 0},
        },
        labels={
            "sanity.gravity.managed": "true",
            "sanity.gravity.home-volume": "true",
        },
    )

    config_dir = "config"
    output_file = os.path.join(config_dir, f"docker-compose.{tag}.yml")
    (
        ComposeBuilder()
        .add_service(svc)
        .declare_volume(f"sg_{tag}", config={"name": f"sg-${{COMPOSE_PROJECT_NAME:-sanity-gravity}}-{tag}"})
        .write(output_file)
    )

    return output_file, service_name


def generate_git_compose(username, service_name=None):
    """Generate a docker-compose override that mounts gitconfig + ssh-agent."""
    print_info("Checking for Git configuration...")

    home = os.path.expanduser("~")
    gitconfig = os.path.join(home, ".gitconfig")
    ssh_auth_sock = None

    if ProxyManager:
        pm = ProxyManager()
        if pm.is_enabled() and os.path.exists(pm.get_socket_path()):
            ssh_auth_sock = pm.get_socket_path()
            print_success(f"Using SSH Proxy ({ssh_auth_sock})")
        else:
            reason = "Unknown"
            if not pm.is_enabled():
                reason = "Service not enabled"
            elif not os.path.exists(pm.get_socket_path()):
                reason = f"Socket missing at {pm.get_socket_path()}"

            print_warning(f"SSH Proxy is NOT set up ({reason}).")
            print_warning(
                "Strict Policy: Git operations inside the container will NOT "
                "have access to your SSH keys."
            )
            print_info(
                "Without Proxy, the container cannot restart seamlessly if "
                "the host reboots."
            )
            print_info("Do you want to enable SSH Proxy now? (Recommended)")

            if sys.stdin.isatty():
                choice = input(
                    f"{Colors.BOLD}Enable SSH Proxy? [Y/n]: {Colors.ENDC}"
                ).strip().lower()
                if choice in ["", "y", "yes"]:
                    try:
                        print_info("Setting up Proxy...")
                        pm.setup()
                        if pm.is_enabled():
                            ssh_auth_sock = pm.get_socket_path()
                            print_success("SSH Proxy enabled and selected.")
                    except Exception as e:
                        print_error(f"Failed to setup proxy: {e}")
                        sys.exit(1)
                else:
                    print_warning(
                        "Skipping SSH Agent integration. Git inside container "
                        "will require manual authentication."
                    )
            else:
                print_warning(
                    "Non-interactive mode: Skipping SSH Agent integration "
                    "(Proxy required)."
                )
    else:
        print_warning("ProxyManager not found. Skipping SSH Agent.")

    volumes = []
    environment = {}

    if os.path.exists(gitconfig):
        volumes.append(f"{gitconfig}:/home/{username}/.gitconfig")
        print_success("Found .gitconfig")
    else:
        print_info(".gitconfig not found on host.")

    if ssh_auth_sock and os.path.exists(ssh_auth_sock):
        volumes.append(f"{ssh_auth_sock}:/tmp/ssh-agent.sock")
        environment["SSH_AUTH_SOCK"] = "/tmp/ssh-agent.sock"

    if not volumes:
        print_info("Git Context Sharing skipped (no config found).")
        return None

    services = [service_name] if service_name else VALID_TAGS
    builder = ComposeBuilder()
    for svc in services:
        builder.add_service(ComposeService(name=svc, image=""))
        builder.merge_volumes(svc, volumes)
        if environment:
            builder.merge_environment(svc, environment)

    config_dir = "config"
    output_file = os.path.join(config_dir, "docker-compose.git.yml")
    builder.write(output_file)

    return output_file


def generate_resource_compose(cpus, memory, service_name=None):
    """Generate a docker-compose override that applies CPU/memory limits."""
    if not cpus and not memory:
        return None

    services = [service_name] if service_name else VALID_TAGS
    builder = ComposeBuilder()
    for svc in services:
        builder.add_service(ComposeService(name=svc, image=""))
        builder.set_deploy_resources(svc, cpus=cpus, memory=memory)

    config_dir = "config"
    output_file = os.path.join(config_dir, "docker-compose.resources.yml")
    builder.write(output_file)

    return output_file
