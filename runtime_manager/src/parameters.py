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
Handles the parameters of the system configuration and system definition files.
"""

import os
import logging
import shutil
import enum
import dataclasses
import pathlib
import urllib.request
import constants
from dataformats import dataformats


class FileState(enum.Enum):
    """Definition of possible file parameter states in SUNRISE Runtime Manager."""
    DEFAULT = 1    # using default file of SysDef (already available to the system)
    PENDING = 2    # SysCfg defines a file but is not yet provided to SUNRISE Runtime Manager
    STAGED = 3     # SUNRISE Runtime Manager has acquired the file but is not yet available in the system container
    AVAILABLE = 4  # system container has access to the file


@dataclasses.dataclass
class FileData:
    """Holds file-specific information of a file parameter."""
    file_name: str
    file_state: FileState
    file_path_default: str
    file_path_origin: str
    file_path_local: str
    file_path_container: str
    credentials: bytes


class Parameter:
    """Handles a parameter of a system."""

    def __init__(self, name, value, sysdef_param_value, overwritten) -> None:
        # get sunrise session logger
        self._log = logging.getLogger('sunrise.system')
        self.name: str = name
        self.value = value
        self.overwritten: bool = overwritten
        self.meta_data: dict = None
        self.file_data: FileData = None
        self.default_value = sysdef_param_value
        if isinstance(sysdef_param_value, dataformats.SysDefCmplxParameter):
            # current parameter has a complex parameter type
            # the sub-entries are only part of the system definition file
            self.default_value = sysdef_param_value.default_value
            # set value in case parameter is not overwritten
            if not overwritten:
                self.value = sysdef_param_value.default_value
            # get meta data of current parameter
            if sysdef_param_value.meta:
                self.meta_data = sysdef_param_value.meta
                if isinstance(self.meta_data, dataformats.SysDefParameterFile):
                    # current parameter is a file parameter -> specific parsing required
                    self.__parse_file_parameter(self.meta_data.is_file, self.default_value)

    def __parse_file_parameter(self, param_subentry_value, sysdef_param_path_value):
        """Parses a file parameter from the system definition file and system configuration file."""
        if isinstance(param_subentry_value, bool):
            if param_subentry_value:
                # current parameter is a file -> create file data object
                self.file_data = FileData(
                    file_name=None,
                    file_state=None,
                    file_path_default=sysdef_param_path_value,
                    file_path_origin=None,
                    file_path_local=None,
                    file_path_container=None,
                    credentials=None
                )
                self.default_value = sysdef_param_path_value
                if self.overwritten:
                    # the file path is overwritten by configuration file
                    # -> this is considered as origin
                    if isinstance(self.value, dataformats.SysCfgUrlParameter):
                        # complex value -> check if path is an url with credentials
                        self.file_data.file_path_origin = self.value.url
                        if self.value.credentials is not None:
                            self.file_data.credentials = bytes(self.value.credentials, 'ascii')
                    else:
                        self.file_data.file_path_origin = self.value
                    self.file_data.file_state = FileState.PENDING
                else:
                    # the file path is not overwritten
                    # -> use default file path based on workspace
                    self.file_data.file_path_container = self.default_value
                    self.file_data.file_state = FileState.DEFAULT
            else:
                # parameter has is_file attribute but with false content -> this entry has no effect
                self._log.info("Detected 'is_file' entry with 'false' value for parameter '%s' -> "
                               "This entry has no effect and is ignored.", self.name)
        else:
            message = f"Detected 'is_file' entry for parameter '{self.name}' with "\
                        "no boolean datatype as value."
            self._log.error(message)
            raise ValueError(message)

    def process_input_file(self, session_id, group, file_name, file):
        """Processes an input file from Python or API.

        It tries to find the referenced parameter and uploads the file to the session workspace.
        """
        self._log.debug("Processing input file for parameter '%s'.", self.name)
        if self.file_data is None:
            message = f"Selected parameter '{self.name}' is not a file and cannot be uploaded with a file."
            self._log.error(message)
            raise NameError(message)
        if self.file_data.file_path_container is None and self.file_data.file_path_origin is None:
            message = f"Corrupted parameter '{self.name}': Marked as file parameter but has no valid path."
            self._log.error(message)
            raise ValueError(message)
        destination_path = os.path.join(constants.SESSIONS_BASE_DIR, str(session_id), 'inputs', group, self.name)
        destination_file = os.path.join(destination_path, file_name)
        destination_path_obj = pathlib.Path(destination_path)
        destination_path_obj.mkdir(parents=True, exist_ok=True)
        if os.path.isfile(str(file)):
            # native execution environment -> file can be uploaded with native os commands
            shutil.copyfile(str(file), destination_file)
        else:
            # API call -> write stream to file
            with open(destination_file, 'wb') as target_file:
                target_file.write(file)
        self.file_data.file_name = file_name
        # mark file as staged (file is available to SUNRISE Runtime Manager but not yet available in the
        # container workspace)
        self.file_data.file_state = FileState.STAGED
        # already create the path of the mounted file (perspective of the executing container)
        target_mounted_dir = os.path.join(constants.CONTAINER_WORKDIR, 'inputs', group, self.name,
                                          self.file_data.file_name)
        self.file_data.file_path_container = target_mounted_dir
        self.file_data.file_path_local = destination_file
        self._log.debug("Successfully saved file for parameter '%s' to temporary workspace path '%s'.", self.name,
                        destination_file)
        self._log.debug("Mounted workspace path inside Docker container will be '%s'.", target_mounted_dir)

    def reset(self):
        """Resets the parameter to its default value."""
        if self.file_data is not None:
            # parameter is file -> remove the existing file and set to default file path
            if self.file_data.file_path_local is not None and os.path.isfile(self.file_data.file_path_local):
                os.remove(self.file_data.file_path_local)
            self.file_data.file_path_container = self.file_data.file_path_default
            self.file_data.file_state = FileState.DEFAULT
            self.file_data.credentials = None
            self.file_data.file_name = None
            self.file_data.file_path_origin = None
            self.file_data.file_path_local = None
        else:
            # non-file parameter -> reset to default value
            self.value = self.default_value

    def stage_file(self, session_id, group):
        """Stages the file by copying the file in the temporary folder of the SUNRISE Runtime Manager."""
        if self.file_data is not None:
            if self.file_data.file_state == FileState.PENDING:
                # try to access parameter and check if file is accessible
                # then copy file to temporary storage of SUNRISE Runtime Manager
                if os.path.isfile(self.file_data.file_path_origin):
                    # native execution environment -> file can be uploaded with native os commands
                    self._log.info("Trying to stage pending file parameter '%s'.", self.name)
                    destination_path = os.path.join(constants.SESSIONS_BASE_DIR, str(session_id), 'inputs', group,
                                                    self.name)
                    destination_file = os.path.join(destination_path, self.file_data.file_name)
                    destination_path_obj = pathlib.Path(destination_path)
                    destination_path_obj.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.file_data.file_path_origin, destination_file)
                    # already create the path of the mounted file (perspective of the executing container)
                    target_mounted_dir = os.path.join(constants.CONTAINER_WORKDIR, 'inputs', group, self.name,
                                                      self.file_data.file_name)
                    self.file_data.file_path_container = target_mounted_dir
                    self.file_data.file_path_local = destination_file
                    self.file_data.file_state = FileState.STAGED

                elif self.file_data.file_path_origin.startswith(('http://', 'https://', 'ftp://')):
                    # file path is a web-based URL -> try to download file
                    self._log.info("Trying to stage pending file parameter '%s' from web-based URL '%s'",
                                   self.name, self.file_data.file_path_origin)
                    try:
                        request = urllib.request.Request(self.file_data.file_path_origin)
                        if self.file_data.credentials is not None:
                            request.add_header("Authorization", f"Bearer {self.file_data.credentials.decode('utf-8')}")
                        with urllib.request.urlopen(request) as file:
                            content = file.read()
                        self._log.info("Successfully downloaded file from URL '%s'.", self.file_data.file_path_origin)
                        destination_path = os.path.join(constants.SESSIONS_BASE_DIR, str(session_id), 'inputs',
                                                        group, self.name)
                        self.file_data.file_name = self.file_data.file_path_origin.split("/")[-1]
                        destination_file = os.path.join(destination_path, self.file_data.file_name)
                        destination_path_obj = pathlib.Path(destination_path)
                        destination_path_obj.mkdir(parents=True, exist_ok=True)
                        with open(destination_file, 'wb') as target_file:
                            target_file.write(content)
                    except urllib.error.HTTPError as exc:
                        message = f"Unable to download file from URL '{self.file_data.file_path_origin}' for the "\
                                  f"parameter '{self.name}': {str(exc)}"
                        self._log.error(message)
                        raise FileNotFoundError(message) from exc
                    target_mounted_dir = os.path.join(constants.CONTAINER_WORKDIR, 'inputs', group, self.name,
                                                      self.file_data.file_name)
                    self.file_data.file_path_container = target_mounted_dir
                    self.file_data.file_path_local = destination_file
                    self.file_data.file_state = FileState.STAGED

                else:
                    message = f"Cannot make file parameter '{self.name}' with origin file path "
                    message += f"'{self.file_data.file_path_origin}' available. "
                    message += "Use 'add' API call to upload the file."
                    self._log.error(message)
                    raise FileNotFoundError(message)

            elif self.file_data.file_state == FileState.STAGED:
                # file is ready to be copied to docker volume
                self._log.info("File parameter '%s' is staged to temporary SUNRISE Runtime Manager storage.", self.name)
        else:
            self._log.debug("Skipping non-file parameter '%s' for file staging process...", self.name)

    def mark_file_parameter_available(self):
        """Marks file parameter as available."""
        if self.file_data is not None:
            if self.file_data.file_state == FileState.STAGED:
                self.file_data.file_state = FileState.AVAILABLE

    def update_parameter(self, new_value):
        """Updates a parameter and replaces the existing value."""
        self._log.info("Updating parameter '%s' with value '%s'...", self.name, new_value)
        # special handling for boolean data types required
        if isinstance(self.value, bool):
            if isinstance(new_value, bool):
                self.value = new_value
            elif new_value.lower() == 'true':
                self.value = True
            else:
                self.value = False
        else:
            # consider all other data types as string
            self.value = new_value
        self._log.info("Successfully updated parameter value.")
