import time

import pytest

pytestmark = pytest.mark.requires_image("ag-xfce-kasm")

#: Electron derives userData from product.json's ``nameLong``, so the
#: directory carries the product name verbatim - space included. Under
#: 1.x it was ``Antigravity``; the standalone 2.x IDE calls itself
#: ``Antigravity IDE``. Every path below has to stay quoted because of it.
CONFIG_DIR = ".config/Antigravity IDE"


class TestAntigravitySingleton:
    def test_auth_redirect_preserves_singleton_socket(self, clean_container, docker_cli, host_env, image):
        """
        Verify that calling the `antigravity` wrapper does not delete the SingletonSocket
        if it's simply trying to pass Auth Redirect URIs to an existing instance.
        """
        container_name = clean_container("sanity-test-singleton")

        env_flags = " ".join([f"-e {k}='{v}'" for k, v in host_env.items()])

        # Start the container in the background
        docker_cli.run(f"docker run -d --name {container_name} {env_flags} {image} sleep 3600")

        # Wait a moment for container to initialize
        time.sleep(2)

        # We simulate the Auth Redirect scenario. If socket cleaning is erroneously placed
        # in the wrapper, calling `antigravity` will delete the socket.

        user = host_env["HOST_USER"]
        config = f"/home/{user}/{CONFIG_DIR}"

        # Create a fake singleton socket & cookie as if the main app had created them
        setup_script = f"""
        mkdir -p "{config}"
        touch "{config}/SingletonSocket"
        touch "{config}/SingletonCookie"
        chown -R {user}:{host_env['HOST_GID']} /home/{user}/.config
        """
        docker_cli.exec(container_name, f"bash -c '{setup_script}'")

        # Execute the wrapper command as if OS handles a URL. `antigravity` is
        # the compatibility alias the 2.x layer keeps for the 1.x name; it
        # reaches the same wrapper as `antigravity-ide`.
        # We pass --version just so it exits quickly without trying to start a real GUI
        # If the wrapper logic is flawed, this invocation will delete the socket.
        docker_cli.exec(container_name, "antigravity --version", user=user)

        # Verify if the files were preserved
        check_cmd = f'ls "{config}/SingletonSocket"'
        result = docker_cli.run(
            f'docker exec {container_name} bash -c \'{check_cmd}\'', check=False
        )

        # IF the socket exists, ls succeeds (returncode 0).
        # IF the wrapper wrongfully deleted it, returncode is 2.
        assert result.returncode == 0, "SingletonSocket was deleted by the wrapper! Auth Redirects will fail."

    def test_both_names_reach_the_wrapper(self, clean_container, docker_cli, host_env, image):
        """``antigravity-ide`` is the 2.x program name, ``antigravity`` the
        alias kept for the 1.x one. Both have to answer on PATH: the first
        is what the .desktop entries and the openbox detection spell, the
        second is what existing docs, scripts and habits spell."""
        container_name = clean_container("sanity-test-singleton-names")
        env_flags = " ".join([f"-e {k}='{v}'" for k, v in host_env.items()])
        docker_cli.run(f"docker run -d --name {container_name} {env_flags} {image} sleep 3600")
        time.sleep(2)
        user = host_env["HOST_USER"]

        for name in ("antigravity-ide", "antigravity"):
            result = docker_cli.run(
                f"docker exec -u {user} {container_name} "
                f"bash -lc 'command -v {name}'",
                check=False,
            )
            assert result.returncode == 0, f"{name} is not on the sandbox user's PATH"
