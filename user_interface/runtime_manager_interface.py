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
TODO EvalAPI Access Functions
"""

import dataclasses
import inspect
import json
import logging
import os
import time
import typing
import requests
import streamlit as st

import ui_utils as uiu
import dataformats as sdf


# INTERNAL HELPER FUNCTIONS ############################################################################################
class SunriseClientError(Exception):
    """Custom exception from the SUNRISE Runtime Manager access."""


def __send_request(request: requests.Request, timeout_s: int = 10) -> requests.Response:
    """INTERNAL function to send the request over the REST API and handle potential errors of the response."""
    try:
        prepared_request = request.prepare()
        with requests.Session() as session:
            response = session.send(prepared_request, timeout=timeout_s)
            response.raise_for_status()
            return response
    except requests.exceptions.HTTPError as exc:
        if response.text == "Internal Server Error":
            details = "Internal Runtime Manager Error"
        else:
            # try to parse the response text as json, otherwise return plain text
            try:
                details = json.loads(response.text)["detail"]
            except ValueError:
                details = response.text
        raise SunriseClientError(
            f"EvalAPI call '{inspect.stack()[1].function}' failed (code {response.status_code}): '{details}'") from exc
    except requests.RequestException as exc:
        raise SunriseClientError(f"EvalAPI call '{inspect.stack()[1].function}' failed: {exc}") from exc


@dataclasses.dataclass
class ResultObject:
    """Class to connect """
    name: str
    data: bytes
    filename: str
    type: sdf.resultformats.ResultTypes
    session_id: str


# RUNTIME MANAGER ACCESS ###############################################################################################
def get_version(rm_address: str) -> typing.Tuple[bool, str]:
    """Get the version of the connected Runtime Manager."""
    try:
        # response = sr_client.runtime_manager_version(rm_address)
        response = __send_request(requests.Request('GET', f"{rm_address}/version"), timeout_s=3)
        response = response.text
        connection_good = True
        logging.debug(f"Retrieved RM version: {response}")
    except SunriseClientError as exc:
        response = str(exc)
        connection_good = False
        logging.error(f"[rm_get_version()] Error: {exc}")
    return connection_good, response


def get_systems(rm_address: str) -> dict:
    """Get a list of available system names from the Runtime Manager."""
    system_names = []
    try:
        request = requests.Request('GET', f"{rm_address}/system")
        response = __send_request(request, timeout_s=4)
        systems = json.loads(response.text)
        for system_name in systems:
            response = __send_request(requests.Request('GET', f"{rm_address}/system/{system_name}"), timeout_s=5)
            versions = json.loads(response.text)
            for version in versions:
                system_names.append(system_name + ":" + version)
    except SunriseClientError as exc:
        logging.error(f"[rm_get_systems()] Error: {exc}")
    return system_names


def get_system_info(rm_address: str, system: str) -> typing.Union[sdf.SysDef, None]:
    """Get the SysDef file for a system from the Runtime Manager."""
    try:
        # Split System to separate name and version
        system = system.split(':', 1)
        response = __send_request(requests.Request('GET', f"{rm_address}/system/{system[0]}/{system[1]}"),
                                  timeout_s=100)
        received_sysdef = sdf.SysDef.model_validate(json.loads(response.text))
    except SunriseClientError as exc:
        logging.error(f"[rm_get_system_info()] Error: {exc}")
        received_sysdef = None
    return received_sysdef


def session_status(rm_address: str, session_id: str) -> sdf.State:
    """Get the status of an existing session"""
    response = __send_request(requests.Request('GET', f"{rm_address}/session/{session_id}/status"), timeout_s=5)
    return sdf.State(json.loads(response.text))


def session_set_fileparam(rm_address: str, session_id: str, param: uiu.ParamHandler, file: bytes,
                          filename: str = None) -> bool:
    """Change the data of a file-parameter in an existing session on the Runtime Manager."""
    try:
        parameter_group = param.get_param_group_name()
        parameter_name = param.key
        if isinstance(file, str):
            # A path was passed: read file to get binary data
            with open(file, "rb") as infile:
                bindata = infile.read()
            upload_filename = os.path.basename(file)
        elif isinstance(file, bytes):
            # Binary content was passed: directly forward to API
            bindata = file
            upload_filename = "file"
        else:
            raise SunriseClientError("EvalAPI call 'session_param_set_file' failed: object has incompatible Type")

        # If user enforces a filename by passing the argument: use it
        if filename:
            upload_filename = filename
        request = requests.Request('POST', f"{rm_address}/session/{session_id}/parameter/{parameter_group}",
                                   params={'parameter_name': parameter_name},
                                   files={'file': (upload_filename, bindata)}, headers={'accept': 'application/json'})
        __send_request(request, timeout_s=30)
        success = True
    except SunriseClientError as exc:
        logging.error(f"[rm_session_set_fileparam()] failed: {exc}")
        success = False
    return success


def session_create(rm_address: str, sescfg: uiu.SesCfg) -> typing.Tuple[str, uiu.ActionStatus]:
    """Create a new session. The system to use is defined by the passed SysCfg."""
    logging.info("Creating a new experiment.")
    status = uiu.ActionStatus()
    try:
        syscfg_json = sescfg.syscfg.model_dump()
        creator = sescfg.creator
        display_name = sescfg.display_name
        descr = sescfg.description

        request = requests.Request('POST', f"{rm_address}/session",
                                   json={'creator': creator, 'description': descr, 'display_name': display_name,
                                         'syscfg': syscfg_json})
        response = __send_request(request, timeout_s=100)

        session_id = json.loads(response.text)
        status.succeed("Session-ID: " + session_id)
        logging.info(f"... ID is {session_id}")
    except TypeError as type_err:
        logging.error("TypeError: Could not create session. Probably syscfg is invalid.")
        status.fail(str(type_err))
        session_id = None
    except SunriseClientError as exc:
        logging.error(f"[rm_session_create()] failed: {exc}")
        status.fail(str(exc))
        session_id = None
    return session_id, status


def session_build(rm_address: str, session_id: str, timeout_sec: int = 300) -> uiu.ActionStatus:
    """Execute the build step for an existing session."""
    logging.info("Calling BUILD")
    logging.debug(f"Session '{session_id}', Timeout {timeout_sec} sec.")
    status = uiu.ActionStatus()
    try:
        request = requests.Request('POST', f"{rm_address}/session/{session_id}/build", params={'timeout': timeout_sec})
        __send_request(request, timeout_s=5)

        timeout_counter = 0
        ses_stat = session_status(rm_address, session_id)
        while (ses_stat is sdf.State.BUILDING) and (timeout_counter < timeout_sec):
            time.sleep(1)
            timeout_counter += 1
            ses_stat = session_status(rm_address, session_id)

        if timeout_counter >= timeout_sec:
            status.fail("Timeout")
            logging.error("Timeout!")
            __send_request(requests.Request('POST', f"{rm_address}/session/{session_id}/stop"), timeout_s=5)
        else:
            log = session_get_log(rm_address, session_id, "container.build")
            if ses_stat is sdf.State.FAILED_BUILD:
                status.fail(log)
                logging.error("Build failed")
            else:
                status.succeed(log)
    except SunriseClientError as exc:
        status.fail(str(exc))
        logging.error(f"[rm_session_build()] Exception: {status.get_message()}")
    return status


def session_run(rm_address: str, session_id: str, timeout_sec: int = 300) -> uiu.ActionStatus:
    """Execute the run step for an existing session."""
    logging.info("Calling RUN")
    logging.debug(f"Session '{session_id}', Timeout {timeout_sec} sec.")
    status = uiu.ActionStatus()
    try:
        request = requests.Request('POST', f"{rm_address}/session/{session_id}/run", params={'timeout': timeout_sec})
        __send_request(request, timeout_s=5)
        timeout_counter = 0
        ses_stat = session_status(rm_address, session_id)
        while (ses_stat is sdf.State.RUNNING) and (timeout_counter < timeout_sec):
            time.sleep(1)
            timeout_counter += 1
            ses_stat = session_status(rm_address, session_id)

        if timeout_counter >= timeout_sec:
            status.fail("Timeout")
            logging.error("Timeout!")
            __send_request(requests.Request('POST', f"{rm_address}/session/{session_id}/stop"), timeout_s=5)
        else:
            log = session_get_log(rm_address, session_id, "container.run")
            if ses_stat is sdf.State.FAILED_RUN:
                status.fail(log)
                logging.error("Run failed")
            else:
                status.succeed(log)
    except SunriseClientError as exc:
        status.fail(str(exc))
        logging.error(f"[rm_session_run()] Exception: {status.get_message()}")
    return status


def session_remove(rm_address: str, session_id: str) -> uiu.ActionStatus:
    """Remove an existing session."""
    logging.info("Removing experiment")
    status = uiu.ActionStatus()
    try:
        response = __send_request(requests.Request('DELETE', f"{rm_address}/session/{session_id}"), timeout_s=10)
        if response.ok:
            status.succeed("Removed " + session_id)
    except SunriseClientError as exc:
        status.fail(str(exc))
        logging.error(f"[rm_session_remove()] Exception: {status.get_message()}")
    return status


def session_get_log(rm_address: str, session_id: str, producer_name: str) -> str | None:
    """Get log from session info. producer_name could be 'container.build' or 'container.run'"""
    action_log = None
    try:
        response = __send_request(requests.Request('GET', f"{rm_address}/session/{session_id}"), timeout_s=5)
        ses_info = sdf.SessionInfo.model_validate(json.loads(response.text))
    except json.JSONDecodeError as exc:
        logging.error(f"Invalid SessionInfo received: {exc}")
    except SunriseClientError as exc:
        logging.error(f"Getting log failed: {exc}")

    for log_obj in ses_info.session_logs:
        if log_obj.producer == producer_name:
            if action_log is None or log_obj.timestamp > action_log.timestamp:
                action_log = log_obj
    return action_log.message


def session_result_list(rm_address: str, session_id: str) -> list[sdf.ResultInfo]:
    """Get information of all available result objects in the session."""
    response = __send_request(requests.Request('GET', f"{rm_address}/session/{session_id}/result/"), timeout_s=100)
    results_raw = response.json()
    results = []
    for result in results_raw:
        results.append(sdf.ResultInfo.model_validate(result))
    return results


def fetch_results(rm_address: str, session_id: str, result_name: str) -> ResultObject:
    """
    Gets and caches result data and if possible result file name from Runtime Manager

    Returns a tuple of the object as bytes, the filename and the data type.
    """
    logging.info(f"Downloading result object '{result_name}'...")
    with st.spinner(f"Downloading object '{result_name}' for session '{session_id}'..."):
        response = __send_request(requests.Request('GET', f"{rm_address}/session/{session_id}/result/{result_name}"),
                                  timeout_s=100)
        result = ResultObject(name=result_name, data=response.content, session_id=session_id, type=None, filename=None)
        # try to extract the filename from the response header
        if 'content-disposition' in response.headers and 'filename' in response.headers['content-disposition']:
            result.filename = response.headers['content-disposition'].split('"')[1]
        # try to extract the data type from the response header
        if 'content-type' in response.headers:
            result.type = sdf.resultformats.ResultTypes(response.headers['content-type'])
    return result
