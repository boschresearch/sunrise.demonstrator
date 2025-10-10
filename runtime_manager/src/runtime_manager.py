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
This module is part of the SUNRISE demonstrator and provides an example for a Runtime Manager.

It is implemented as FastAPI application that provides REST endpoints.
"""

import os
import uuid
import logging
import pydantic
import fastapi
import uvicorn
import uvicorn.config
import system
import session
import constants
from dataformats import dataformats
import system_db
import compute_if


# get sunrise interface logger
log = logging.getLogger('sunrise.rest-api')

# extent logging of uvicorn (add time stamp)
uvicorn.config.LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s %(levelprefix)s %(message)s"
uvicorn.config.LOGGING_CONFIG["formatters"]["access"]["fmt"] = '%(asctime)s %(levelprefix)s %(client_addr)s'\
                                                               ' - "%(request_line)s" %(status_code)s'

# FastAPI application object for hosting REST API of SUNRISE Runtime Manager
api_app = fastapi.FastAPI(
    title='SUNRISE Evaluation API (EvalAPI)',
    summary='Implementation of the EvalAPI to the SUNRISE Runtime Manager',
    description='In the SUNRISE framework, the EvalAPI is the interface for front-end users to the Runtime Manager.',
    contact={'name': 'SUNRISE Team', 'url': 'https://www.bosch.com/research/', 'email': 'sunrise@bosch.com'},
    version=constants.SUNRISE_RUNTIME_MANAGER_VERSION
)


@api_app.get("/version", summary="Get the version of the Runtime Manager",
             response_class=fastapi.responses.PlainTextResponse, response_description="Version string")
def get_version() -> str:
    """REST API endpoint to get the Runtime Manager version.

    Returns:
        version (str): The version of this Runtime Manager.
    """
    log.info("The version of SUNRISE Runtime Manager is '%s'", constants.SUNRISE_RUNTIME_MANAGER_VERSION)
    return constants.SUNRISE_RUNTIME_MANAGER_VERSION


@api_app.get("/session", summary="Get the IDs of all existing experiments",
             response_description="List of experiment id strings")
def get_sessions() -> list[uuid.UUID]:
    """REST API endpoint for listing all available sessions.

    Returns:
        session_ids (list[UUID]): List of all session IDs of available experiments.
    """
    return session.SessionsHandler.available_sessions()


@api_app.post("/session", status_code=fastapi.status.HTTP_201_CREATED, summary="Create a new experiment",
              response_description="Experiment Id as string")
def create_session(item: dataformats.CreateSessionItem = fastapi.Body(description="A CreateSessionItem object")
                   ) -> uuid.UUID:
    """REST API endpoint for creating a new experiment.

    Parameters:
        item (CreateSessionItem): Object with system selection and experiment metadata.

    Returns:
        session_id (UUID): Session ID of the created experiment.
    """
    try:
        return session.SessionsHandler.create_session(item)
    except (ValueError, FileNotFoundError, session.InvalidSessionError, pydantic.ValidationError, RuntimeError,
            system_db.SystemNotFound) as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=str(exc))


@api_app.get("/session/{session_id}", summary="Get experiment details",
             response_description="SessionInfo object for the experiment")
def get_session(session_id: uuid.UUID) -> dataformats.SessionInfo:
    """REST API endpoint to get information about a specific session.

    Parameters:
        session_id (UUID): Session ID of the experiment.

    Returns:
        session_info (dataformats.SessionInfo): An object containing information about the experiment session.
    """
    try:
        with session.SessionsHandler(session_id) as session_data:
            return session_data.get_info()
    except session.InvalidSessionError as exc:
        message = f"Got an invalid session id '{str(session_id)}': {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)
    except compute_if.ComputeResourceUnavailableError as exc:
        message = f"Unable to get the resource of compute backed for the session id '{str(session_id)}': {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=message)


@api_app.delete("/session/{session_id}", summary="Remove an existing experiment",
                response_description="No response data")
def delete_session(session_id: uuid.UUID, force: bool = False) -> None:
    """REST API endpoint for removing an experiment. It will delete all artifacts of the session.

    Warning (!): Session content cannot be restored!

    Parameters:
        session_id (UUID): Session ID of the experiment.
        force (bool): Deleted even if the session is still opened by another connection.
                        Warning (!): Might lead to data corruption!
    """
    try:
        session.SessionsHandler.remove_session(session_id, force)
    except (KeyError, SystemError, OSError, session.InvalidSessionError, session.LockedSessionError) as exc:
        message = f"Unable to remove session id '{str(session_id)}': {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)


@api_app.get("/session/{session_id}/parameter/{group}", summary="Get all parameter values in the experiment by group",
             response_description="Dictionary with parameters and values")
def get_session_parameters(session_id: uuid.UUID,
                           group: system.ParameterGroupIdentifier) -> dict[str, str | bool | int | float]:
    """REST API endpoint for listing all parameters and their values of a parameter group configured in an experiment.

    Parameters:
        session_id (UUID): Session ID of the experiment.
        group (ParameterGroupIdentifier): Parameter group ('common', 'build' or 'run').

    Returns:
        parameters (dict): Dictionary of parameters and values for the parameter group used in this session.
    """
    try:
        with session.SessionsHandler(session_id) as session_data:
            if group is system.ParameterGroupIdentifier.COMMON:
                return session_data.common_parameters()
            if group is system.ParameterGroupIdentifier.BUILD:
                return session_data.build_parameters()
            if group is system.ParameterGroupIdentifier.RUN:
                return session_data.run_parameters()
            # invalid parameter group if this point is reached
            raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND,
                                        detail=f"Invalid parameter group '{str(group)}'.")
    except Exception as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=str(exc))


@api_app.put("/session/{session_id}/parameter/{group}", summary="Set the value of a parameter",
             response_description="No response data")
def put_session_parameter(session_id: uuid.UUID, group: system.ParameterGroupIdentifier,
                          parameter: dataformats.UpdateParameterItem = fastapi.Body(
                                                                    description="New parameter value")) -> None:
    """REST API endpoint for updating a parameter in an existing experiment.

    Warning (!): This might invalidate the results of previous build and/or run for this experiment!

    Parameters:
        session_id (UUID): Session ID of the experiment.
        group (ParameterGroupIdentifier): Parameter group ('common', 'build' or 'run').
        parameter (UpdateParameterItem): Object with parameter name and value.
    """

    try:
        with session.SessionsHandler(session_id) as session_data:
            # converting group identifier to real group name for internal processing
            param_group = dataformats.ParameterGroup(group + "_parameters")
            session_data.update(param_group, parameter.name, parameter.value)
    except (NameError, ValueError) as exc:
        message = f"Update of parameter '{parameter.name}' in '{session_id}' failed: {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)
    except session.LockedSessionError as exc:
        message = f"Update of parameter '{parameter.name}' in '{session_id}' failed: {str(exc)}\n" \
                  f"Update of parameter not allowed in current session state '{get_session_state(session_id)}'."
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=message)


@api_app.post("/session/{session_id}/parameter/{group}", summary="Set the value of a file parameter",
              response_description="No response data")
def post_session_parameter(session_id: uuid.UUID, group: system.ParameterGroupIdentifier, parameter_name: str,
                           file: fastapi.UploadFile = fastapi.File(description="File for parameter")) -> None:
    """REST API endpoint for adding files to the session.

    Warning (!): This might invalidate the results of previous build and/or run for this experiment!

    Parameters:
        session_id (UUID): Session ID of the experiment.
        group (ParameterGroupIdentifier): Parameter group ('common', 'build' or 'run').
        param_name (str): Name of the file parameter.
        file (UploadFile): Content to set the file parameter.
    """

    try:
        with session.SessionsHandler(session_id) as session_data:
            # converting group identifier to real group name for internal processing
            param_group = dataformats.ParameterGroup(group + "_parameters")
            session_data.add(param_group, parameter_name, file.filename, file.file.read())
    except (NameError, ValueError) as exc:
        message = f"File upload of parameter '{parameter_name}' in '{session_id}' failed: {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)
    except session.LockedSessionError as exc:
        message = f"Update of parameter '{parameter_name}' in '{session_id}' failed: {str(exc)}\n" \
                  f"Update of parameter not allowed in current session state '{get_session_state(session_id)}'."
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=message)


@api_app.delete("/session/{session_id}/parameter/{group}", summary="Reset a parameter to its default value",
                response_description="No response data")
def delete_session_parameter(session_id: uuid.UUID, group: system.ParameterGroupIdentifier,
                             parameter_name: str) -> None:
    """REST API endpoint to set a parameter to its default value.

    In case of a file parameter, this will delete an already uploaded file and replace it by the default
    file path. In any other case, the parameter value will be replaced by its default value.

    Warning (!): This might invalidate the results of previous build and/or run for this experiment!

    Parameters:
        session_id (UUID): Session ID of the experiment.
        group (ParameterGroupIdentifier): Parameter group ('common', 'build' or 'run').
        param_name (str): Name of the parameter.
    """

    try:
        with session.SessionsHandler(session_id) as session_data:
            # converting group identifier to real group name for internal processing
            param_group = dataformats.ParameterGroup(group + "_parameters")
            session_data.delete(param_group, parameter_name)
    except (NameError, ValueError) as exc:
        message = f"Deletion of parameter '{parameter_name}' in '{session_id}' failed: {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)
    except session.LockedSessionError as exc:
        message = f"Deletion of parameter '{parameter_name}' in '{session_id}' failed: {str(exc)}\n" \
                  f"Deletion of parameter not allowed in current session state '{get_session_state(session_id)}'."
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=message)


@api_app.post("/session/{session_id}/build", summary="Start the build-action of an experiment",
              response_description="No response data")
def post_session_build(session_id: uuid.UUID, timeout: int = None) -> None:
    """REST API endpoint for executing the system build.

    Parameters:
        session_id (UUID): Session ID of the experiment.
        timeout (int): Optional timeout in seconds for this command.
    """

    with session.SessionsHandler(session_id) as session_data:
        status = session_data.status()
    if status in [dataformats.State.RUNNING, dataformats.State.BUILDING]:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_412_PRECONDITION_FAILED,
                                    detail=f"Build not allowed since the session is in state {status}")
    try:
        session.Session.execute(session_id, 'build', True, timeout)
    except session.UnexpectedSessionState as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail=str(exc)) from exc


@api_app.post("/session/{session_id}/run", summary="Start the run-action of an experiment",
              response_description="No response data")
def post_session_run(session_id: uuid.UUID, timeout: int = None) -> None:
    """REST API endpoint for executing the system run.

    Parameters:
        session_id (UUID): Session ID of the experiment.
        timeout (int): Optional timeout in seconds for this command.
    """

    with session.SessionsHandler(session_id) as session_data:
        status = session_data.status()
        has_build_command = session_data.system.has_build
    if status in [dataformats.State.RUNNING, dataformats.State.BUILDING]:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_412_PRECONDITION_FAILED,
                                    detail=f"Run not allowed since the session is in state {status}")
    # if the system has a build command, the build step must be successfully completed for the run command
    if has_build_command and status not in [dataformats.State.BUILT, dataformats.State.RAN,
                                            dataformats.State.FAILED_RUN]:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_412_PRECONDITION_FAILED,
                                    detail=f"Run not allowed since the session is in state {status}")
    try:
        session.Session.execute(session_id, 'run', True, timeout)
    except session.UnexpectedSessionState as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail=str(exc)) from exc


@api_app.post("/session/{session_id}/stop", summary="Stop the ongoing build-/run-action",
              response_description="No response data")
def post_session_stop(session_id: uuid.UUID) -> None:
    """REST API endpoint for stopping immediately a building or running system.

    Parameters:
        session_id (UUID): Session ID of the experiment.
    """

    try:
        with session.SessionsHandler(session_id) as session_data:
            status = session_data.status()
            if status in [dataformats.State.RUNNING, dataformats.State.BUILDING]:
                session_data.stop()
            else:
                # stop command is only allowed in a building or running state
                raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST,
                                            detail="Stop call invalid since the session is not in state "
                                                   f"{dataformats.State.BUILDING} or {dataformats.State.RUNNING}")
    except (session.InvalidSessionError, compute_if.ComputeResourceUnavailableError) as exc:
        message = f"Failed to stop '{session_id}': {str(exc)}"
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)


@api_app.get("/session/{session_id}/status", summary="Get the state of the experiment",
             response_description="The experiment state")
def get_session_state(session_id: uuid.UUID) -> dataformats.State:
    """REST API endpoint for returning current session state in the SUNRISE workflow model.

    Parameters:
        session_id (UUID): Session ID of the experiment.

    Returns:
        state (dataformats.State): Current state of requested session.
    """

    try:
        with session.SessionsHandler(session_id) as session_data:
            return session_data.status()
    except Exception as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail=str(exc)) from exc


@api_app.get("/session/{session_id}/result", summary="Get a list with information about experiment results",
             response_description="List of ResultInfo objects")
def get_session_results(session_id: uuid.UUID) -> list[dataformats.ResultInfo]:
    """REST API endpoint for getting a list containing the availability status for each result in the experiment.

    Parameters:
        session_id (UUID): Session ID of the experiment.

    Returns:
        results info (list[ResultInfo]): List containing the availability of each result. In case a result is not
                                         available, then the message field contains a detailed description why.
    """

    try:
        with session.SessionsHandler(session_id) as session_data:
            result_info_list: list[dataformats.ResultInfo] = []
            for result_name, result_info in session_data.system.data.results.items():
                is_available, optional_message = session_data.get_result_availability(result_name)
                result_info = dataformats.ResultInfo(name=result_name, type=result_info.type,
                                                     is_available=is_available, message=optional_message)
                result_info_list.append(result_info)
            return result_info_list
    except Exception as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@api_app.get("/session/{session_id}/result/{name}", summary="Get a result object",
             response_description="The result file")
def get_session_result(session_id: uuid.UUID, name: str) -> fastapi.responses.FileResponse:
    """REST API endpoint for getting a result object from the experiment after a successful run.

    Parameters:
        session_id (UUID): Session ID of the experiment.
        name (str): Name of result object.

    Returns:
        file (FileResponse): File object containing the requested result. The response header contains the file name and
                             the data type.
    """

    if name is None or len(name) == 0:
        message = "Requested invalid result name with empty or not existing content."
        log.error(message)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)
    try:
        with session.SessionsHandler(session_id) as session_data:
            result = session_data.system.data.results[name]
            filename: os.PathLike = os.path.basename(result.path)
            datatype = result.type
            return fastapi.responses.FileResponse(session_data.get_result(name), filename=filename, media_type=datatype)
    except (NameError, KeyError, FileNotFoundError, session.InvalidSessionError, session.ResultNotAvailable) as exc:
        message = f"Requested invalid result '{name}' from session id '{session_id}': {str(exc)}"
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail=message)
    except RuntimeError as exc:
        message = f"Copy operation for result '{name}' from compute backend was not successful: {str(exc)}"
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=message)


@api_app.get("/system", summary="List all available system names", response_description="List of name strings")
def get_systems() -> list[str]:
    """REST API endpoint to get the list of available system names.

    Returns:
        systems_list (list[str]): List containing the names of all available systems.
    """
    return system_db.systems.get_system_names()


@api_app.get("/system/{name}", summary="List all available versions of a system",
             response_description="List of version strings")
def get_system_version(name: str) -> list[str]:
    """REST API endpoint to get a list of available versions of a specific system.

    Parameters:
        name (str): Name of the requested system.

    Returns:
        versions_list (list[str]): List containing the versions of the requested system.
    """
    try:
        return system_db.systems.get_system_versions(name)
    except (system_db.SystemNotFound, FileNotFoundError, pydantic.ValidationError) as exc:
        message = str(exc)
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=message)


@api_app.get("/system/{name}/{version}", summary="Get the SysDef of a system", response_description="SysDef object")
def get_system_definition(name: str, version: str) -> dataformats.SysDef:
    """REST API endpoint to get the definition of a system (SysDef).

    Parameters:
        name (str): Name of the system.
        version (str): Version of the system.

    Returns:
        system_definition (SysDef): The system definition object.
    """
    try:
        return system.System.get_system_definition(name, version)
    except (FileNotFoundError, UnboundLocalError, OSError, RuntimeError, system_db.SystemNotFound, KeyError) as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=str(exc))


@api_app.get("/system/{name}/{version}/description", summary="Get the system description",
             response_class=fastapi.responses.PlainTextResponse,
             response_description="String with Markdown syntax.")
def get_system_description(name: str, version: str) -> str:
    """REST API endpoint to get the description of a system.

    Parameters:
        name (str): Name of the system.
        version (str): Version of the system.

    Returns:
        description (str): Description of the system as string with Markdown syntax.
    """
    try:
        return system.System.get_system_description(name, version)
    except (FileNotFoundError, pydantic.ValidationError, UnboundLocalError, OSError, RuntimeError) as exc:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=str(exc))


# start of uvicorn server for hosting the REST API
if __name__ == "__main__":
    # setup loggers
    logging.config.fileConfig(os.path.join(constants.SUNRISE_RUNTIME_MANAGER_FULL_PATH, 'config', 'logging.conf'))
    uvicorn.run(api_app, host="0.0.0.0", port=int(os.getenv('SUNRISE_RUNTIME_MANAGER_PORT', '8000')))
