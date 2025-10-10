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
Handles the session management of SUNRISE Runtime Manager.

A session comprises all data, processes and information required to run
a simulation job.
"""

import uuid
import dataclasses
import datetime
import pickle
import os
import logging
import threading
import shutil
import constants
from dataformats import dataformats
import system
import compute_if


class UnexpectedSessionState(Exception):
    """Will be raised if the session state is not in the expected state after an operation."""


class InvalidSessionError(Exception):
    """Will be raised in case session data is invalid in the used context."""


class LockedSessionError(Exception):
    """Will be raised if the session is already locked by another function or thread."""


class ResultNotAvailable(Exception):
    """Will be raised in case a result is requested which is not (yet) available."""


@dataclasses.dataclass
class SessionDetails:
    """Contains additional information about a session."""
    display_name: str
    session_description: str
    creator_name: str
    creation_date: str
    remote: bool = None

    @classmethod
    def from_create_item(cls, create_data: dataformats.CreateSessionItem):
        """Take member values from a CreateSessionItem object."""
        inst = cls(display_name=create_data.display_name if create_data.display_name else "",
                   session_description=create_data.description if create_data.description else "",
                   creator_name=create_data.creator if create_data.creator else "",
                   creation_date=str(datetime.datetime.now()),
                   remote=create_data.remote)
        return inst


class Session:
    """Represents a session instance and provides all public operations on a session."""

    def __init__(self, session_id: uuid.UUID, syscfg: dataformats.SysCfg, details: SessionDetails) -> None:
        """Creates a new session instance."""
        # get sunrise session logger
        self._log = logging.getLogger('sunrise.session')
        # parse content of system configuration into a dataclass and clone repository
        self.system = system.System(str(session_id),
                                    syscfg,
                                    os.path.join(constants.SESSIONS_BASE_DIR, str(session_id), 'repository'),
                                    details.remote)
        self.details = details
        # set session state to 'built' if there is no build command in SysDef
        if self.system.has_build:
            self.state = dataformats.State.CREATED
        else:
            self.state = dataformats.State.BUILT
        self.session_id = session_id
        self.log_entries: list[dataformats.LogEntry] = []

    def __getstate__(self):
        """Defines which data of this class can be serialized by pickle."""
        # copy the object state which contains all instance attributes
        state = self.__dict__.copy()
        # remove the unpicklable entries
        del state['_log']
        return state

    def __setstate__(self, state):
        """Defines which data of this class can be deserialized by pickle."""
        # restore instance attributes
        self.__dict__.update(state)
        # restore unpicklable entries
        self._log = logging.getLogger('sunrise.session')

    def remove(self):
        """Removes the used resources of this session."""
        self.system.remove()

    def __update_state_after_param_change(self, changed_param_group):
        """Updates the session state if required after a parameter value has been changed."""
        previous_state = self.state
        if changed_param_group in (dataformats.ParameterGroup.COMMON, dataformats.ParameterGroup.BUILD):
            if self.state in (dataformats.State.BUILT, dataformats.State.FAILED_BUILD,
                              dataformats.State.RAN, dataformats.State.FAILED_RUN):
                if self.system.has_build:
                    self.state = dataformats.State.CREATED
                else:
                    self.state = dataformats.State.BUILT
        elif changed_param_group == dataformats.ParameterGroup.RUN:
            if self.state in (dataformats.State.RAN, dataformats.State.FAILED_RUN):
                self.state = dataformats.State.BUILT
        if previous_state != self.state:
            self._log.info("Parameter update changed session state from '%s' to '%s'", previous_state, self.state)

    def update(self, parameter_group, parameter_name, parameter_value):
        """Updates a specific parameter with a new value. The updated SysCfg file will be returned."""
        # it is not allowed to update a parameter during command execution
        if self.state in (dataformats.State.BUILDING, dataformats.State.RUNNING):
            raise LockedSessionError
        # check if parameter is part of parsed parameters from system definition and system configuration files
        parameter = self.system.get_parameter(parameter_group, parameter_name)
        if parameter is not None:
            parameter.update_parameter(parameter_value)
            # update session state depending on parameter group
            self.__update_state_after_param_change(parameter_group)
        else:
            message = f"Selected parameter '{parameter_name}' is not part of system definition."
            self._log.error(message)
            raise ValueError(message)

    def add(self, parameter_group, parameter_name, file_name, file):
        """Adds a file for a specific file parameter."""
        # it is not allowed to add a file parameter during command execution
        if self.state in (dataformats.State.BUILDING, dataformats.State.RUNNING):
            raise LockedSessionError
        # check if parameter is part of parsed parameters from system definition and system configuration files
        parameter = self.system.get_parameter(parameter_group, parameter_name)
        if parameter is not None:
            self._log.info("Processing 'add' command for file parameter '%s' of parameter group '%s'...",
                           parameter_name, parameter_group)
            parameter.process_input_file(self.session_id, parameter_group, file_name, file)
        else:
            message = f"Selected parameter '{parameter_name}' in parameter group '{parameter_group}'"\
                       " is not part of system definition."
            self._log.error(message)
            raise ValueError(message)
        # update session state depending on parameter group
        self.__update_state_after_param_change(parameter_group)

    def delete(self, parameter_group, parameter_name):
        """Deletes a parameter value and replaces it by the default value."""
        parameter = self.system.get_parameter(parameter_group, parameter_name)
        if parameter is not None:
            self._log.info("Processing 'delete' command for parameter '%s' of parameter group '%s'...",
                           parameter_name, parameter_group)
            parameter.reset()
        else:
            message = f"Selected parameter '{parameter_name}' in parameter group '{parameter_group}'"\
                       " is not part of system definition."
            self._log.error(message)
            raise ValueError(message)
        # update session state depending on parameter group
        self.__update_state_after_param_change(parameter_group)

    @staticmethod
    def __execute_precondition_check(session_id, command):
        """Precondition checks if command can be executed in the current session state."""
        with SessionsHandler(session_id) as session:
            # check if there is already a build or run command active
            if session.state in (dataformats.State.BUILDING, dataformats.State.RUNNING):
                raise UnexpectedSessionState(
                    f"Cannot execute '{command}' as session is already 'building' or 'running'!")
            # if the system has a build command, the build step must be successfully completed for
            # the run command. If there is no build command it doesn't matter what the current session state is.
            if command == 'run' and session.system.has_build and session.state not in (
               dataformats.State.BUILT, dataformats.State.RAN, dataformats.State.FAILED_RUN):
                raise UnexpectedSessionState("Cannot execute 'run' as session state is not 'built' or 'ran'!")

    @staticmethod
    def execute(session_id, command: str, async_call: bool = False, timeout: int = None):
        """Executes the system for the build or run command."""
        Session.__execute_precondition_check(session_id, command)

        state_mapping = {
            'build': (dataformats.State.BUILDING, dataformats.State.BUILT, dataformats.State.FAILED_BUILD,
                      f"{session_id}_build"),
            'run': (dataformats.State.RUNNING, dataformats.State.RAN, dataformats.State.FAILED_RUN,
                    f"{session_id}_run")
        }

        if command not in state_mapping:
            raise ValueError(f"Invalid command: {command}")

        initial_state, success_state, failure_state, name = state_mapping[command]

        # make first log entry in session to show start of command
        with SessionsHandler(session_id) as session:
            session.log_entries.append(dataformats.LogEntry(
                    timestamp=datetime.datetime.now(),
                    producer=f"container.{command}",
                    message="--- starting execution ---\n"))

        if async_call:
            with SessionsHandler(session_id) as session:
                session.state = initial_state
            target = Session.__execute_async
            thread = threading.Thread(target=target, args=(session_id, command, timeout), name=name)
            thread.start()
            return f"{command} command started asynchronously."

        # sync execution of command
        with SessionsHandler(session_id) as session:
            try:
                output = session.system.execute(command, timeout)
                session.state = success_state
                session.log_entries[-1].message += output
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                output = str(exc)
                session.state = failure_state
                session.log_entries[-1].message += output
            if not output:
                session.log_entries[-1].message += f"No output generated by {command} command."
            if session.state is not success_state:
                raise UnexpectedSessionState(output)

        return output

    @staticmethod
    def __execute_async(session_id, command: str, timeout: int = None):
        """This method is called as thread to execute the system asynchronously."""
        try:
            def write_to_log(_, message: str):
                """Implements progress callback for compute backend. Messages will be written to session log."""
                try:
                    with SessionsHandler(session_id) as session:
                        session.log_entries[-1].message += message
                except (LockedSessionError, InvalidSessionError) as exc:
                    message = f"Cannot write log entry for session id '{session_id}': {str(exc)}"
                    logging.error(message)

            # special invocation of execute method in read only mode to allow progress callback to update session log
            with SessionsHandler(session_id, read_only=True) as session:
                output = session.system.execute(command, timeout, write_to_log)
            with SessionsHandler(session_id) as session:
                # check if progress callback was used by backend, otherwise use returned output for session log
                if session.log_entries[-1].message == "--- starting execution ---\n":
                    if not output:
                        output = f"No output generated by {command} command."
                    session.log_entries[-1].message += output
                if command == 'build':
                    session.state = dataformats.State.BUILT
                else:
                    session.state = dataformats.State.RAN
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            with SessionsHandler(session_id) as session:
                session.log_entries[-1].message += str(exc)
                if command == 'build':
                    session.state = dataformats.State.FAILED_BUILD
                else:
                    session.state = dataformats.State.FAILED_RUN

    def stop(self):
        """Stops a running system."""
        self.system.stop()

    def status(self):
        """Returns the current session state."""
        return self.state

    def common_parameters(self):
        """Returns the list session parameters."""
        syscfg = self.system.get_current_system_config()
        return syscfg.common_parameters

    def build_parameters(self):
        """Returns the list session parameters."""
        syscfg = self.system.get_current_system_config()
        return syscfg.build_parameters

    def run_parameters(self):
        """Returns the list session parameters."""
        syscfg = self.system.get_current_system_config()
        return syscfg.run_parameters

    def get_result_availability(self, name: str) -> tuple[bool, str]:
        """Returns True if the result is available, otherwise False with a description will be returned."""
        result = self.system.data.results[name]
        if isinstance(result, dataformats.SysDefResult):
            enabled_by = result.enabled_by
        else:
            enabled_by = None
        # parse enabled_by list in case it is present
        if enabled_by is not None:
            for enable_entry in enabled_by:
                parameter_name = enable_entry.split('/')[-1]
                parameter_group = dataformats.ParameterGroup(enable_entry.split('/')[-2])
                parameter = self.system.get_parameter(parameter_group, parameter_name)
                if isinstance(parameter.value, bool):
                    if not parameter.value:
                        message = f"Result '{name}' is not available: Required parameter '{parameter.name}' is not "\
                                   "set to 'true'."
                        return False, message
                else:
                    message = f"Result '{name}' cannot be generated: Required parameter '{parameter.name}' is not "\
                               "a boolean type. The SysDef is invalid for this result."
                    return False, message
                if parameter_group == dataformats.ParameterGroup.BUILD:
                    if self.state not in (dataformats.State.BUILT, dataformats.State.RUNNING, dataformats.State.RAN,
                                          dataformats.State.FAILED_RUN):
                        message = f"Result '{name}' is not available: Session state is '{str(self.state)}' but "\
                                  f"at least '{str(dataformats.State.BUILT)}' is required."
                        return False, message
                if parameter_group == dataformats.ParameterGroup.RUN:
                    if self.state not in dataformats.State.RAN:
                        message = f"Result '{name}' is not available: Session state is '{str(self.state)}' but "\
                                  f"at least '{str(dataformats.State.RAN)}' is required."
                        return False, message
        else:
            # no enabled_by information is available -> expect to have the result available after successful run step
            if self.state is not dataformats.State.RAN:
                message = f"Result '{name}' is not available: Session state is '{str(self.state)}' but at least "\
                          f"'{str(dataformats.State.RAN)}' is required."
                return False, message
        # at this point all checks are done and the result should be available
        return True, None

    def get_result(self, name: str) -> str:
        """Returns a result as path from a run or build step."""
        result_found, message = self.get_result_availability(name)
        if not result_found:
            self._log.error(message)
            raise ResultNotAvailable(message)
        result = self.system.data.results[name]
        if isinstance(result, dataformats.SysDefResult):
            path: os.PathLike = result.path
        else:
            path: os.PathLike = result
        return self.system.get_result(path)

    def get_info(self):
        """Returns information about the provided session id."""
        session_info = dataformats.SessionInfo(
            display_name=self.details.display_name,
            creation_date=self.details.creation_date,
            creator_name=self.details.creator_name,
            session_description=self.details.session_description,
            session_state=self.state,
            system_name=self.system.system_id.name,
            system_version=self.system.system_id.version,
            session_logs=self.log_entries,
            syscfg=self.system.get_current_system_config()
        )
        return session_info


class SessionsHandler:
    """Sessions handling of the SUNRISE Runtime Manager."""

    # name of session data file
    SESSION_FILE_NAME = 'session_data'

    # name of the session data version file
    SESSION_VERSION_FILE_NAME = 'sunrise_runtime_manager_version'

    # contains all opened sessions (key = session id, value = threading lock)
    _opened_sessions: dict[str, threading.Lock] = {}

    def __init__(self, session_id, read_only=False, force=False) -> None:
        # get sunrise session logger
        self._log = logging.getLogger('sunrise.session')
        self.session_id = session_id
        self.read_only = read_only
        self.force = force
        self.session = None
        if not os.path.isdir(constants.SESSIONS_BASE_DIR):
            os.makedirs(constants.SESSIONS_BASE_DIR)

    def __enter__(self) -> Session:
        self.session = self.__open_storage_file(self.read_only, self.force)
        return self.session

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.__close_storage_file(self.read_only)

    @staticmethod
    def create_session(create_session_item: dataformats.CreateSessionItem) -> uuid.UUID:
        """Creates new session for a specific system configuration.

            Parameters:
                create_session_item: Contains all relevant data to create a session (e.g. SysCfg)
            Returns:
                Unique session id representing this session.
        """
        session_id = uuid.uuid4()
        session_details = SessionDetails.from_create_item(create_session_item)
        session_data = Session(session_id, create_session_item.syscfg, session_details)

        # create a new session file for non-volatile storage of session data
        session_file_path = os.path.join(constants.SESSIONS_BASE_DIR, str(session_id),
                                         SessionsHandler.SESSION_FILE_NAME)
        with open(session_file_path, 'wb') as file:
            pickle.dump(session_data, file)

        # add a file with the version of the SUNRISE Runtime Manager to enable compatibility checks of the pickled file
        version_marker_file = os.path.join(constants.SESSIONS_BASE_DIR, str(session_id),
                                           SessionsHandler.SESSION_VERSION_FILE_NAME)
        with open(version_marker_file, mode="w", encoding="utf-8") as file:
            file.write(constants.SUNRISE_RUNTIME_MANAGER_VERSION)

        return session_id

    def __open_storage_file(self, read_only: bool = False, force: bool = False):
        """Opens the storage file for the session id and locks the file to avoid manipulation by another thread."""
        # get session lock for exclusive session file access if write access is requested
        if self.session_id in SessionsHandler._opened_sessions:
            session_look = SessionsHandler._opened_sessions[self.session_id]
        else:
            session_look = threading.Lock()
            SessionsHandler._opened_sessions[self.session_id] = session_look
        if not read_only:
            # exclusive lock required for write operations on session
            if session_look.locked() and force:
                self._log.warning("Session file is locked and is forced to be opened again. " +
                                  "Data corruption might occur if trying to be saved!")
            # try to acquire lock with a max timeout of one second
            elif not session_look.acquire(timeout=1.0):
                message = "Session is already locked by another process. Cannot open session after waiting for 1s!"
                self._log.error(message)
                raise LockedSessionError(message)

        session_file_path = os.path.join(constants.SESSIONS_BASE_DIR, str(self.session_id),
                                         SessionsHandler.SESSION_FILE_NAME)

        if not os.path.isfile(session_file_path):
            message = f"No session file found for session id '{str(self.session_id)}'."
            self._log.error(message)
            raise InvalidSessionError(message)

        # check if pickled session data file was created with this SUNRISE Runtime Manager version
        version_marker_file = os.path.join(constants.SESSIONS_BASE_DIR, str(self.session_id),
                                           SessionsHandler.SESSION_VERSION_FILE_NAME)
        with open(version_marker_file, mode="r", encoding="utf-8") as file:
            version = str.strip(file.readline())
        if version != constants.SUNRISE_RUNTIME_MANAGER_VERSION:
            self._log.warning("The session file was created with a different SUNRISE Runtime Manager version: "
                              "Read version is '%s', expected version is '%s'! Trying to parse the session file "
                              "but errors might occur.", version, constants.SUNRISE_RUNTIME_MANAGER_VERSION)

        session_data: Session
        with open(os.path.join(session_file_path), 'rb') as file:
            try:
                session_data = pickle.load(file)
            except ModuleNotFoundError as exc:
                message = f"Cannot load session file for session id '{str(self.session_id)}'."\
                           "The session might be created with an older or newer version of SUNRISE Runtime Manager "\
                           f"and could be now incompatible with this version. Problematic module is: {str(exc)}"
                self._log.error(message)
                raise InvalidSessionError(message) from exc
            except compute_if.ComputeResourceUnavailableError as exc:
                message = f"Cannot open the session volume: {str(exc)}"
                self._log.error(message)
                raise InvalidSessionError(message) from exc

        session_data.session_handler = self
        return session_data

    def __close_storage_file(self, read_only: bool = False):
        """Closes the storage file for the session and releases the file lock to allow modification by other threads."""
        if not read_only:
            session_file_path = os.path.join(constants.SESSIONS_BASE_DIR, str(self.session_id),
                                             SessionsHandler.SESSION_FILE_NAME)
            if not os.path.isfile(session_file_path):
                message = f"No session file found for session id '{str(self.session_id)}'."
                self._log.error(message)
                raise InvalidSessionError(message)

            # save session data to session file
            with open(os.path.join(session_file_path), 'wb') as file:
                pickle.dump(self.session, file)

            # release lock on this session file
            SessionsHandler._opened_sessions[self.session_id].release()

    @staticmethod
    def remove_session(session_id, force: bool = False):
        """Removes the session and its artifacts."""
        remove_approved = False
        try:
            with SessionsHandler(session_id, read_only=force, force=force) as session:
                remove_approved = True
                session.remove()
        except compute_if.ComputeResourceUnavailableError as exc:
            raise InvalidSessionError(exc) from exc
        finally:
            if remove_approved:
                # remove lock object from session handle object
                del SessionsHandler._opened_sessions[session_id]
                # remove session from filesystem
                session_path = os.path.join(constants.SESSIONS_BASE_DIR, str(session_id))
                if os.path.isdir(session_path):
                    shutil.rmtree(session_path)

    @staticmethod
    def available_sessions() -> list[str]:
        """Returns a list with all available sessions."""
        session_ids = []
        # iterate over all folders in session base folder to get available session ids
        if os.path.isdir(constants.SESSIONS_BASE_DIR):
            session_ids = list(os.listdir(constants.SESSIONS_BASE_DIR))
        return session_ids
