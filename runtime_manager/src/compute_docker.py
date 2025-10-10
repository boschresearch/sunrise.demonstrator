# Copyright (c) 2025 Robert Bosch GmbH
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Compute backend interface for build/run operations of systems.
"""

import os
import logging
import enum
import tarfile
import pathlib
import docker
import compute_if


def change_file_permission(tarinfo):
    """Changes the file permission to full access for the provided tarinfo object.

    This helper function will be called by the __copy_files() function during the tar archive creation."""
    tarinfo.mode = int('0777', base=8)
    return tarinfo


class CopyDirection(enum.Enum):
    """Definition of the copy direction between SUNRISE Runtime Manager and container workspace."""
    SUNRISE_TO_CONTAINER = 1
    CONTAINER_TO_SUNRISE = 2


class ComputeDocker(compute_if.ComputeInterface):
    """Docker daemon implementation of compute interface."""

    def __init__(self) -> None:
        """Creates an instance of the Docker-based compute backend."""
        self._log = logging.getLogger('sunrise.container')
        self._client: docker.DockerClient = docker.from_env()
        self._system: compute_if.ComputeSystem = None
        self._output: str = None
        self._volume = None
        self._volume_name: str = None

    def create_resource(self, system: compute_if.ComputeSystem, progress: compute_if.ComputeProgress = None):
        # get sunrise container logger
        self._system = system
        self._volume_name = 'sunrise_session_volume_' + self._system.session_id
        # create a Docker volume to store all session-specific data into it
        self._volume = self._client.volumes.create(name=self._volume_name, driver='local')
        self.__copy_files(self._system.files, CopyDirection.SUNRISE_TO_CONTAINER)

    def build_system(self, files: list[compute_if.ComputeFile] = None, timeout: int = None,
                     progress: compute_if.ComputeProgress = None) -> str:
        """Starts a container with the build command."""
        self.__copy_files(files, CopyDirection.SUNRISE_TO_CONTAINER)
        return self.__execute_container(self._system.build_command, timeout, progress)

    def run_system(self, files: list[compute_if.ComputeFile] = None, timeout: int = None,
                   progress: compute_if.ComputeProgress = None) -> str:
        """Starts a container with the run command."""
        self.__copy_files(files, CopyDirection.SUNRISE_TO_CONTAINER)
        return self.__execute_container(self._system.run_command, timeout, progress)

    def stop_command(self):
        """Stops a running container."""
        container_name = f"sunrise_session_container_{self._system.session_id}"
        try:
            container = self._client.containers.get(container_name)
        except (docker.errors.ContainerError, docker.errors.APIError) as exc:
            message = f"Unable to find container '{container_name}' to stop it: {str(exc)}"
            self._log.error(message)
            raise compute_if.ComputeResourceUnavailableError(message) from exc
        try:
            container.stop()
        except (docker.errors.ContainerError, docker.errors.APIError) as exc:
            message = f"Unable to stop container '{container_name}': {str(exc)}"
            self._log.error(message)
            raise compute_if.ComputeResourceError(message) from exc

    def get_result(self, path: os.PathLike, progress: compute_if.ComputeProgress = None) -> os.PathLike:
        """Extracts the result by its name from the session container workspace."""
        self._log.info("Copy result '%s' from session container volume to SUNRISE Runtime Manager workspace...", path)
        # creating source and destination file paths for copy operation
        source_file = os.path.join(self._system.work_dir, path)
        file_name = os.path.basename(source_file)
        results_dir = os.path.join(self._system.local_dir, 'results')
        if not os.path.exists(results_dir):
            self._log.debug("Creating results directory '%s'...", results_dir)
            work_dir_obj = pathlib.Path(results_dir)
            work_dir_obj.mkdir(parents=True)
        destination_file = os.path.join(results_dir, file_name)
        files: list[compute_if.ComputeFile] = [compute_if.ComputeFile(source_path=source_file,
                                                                      destination_path=destination_file)]
        self.__copy_files(files, direction=CopyDirection.CONTAINER_TO_SUNRISE)
        self._log.debug("Successfully copied result '%s' to SUNRISE Runtime Manager workspace.", path)
        return destination_file

    def remove_resource(self):
        """Deletes the container in case it is still running and its volume containing the session data."""
        try:
            # check if volume is used by containers -> kill and remove containers first
            client = self._client
            containers = client.containers.list(filters={'volume': self._volume.name})
            for container in containers:
                container.kill()
                container.remove()
            # allow a cleanup of the container itself if delete command is defined (max. of 10 seconds allowed)
            if self._system.delete_command is not None and len(self._system.delete_command) > 0:
                self.__execute_container(self._system.delete_command, timeout=10.0)
            self._volume.remove()
            self._log.debug("Successfully removed Docker volume of session.")
        except (docker.errors.APIError, docker.errors.NotFound, docker.errors.ContainerError) as exc:
            message = f"Docker volume cannot be removed: {str(exc)}"
            self._log.error(message)
            raise compute_if.ComputeResourceUnavailableError(message) from exc

    def __getstate__(self):
        """Defines which data of this class can be serialized by pickle."""
        # copy the object state which contains all instance attributes
        state = self.__dict__.copy()
        # remove the unpicklable entries
        del state['_log']
        del state['_client']
        del state['_volume']
        return state

    def __setstate__(self, state):
        """Defines which data of this class can be deserialized by pickle."""
        # restore instance attributes
        self.__dict__.update(state)
        # restore unpicklable entries
        self._log = logging.getLogger('sunrise.container')
        self._client = docker.from_env()
        try:
            self._volume = self._client.volumes.get(self._volume_name)
        except docker.errors.NotFound as exc:
            message = f"Docker volume cannot be found: {str(exc)}"
            self._log.error(message)
            raise compute_if.ComputeResourceUnavailableError(message) from exc

    def __pull_image(self):
        """Pulls docker image from registry."""
        if "/" in self._system.image:
            self._log.debug('Pulling docker image')
            self._client.images.pull(self._system.image)
        else:
            # using local available Docker image as image name does not contain a full URL
            self._log.debug('Using local docker image without container registry')

    def __set_environment(self) -> dict:
        """Copies proxy settings of host to container if available."""
        environment = {}
        proxy_env_names = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'no_proxy', 'NO_PROXY']
        for proxy_env_name in proxy_env_names:
            try:
                env_value = os.environ[proxy_env_name]
                environment[proxy_env_name] = env_value
                self._log.debug("Setting environment variable %s=%s inside Docker container.", proxy_env_name,
                                env_value)
            except KeyError:
                pass
        return environment

    def __copy_files(self, files: list[compute_if.ComputeFile], direction: CopyDirection):
        """Copy operation between SUNRISE Runtime Manager workspace and container workspace.
        Uses a native docker copy operation with a tar filestream.
        """
        self._log.debug("Container copy operation starting...")
        volumes = {self._volume.name: {'bind': str(self._system.mount_dir), 'mode': 'rw'}}

        try:
            self.__pull_image()
            container = self._client.containers.run(image=self._system.image, volumes=volumes, detach=True)
            container.wait()

            if direction is CopyDirection.SUNRISE_TO_CONTAINER:
                # directory or file to be copied
                tar_filepath_local = os.path.join(self._system.local_dir, 'tmp_file_transfer.tar')
                # internal directory structure of tar file
                # running sessions expect input/repo to be placed accordingly
                # generate tar file
                with tarfile.open(tar_filepath_local, "w") as tar_file:
                    # tracks all added directories to avoid multiple adding of same directory
                    added_directories = set()
                    for file in files:
                        # check if current file is a file
                        if os.path.isfile(file.source_path):
                            # add parent directory to the archive to avoid that
                            # this parent folder will get a root owner inside the container
                            if os.path.dirname(file.destination_path) not in added_directories:
                                tar_file.add(os.path.dirname(file.source_path),
                                             arcname=os.path.dirname(file.destination_path),
                                             recursive=False,
                                             filter=change_file_permission)
                                added_directories.add(os.path.dirname(file.destination_path))
                        tar_file.add(file.source_path,
                                     arcname=file.destination_path,
                                     recursive=False,
                                     filter=change_file_permission)
                # open tar file and push it to running container
                with open(tar_filepath_local, "rb") as tar_file:
                    container.put_archive("/", tar_file)
                os.remove(tar_filepath_local)

            elif direction is CopyDirection.CONTAINER_TO_SUNRISE:
                # container source and sunrise destination file and folder handling
                destination_file = os.path.join(self._system.local_dir, 'results', 'tmp_file_transfer.tar')
                # read the container source to a byte stream
                bits, stat = container.get_archive(files[0].source_path)
                self._log.debug("Container copy operation 'stat' information: %s", stat)
                # move byte stream to a tar file
                with open(destination_file, 'wb+') as tar_file:
                    for chunk in bits:
                        tar_file.write(chunk)
                # extract tarfile to destination folder
                with tarfile.open(destination_file, 'r:') as tar_file:
                    tar_file.extractall(os.path.dirname(destination_file))
                os.remove(destination_file)
            container.remove()

        except (docker.errors.ContainerError, docker.errors.ImageNotFound, docker.errors.APIError) as exc:
            message = f"Exception occurred during Docker copy operation: {str(exc.explanation)}"
            self._log.error(message)
            raise RuntimeError(message) from exc

        self._log.debug("Container copy operation was successful.")

    def __execute_container(self, command, timeout, progress=None):
        """Executes the docker container and invokes the command within."""
        self._output = ""
        try:
            self._log.info('Invoke of system %s...', command)
            # pull the image from the registry
            self.__pull_image()
            self._log.debug("Container execution starting...")
            # define timeout in ulimits list if configured
            ulimits = []
            if timeout is not None and timeout > 0:
                ulimits.append(docker.types.Ulimit(name='cpu', soft=int(timeout), hard=int(timeout)))
            container = self._client.containers.run(
                image=self._system.image,
                name=f"sunrise_session_container_{self._system.session_id}",
                command=command,
                volumes={self._volume.name: {'bind': str(self._system.mount_dir), 'mode': 'rw'}},
                environment=self.__set_environment(),
                detach=True,
                ulimits=ulimits,
                working_dir=str(self._system.work_dir))

            if progress:
                logs = container.logs(stream=True)
                for log in logs:
                    progress(0, log.decode("utf-8"))
            # wait until container execution is completed
            container_status = container.wait()

            self._output = container.logs().decode("utf-8")

            container.remove()

        except (OSError, ValueError, NameError, FileNotFoundError, RuntimeError,
                docker.errors.ContainerError, docker.errors.ImageNotFound, docker.errors.APIError) as exc:
            # mark session as failed in case any exception occurred during build
            self._log.error(str(exc))
            self._output = str(exc)
            raise compute_if.ComputeError(str(exc)) from exc

        if container_status['StatusCode'] == 0:
            self._log.info("Container execution successfully finished...")
            self._log.debug("Log output of container:\n %s", self._output)
        else:
            message = f"Container execution failed with status code '{container_status['StatusCode']}'. "\
                      f"Log output of container:\n{self._output}"
            self._log.error(message)
            raise compute_if.ComputeError(message)

        return self._output
