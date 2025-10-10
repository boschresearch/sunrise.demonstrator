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
import abc
import typing
import dataclasses


#######################
# EXCEPTION DEFINITIONS
#######################

class ComputeResourceError(Exception):
    """Will be raised if a generic error of the compute resource occurs."""


class ComputeResourceUnavailableError(Exception):
    """Will be raised if the compute resource is not available or unreachable."""


class ComputeResourceCredentialsError(Exception):
    """Will be raised if the credentials are invalid to access the compute resource."""


class ComputeError(Exception):
    """Will be raised if a system build/run command fails."""


class ComputeTimeoutError(Exception):
    """Will be raised if a system build/run command times out."""


class ComputeFileError(Exception):
    """Will be raised if file cannot be copied from or to compute backend."""


########################
# DATA MODEL DEFINITIONS
########################

@dataclasses.dataclass
class ComputeFile:
    """Information about a single file which should be transferred to the compute backend."""
    # accessible file path from this Python script (locally available)
    source_path: os.PathLike
    # destination file path in perspective of the compute resource (e.g., a path inside a containers' file system)
    destination_path: os.PathLike


@dataclasses.dataclass
# pylint: disable-next=too-many-instance-attributes
class ComputeSystem:
    """Information about the system for the compute backend."""
    # used to identify the compute backend resource with the associated sunrise session
    session_id: str
    # image URL to container registry
    image: str
    # local available directory for temporary file storage (e.g. for result files)
    local_dir: os.PathLike
    # absolute path to mount directory inside compute resource on compute backend
    # this entry can be used by the compute backend to mount a persistent storage
    # all 'ComputeFile' files use the mount_dir as base path
    mount_dir: os.PathLike
    # absolute path to working directory inside compute resource on compute backend
    # this is always a sub-directory of the 'mount_dir' entry
    work_dir: os.PathLike
    # command to be executed for build operation
    build_command: str
    # command to be executed for run operation
    run_command: str
    # command to be executed if system gets deleted
    delete_command: str
    # list of all files which should be copied to backend
    files: list[ComputeFile]
    # requirements for compute resources (e.g. specific amount of CPUs or RAM)
    requirements: dict


# type definition for progress callbacks
# parameters:
#   progress (int): progress in percent (0 .. 100)
#   message (str): progress message
ComputeProgress = typing.Callable[[int, str], None]


#######################
# INTERFACE DEFINITIONS
#######################

class ComputeInterface(metaclass=abc.ABCMeta):
    """Interface for backend interface computations.

    IMPORTANT: Implementations of this interface must be de-/serializable using 'Pickle' package. Define
               '__getstate__()' and '__setstate__()' methods in case serialization cannot be done automatically.
    """

    @abc.abstractmethod
    def create_resource(self, system: ComputeSystem, progress: ComputeProgress = None):
        """Create a new resource on compute backend.

        Creates a new resource on the compute backend based on the entries of the provided ComputeSystem
        model.

        Parameters:
            system (ComputeSystem): Contains all relevant information to create the backend resource.
            progress (ComputeProgress): Optional callback function which gets called in case resource
                                        creation progresses.

        Raises:
            ComputeResourceUnavailableError: Will be raised if compute resource is not available or unreachable.
            ComputeResourceCredentialsError: Will be raised if credentials are invalid to access compute resource.
            ComputeResourceError: Will be raised if a generic error of the compute resource occurs.
            ComputeFileError: Will be raised if a file cannot be copied to compute backend.
        """
        return None

    @abc.abstractmethod
    def build_system(self, files: list[ComputeFile] = None, timeout: int = None,
                     progress: ComputeProgress = None) -> str:
        """Build the system on the compute backend. This function is blocking until operation finishes.

        Parameters:
            files (list): Optional list of files which should be transferred to backend.
                          The files provided with the 'create_resource' method might be extended or overwritten.
            timeout (int): Optional timeout in seconds. ComputeTimeoutError will be raised
                           in case timeout occurs.
            progress (ComputeProgress): Optional callback function which gets called in case build progresses.

        Returns:
            log info (str): Log output of compute backend during build command.

        Raises:
            ComputeTimeoutError: Will be raised in case timeout occurs.
            ComputeError: Will be raised if the build command fails.
            ComputeFileError: Will be raised if a file cannot be copied to compute backend.
        """
        return None

    @abc.abstractmethod
    def run_system(self, files: list[ComputeFile] = None, timeout: int = None,
                   progress: ComputeProgress = None) -> str:
        """Run the system on the compute backend. This function is blocking until operation finishes.

        Parameters:
            files (list): Optional list of files which should be transferred to backend.
                          The files provided with the 'create_resource' method might be extended or overwritten.
            timeout (int): Optional timeout in seconds. ComputeTimeoutError will be raised
                           in case timeout occurs.
            progress (ComputeProgress): Optional callback function which gets called in case run progresses.

        Returns:
            log info (str): Log output of compute backend during run command.

        Raises:
            ComputeTimeoutError: Will be raised in case timeout occurs.
            ComputeError: Will be raised if the run command fails.
            ComputeFileError: Will be raised if a file cannot be copied to compute backend.
        """
        return None

    @abc.abstractmethod
    def stop_command(self):
        """Stops a run or build command."""
        return None

    @abc.abstractmethod
    def get_result(self, path: os.PathLike, progress: ComputeProgress = None) -> os.PathLike:
        """Returns a result of a ran system from the compute backend.

        Parameters:
            path (PathLike): Path in perspective of the container file system to the result file.
            progress (ComputeProgress): Optional callback function which gets called in case result
                                        extraction progresses.

        Returns:
            result file path (PathLike): Local available path to the result file (this file must be
                                         stored in sub-path of 'local_dir' provided in 'ComputeSystem'
                                         data structure).
        """
        return None

    @abc.abstractmethod
    def remove_resource(self):
        """Removes the resource from the compute backend."""
        return None
