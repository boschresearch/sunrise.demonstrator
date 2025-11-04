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
This module is part of the SUNRISE demonstrator and creates a web-based user interface that serves as front-end.

The Streamlit framework is used to run the web server and infrastructure, the content of the page is defined here.
"""

import os
import logging
import streamlit as st
import pydantic

import ui_utils as uiu
import runtime_manager_interface as rmi
import dataformats


# LOCAL TYPES ##########################################################################################################
class MinUiCfg(pydantic.BaseModel):
    """Definition of System to be used in the Minimal UI Context
        system_name: Name of the system to be used
        system_version: the version of 'system_name'. If omitted, the first available version on the RM is used.
        display_name, creator, description: Information that is added to the experiment
        *_parameters: list of parameter names that should be presented to the user for modification
        results:list of result object names that should be presented. If 'None', all available are displayed.
    """
    system_name: str
    system_version: str | None = None
    display_name: str = "From Demo UI"
    creator: str = "UI User"
    description: str = ""
    common_parameters: list[str] = []
    build_parameters: list[str] = []
    run_parameters: list[str] = []
    results: list[str] | None = None

    def get_param_keys_to_modify(self, group: dataformats.ParameterGroup) -> list[str]:
        """Return the parameter type to be used in the SUNRISE Client API"""
        if group is dataformats.ParameterGroup.COMMON:
            return self.common_parameters
        if group is dataformats.ParameterGroup.BUILD:
            return self.build_parameters
        if group is dataformats.ParameterGroup.RUN:
            return self.run_parameters
        raise KeyError(f"Unknown group type: {group}")


# STREAMLIT STATE INITIALIZATION #######################################################################################
if "mnl_config" not in st.session_state:
    st.session_state.mnl_config = MinUiCfg(system_name="Demo System", build_parameters=["tracing"],
                                           run_parameters=["frequency"], results=["signal_trace"])
if "mnl_session_id" not in st.session_state:
    st.session_state.mnl_session_id = None
if "mnl_active_system" not in st.session_state:
    st.session_state.mnl_active_system = uiu.SystemHandler()
if "mnl_build_log" not in st.session_state:
    st.session_state["mnl_build_log"] = None
if "mnl_run_log" not in st.session_state:
    st.session_state["mnl_run_log"] = None
if "mnl_params_locked" not in st.session_state:
    st.session_state["mnl_params_locked"] = False


# BUILD GUI ELEMENTS ###################################################################################################
st.set_page_config(page_title="SUNRISE Front-End Demo", page_icon="img/sunrise_icon.ico",
                   initial_sidebar_state="collapsed")

st.image("img/sunrise_logo.svg", width=175)
st.title("SUNRISE Workflow")

# Runtime Manager Connection
rm_address = os.getenv("RUNTIME_MANAGER_URL", "http://localhost") + ":" + os.getenv("RUNTIME_MANAGER_PORT", "8000")
st.caption(f"Runtime Manager address: *{rm_address}*")
connected, version_message = rmi.get_version(rm_address)
if not connected:
    logging.error(f"Could not connect Runtime Manager '{rm_address}'")
    st.error("Runtime Manager not connected (unreachable)")

# Main Part
if connected:
    st.caption(f"Runtime Manager version: v{version_message}")
    if not st.session_state.mnl_active_system.is_available():
        logging.debug(f"Getting system details from RM ({rm_address})")
        available_systems = rmi.get_systems(rm_address)
        if st.session_state.mnl_config.system_version is None:
            system = next((sys for sys in available_systems if st.session_state.mnl_config.system_name in sys),
                          None)
            if system is None:
                raise ValueError(f"Selected system not found: '{st.session_state.mnl_config.system_name}'")
        else:
            system = st.session_state.mnl_config.system_name + ":" + st.session_state.mnl_config.system_version
            if system not in available_systems:
                raise ValueError(f"Selected system not found: '{system}'")
        sysdef = rmi.get_system_info(rm_address, system)
        st.session_state.mnl_active_system.from_sysdef(sysdef)
        st.session_state.mnl_active_system.session_parameters["display_name"].val_user =\
            st.session_state.mnl_config.display_name
        st.session_state.mnl_active_system.session_parameters["creator"].val_user =\
            st.session_state.mnl_config.creator
        st.session_state.mnl_active_system.session_parameters["description"].val_user =\
            st.session_state.mnl_config.description
    st.markdown(f"Using System **`{st.session_state.mnl_active_system.name}`**")
    ses_stat = None
    if st.session_state.mnl_session_id is not None:
        try:
            ses_stat = rmi.session_status(rm_address, st.session_state.mnl_session_id)
        except rmi.SunriseClientError as exc:
            raise RuntimeError("Session Status cannot be retrieved") from exc
    # Control locking of input widgets
    if (("but_workflow" in st.session_state and st.session_state.but_workflow)
            or (ses_stat is not None and ses_stat != dataformats.State.CREATED)):
        st.session_state.mnl_params_locked = True
    else:
        st.session_state.mnl_params_locked = False
    st.header("Parameters :wrench:")
    for param_group in dataformats.ParameterGroup:
        for param_key in st.session_state.mnl_config.get_param_keys_to_modify(param_group):
            if not st.session_state.mnl_active_system.has_parameter(param_group, param_key):
                raise ValueError(f"Parameter '{param_group}:{param_key}' not found in system!")
            param_obj = st.session_state.mnl_active_system[param_group][param_key]
            param_obj.init_widget_key("mnl_" + param_key)
            uiu.visualize_parameter(param_obj, disabled=st.session_state.mnl_params_locked)
    st.text("")  # Add some vertical space
    st.header("Experiment :microscope:")
    if st.button(":play_or_pause_button: Run Workflow",
                 disabled=st.session_state.mnl_params_locked, key='but_workflow'):
        with st.status("Workflow Execution", expanded=True) as stat:
            logging.debug("Starting Workflow execution")
            st.session_state["mnl_build_log"] = None
            st.session_state["mnl_run_log"] = None
            stat.update(label="Creating... :building_construction:", state="running")
            # Consider modified parameters
            for param_group in dataformats.ParameterGroup:
                for param_key in st.session_state.mnl_config.get_param_keys_to_modify(param_group):
                    param_obj = st.session_state.mnl_active_system[param_group][param_key]
                    if st.session_state[param_obj.ui_widget_key] != param_obj.val_user:
                        logging.debug(f"Parameter '{param_obj.key}' was modified")
                        param_obj.val_user = st.session_state[param_obj.ui_widget_key]
            logging.debug("Starting Session creation")
            st.session_state.mnl_session_id, res = rmi.session_create(
                rm_address, st.session_state.mnl_active_system.to_sescfg())
            if res.is_good():
                st.write(f":heavy_check_mark: Created Experiment *'{st.session_state.mnl_session_id}'*")
                logging.debug(f"Session ID is: {st.session_state.mnl_session_id}")
            else:
                stat.update(label="Create Failed", state="error")
                logging.error("Session create failed")
                raise RuntimeError(f"Could not create Experiment: {res.get_message()}")
            stat.update(label="Uploading File Parameters... :outbox_tray:", state="running")
            for param_group in dataformats.ParameterGroup:
                if st.session_state.mnl_active_system.has_parameter_group(param_group):
                    for param_key in st.session_state.mnl_config.get_param_keys_to_modify(param_group):
                        if st.session_state.mnl_active_system[param_group][param_key].is_fileparam():
                            param_obj = st.session_state.mnl_active_system[param_group][param_key]
                            uploader_value = st.session_state[param_obj.ui_widget_key]
                            if isinstance(uploader_value, st.runtime.uploaded_file_manager.UploadedFile):
                                logging.debug(f"Uploading file parameter {param_key}")
                                success = rmi.session_set_fileparam(rm_address, st.session_state.mnl_session_id,
                                                                    param_obj, uploader_value.getvalue(),
                                                                    uploader_value.name)
                                if success:
                                    st.write(f":heavy_check_mark: File *'{param_key}'* uploaded")
                                else:
                                    st.error(f"File *'{param_key}'* was not uploaded.")
                                    logging.error("File Upload failed")
            stat.update(label="Building... :hammer_and_pick:", state="running")
            res = rmi.session_build(rm_address, st.session_state.mnl_session_id)
            st.session_state.mnl_build_log = res.get_message()
            if res.is_good():
                logging.debug("Build finished successfully")
                st.write(":heavy_check_mark: Build completed")
            else:
                logging.error(f"Build failed: {res.get_message()}")
                st.error(f"Build failed: {res.get_message()}")
                stat.update(label="Build Failed", state="error")
            stat.update(label="Running... :repeat:", state="running")
            res = rmi.session_run(rm_address, st.session_state.mnl_session_id)
            st.session_state.mnl_run_log = res.get_message()
            if res.is_good():
                logging.debug("Run finished successfully")
                st.write(":heavy_check_mark: Run completed")
                stat.update(label="Finished", state="complete")
            else:
                logging.error(f"Run failed: {res.get_message()}")
                st.error(f"Run failed: {res.get_message()}")
                stat.update(label="Run Failed", state="error")
            st.rerun()
    if st.session_state.mnl_session_id is not None:
        st.markdown(f"Experiment ID: **`{st.session_state.mnl_session_id}`**")
        if ses_stat == dataformats.State.RAN:
            st.status("**Workflow Completed**", state="complete").markdown(f"Experiment Status: `{ses_stat.value}`")
            st.text("")  # Add some vertical space
            st.header("Result Analysis :bar_chart:")
            results = rmi.session_result_list(rm_address, st.session_state.mnl_session_id)
            if st.session_state.mnl_config.results is None:
                # No specific results selected, display all available
                results_to_display = [res for res in results if res.is_available]
            else:
                system_results = {res.name: res for res in results}
                results_to_display = []
                for res_name in st.session_state.mnl_config.results:
                    if res_name in system_results:
                        if system_results[res_name].is_available:
                            results_to_display.append(system_results[res_name])
                        else:
                            st.warning(f"Requested result object '{res_name}' is not available in this experiment")
                    else:
                        st.error(f"Result object '{res_name}' is not known to this system")
            for rtd in results_to_display:
                logging.debug(f"Displaying result '{rtd.name}'")
                result = rmi.fetch_results(rm_address, st.session_state.mnl_session_id, rtd.name)
                if result.type == dataformats.resultformats.ResultTypes.GENERIC_TEXT:
                    uiu.display_result_gentext(result.data)
                elif result.type == dataformats.resultformats.ResultTypes.PERFORMANCE:
                    uiu.display_result_performance(result.data)
                elif result.type == dataformats.resultformats.ResultTypes.SIM_SPEED:
                    uiu.display_result_simspeed(result.data)
                else:
                    st.info(f"Visualization of result '{result.name}' is not supported (incompatible type)")
        elif ses_stat in [dataformats.State.FAILED_BUILD, dataformats.State.FAILED_RUN]:
            st.status("**Workflow execution failed**",
                      state="error").markdown(f"Experiment Status: `{ses_stat.value}`")
        st.divider()
        if st.session_state.mnl_build_log is not None:
            with st.expander("Build Log"):
                st.text(st.session_state.mnl_build_log)
        if st.session_state.mnl_run_log is not None:
            with st.expander("Run Log"):
                st.text(st.session_state.mnl_run_log)
        st.divider()
        if st.button(":wastebasket: Delete Experiment", key="but_remove"):
            res = rmi.session_remove(rm_address, st.session_state.mnl_session_id)
            if res.is_good():
                logging.debug("Experiment successfully removed")
                st.session_state.mnl_session_id = None
                st.session_state.mnl_params_locked = False
                st.rerun()
            else:
                logging.error(f"Could not remove experiment: {res.get_message()}")
                st.error(f"Could not remove experiment '{st.session_state.mnl_session_id}': {res.get_message()}")
