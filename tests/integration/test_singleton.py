import time

import pytest

pytestmark = pytest.mark.requires_image("ag-xfce-kasm")


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
        
        # Create a fake singleton socket & cookie as if the main app had created them
        setup_script = f"""
        mkdir -p /home/{user}/.config/Antigravity
        touch /home/{user}/.config/Antigravity/SingletonSocket
        touch /home/{user}/.config/Antigravity/SingletonCookie
        chown -R {user}:{host_env['HOST_GID']} /home/{user}/.config
        """
        docker_cli.exec(container_name, f"bash -c '{setup_script}'")
        
        # Execute the wrapper command as if OS handles a URL
        # We pass --version just so it exits quickly without trying to start a real GUI
        # If the wrapper logic is flawed, this invocation will delete the socket.
        docker_cli.exec(container_name, "antigravity --version", user=user)
        
        # Verify if the files were preserved
        check_cmd = f"ls /home/{user}/.config/Antigravity/SingletonSocket"
        result = docker_cli.run(f"docker exec {container_name} bash -c '{check_cmd}'", check=False)
        
        # IF the socket exists, ls succeeds (returncode 0). 
        # IF the wrapper wrongfully deleted it, returncode is 2.
        assert result.returncode == 0, "SingletonSocket was deleted by the wrapper! Auth Redirects will fail."
