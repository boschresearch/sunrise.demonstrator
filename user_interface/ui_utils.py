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
Utilities for the SUNRISE web-based user-interface.
"""

from datetime import datetime
from enum import Enum
import typing
import dataclasses
import inspect
import pydantic
import streamlit as st

import dataformats as sdf


@dataclasses.dataclass
class ActionStatus:
    """"Class to cache the execution status of a generic action."""
    __available: bool
    __error: bool
    __message: str
    __timestamp: datetime.timestamp

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset all internal variables."""
        self.__available = False
        self.__error = False
        self.__message = "n/a"
        self.__timestamp = None

    def succeed(self, msg: str = "success") -> None:
        """Set positive status with optional passed message."""
        self.__available = True
        self.__error = False
        self.__message = msg
        self.__timestamp = datetime.now()

    def fail(self, msg: str = "error") -> None:
        """Set negative status with optional passed message."""
        self.__available = True
        self.__error = True
        self.__message = msg
        self.__timestamp = datetime.now()

    def is_available(self) -> bool:
        """Check if status was set."""
        return self.__available

    def is_good(self) -> bool:
        """Check if status is positive."""
        return self.__available and not self.__error

    def is_failed(self) -> bool:
        """Check if status is negative."""
        return self.__available and self.__error

    def get_message(self) -> str:
        """Return status message."""
        return self.__message

    def get_timestamp_str(self) -> str:
        """Return timestamp when the status was set."""
        if self.__timestamp is None:
            return ""
        return self.__timestamp.strftime("%H:%M:%S")


class SesCfg(pydantic.BaseModel):
    """Definition of a session configuration, created by the user."""
    syscfg: sdf.SysCfg
    display_name: str
    description: str
    creator: str


class ParamKind(str, Enum):
    """Types of parameters. (Not using sunrise package 'ParameterGroup' since it does not contain session parameters)"""
    SESSION = "session"
    COMMON = "common"
    BUILD = "build"
    RUN = "run"

    def group_name(self) -> str:
        """Create a string '<value>_parameters' that is compatible to the SUNRISE dataformats enum string definition."""
        return self.value + "_parameters"


class ParamHandler:
    """Handle a single parameter in the UI."""

    def __init__(self, key: str, kind: ParamKind, reset_value="") -> None:
        self.key: str = key             # hierarchical parameter name
        self.kind = kind
        self.val_reset = reset_value
        self.ui_widget_key = None
        if self.is_fileparam():
            self.val_user = None
        elif self.__is_complex_param():
            self.val_user = self.val_reset.default_value
        else:
            self.val_user = self.val_reset

    def init_widget_key(self, name: str = None) -> str:
        """Assign a widget key. Should be called when also the widget is created."""
        if name is None:
            name = self.key
        self.ui_widget_key = f"par_{self.kind}_{name}"

    def get_param_group(self) -> sdf.ParameterGroup | None:
        """Return the parameter type to be used in the SUNRISE Client API"""
        if self.kind is ParamKind.COMMON:
            return sdf.ParameterGroup.COMMON
        if self.kind is ParamKind.BUILD:
            return sdf.ParameterGroup.BUILD
        if self.kind is ParamKind.RUN:
            return sdf.ParameterGroup.RUN
        return None

    def get_param_group_name(self) -> str:
        """Get the name of the parameter type, e.g. 'build',."""
        return self.get_param_group().rootname()

    def in_syscfg(self) -> bool:
        "Return true if the parameter object type can be added to a SysCfg."
        return not self.is_fileparam() and \
            isinstance(self.val_user, (str, bool, int, float, sdf.SysCfgUrlParameter))

    def __is_complex_param(self) -> bool:
        """Check of current instance is a complex parameter"""
        return isinstance(self.val_reset, sdf.SysDefCmplxParameter)

    def is_fileparam(self) -> bool:
        """Check of current instance is a file parameter"""
        return self.__is_complex_param() and self.val_reset.is_fileparam()

    def is_enum_param(self) -> bool:
        """Check of current instance is a enum parameter"""
        return self.__is_complex_param() and isinstance(self.val_reset.meta, sdf.SysDefParameterEnum)

    def is_range_param(self) -> bool:
        """Check of current instance is a range parameter"""
        return self.__is_complex_param() and isinstance(self.val_reset.meta, sdf.SysDefParameterRange)


class SystemHandler:
    """Handle all parameters of a system for the UI."""

    def __init__(self, sysdef: sdf.SysDef = None) -> None:
        """Set up this instance either empty or from a SysDef object"""
        self.sysdef: sdf.SysDef
        self.name: str
        self.session_parameters: typing.Dict[ParamHandler]
        self.common_parameters: typing.Dict[ParamHandler]
        self.build_parameters: typing.Dict[ParamHandler]
        self.run_parameters: typing.Dict[ParamHandler]
        if sysdef is None:
            self.reset()
        else:
            self.from_sysdef(sysdef)

    def __getitem__(self, item):
        """Make class indexable e.g. to read parameter groups with name: my_syshandler["build_parameters"]"""
        return getattr(self, item)

    def __setitem__(self, item, value):
        """Make class indexable e.g. to writer parameter groups with name: my_syshandler["build_parameters"] = {...}"""
        return setattr(self, item, value)

    def reset(self, name2keep: str = None):
        """Set member variables to default"""
        self.sysdef = None
        self.name = name2keep
        self.session_parameters = None
        self.common_parameters = None
        self.build_parameters = None
        self.run_parameters = None

    def from_sysdef(self, sysdef: sdf.SysDef) -> None:
        """Fill in data from a SysDef object"""
        self.sysdef = sysdef
        self.name = sysdef.name + ":" + sysdef.version

        for paramgroup in sdf.ParameterGroup:
            if sysdef[paramgroup] is None:
                self[paramgroup] = None
            else:
                self[paramgroup] = {}
                for name in sysdef[paramgroup]:
                    self[paramgroup][name] = ParamHandler(name, ParamKind(paramgroup.rootname()),
                                                          sysdef[paramgroup][name])
        self.session_parameters = {}
        for param in inspect.get_annotations(SesCfg):
            if param == "syscfg":
                continue
            self.session_parameters[param] = ParamHandler(param, ParamKind.SESSION)

    def is_available(self) -> bool:
        """Check if this instance was initialized"""
        return self.name is not None and self.sysdef is not None

    def has_parameter_group(self, group: ParamKind | sdf.ParameterGroup | str) -> bool:
        """Check if parameter group is available in this system (string must be <session|common|build|run>_parameters"""
        group_name = None
        if isinstance(group, ParamKind):
            group_name = group.group_name()
        elif isinstance(group, sdf.ParameterGroup):
            group_name = group.value
        else:
            raise ValueError(f"Unknown Group type: {group}")
        return (self[group_name] is not None) and (self[group_name] != {})

    def has_session_params(self) -> bool:
        """Check if session parameters are added"""
        return self.has_parameter_group(ParamKind.SESSION)

    def has_common_params(self) -> bool:
        """Check if system has common parameters"""
        return self.has_parameter_group(ParamKind.COMMON)

    def has_build_params(self) -> bool:
        """Check if system has build parameters"""
        return self.has_parameter_group(ParamKind.BUILD)

    def has_run_params(self) -> bool:
        """Check if system has run parameters"""
        return self.has_parameter_group(ParamKind.RUN)

    def has_parameter(self, group: ParamKind | sdf.ParameterGroup | str, name: str) -> bool:
        """Check if system has a parameter with the passed name in the passed group"""
        return self.has_parameter_group(group) and name in self[group]

    def to_sescfg(self) -> SesCfg | None:
        """Create a session configuration object from class data"""
        if not self.is_available():
            return None

        (sysname, sysversion) = self.name.split(':', 1)
        syscfg = sdf.SysCfg(system=sdf.SysCfgSystem(name=sysname, version=sysversion))

        # Handle action parameters
        for paramgroup in sdf.ParameterGroup:
            if self.has_parameter_group(paramgroup):
                syscfg[paramgroup] = {}
                for param_key, param_obj in self[paramgroup].items():
                    if param_obj.in_syscfg():
                        syscfg[paramgroup][param_key] = param_obj.val_user
            else:
                syscfg[paramgroup] = None

        # Handle session parameters
        display_name = self.session_parameters["display_name"].val_user
        creator = self.session_parameters["creator"].val_user
        description = self.session_parameters["description"].val_user
        sescfg = SesCfg(syscfg=syscfg, display_name=display_name, creator=creator, description=description)
        return sescfg


def visualize_parameter(param_obj: ParamHandler, display_name: str = None, disabled: bool = False):
    """Create specific Streamlit widget for the passed parameter. Type is chosen according to parameter data type."""
    if display_name is None:
        display_name = param_obj.key

    if (param_obj.ui_widget_key in st.session_state
            and st.session_state[param_obj.ui_widget_key] != param_obj.val_user):
        # Case triggered when the user changes a value and its not yet stored in the cached data
        val = st.session_state[param_obj.ui_widget_key]
    else:
        val = param_obj.val_user

    if param_obj.is_fileparam():
        st.file_uploader(display_name, key=param_obj.ui_widget_key, disabled=disabled)
    elif param_obj.is_enum_param():
        # Find out list index of currently selected element for initial value of selectbox
        idx = param_obj.val_reset.meta.values.index(param_obj.val_user)
        st.selectbox(display_name, param_obj.val_reset.meta.values, key=param_obj.ui_widget_key, index=idx,
                     disabled=disabled)
    elif param_obj.is_range_param():
        max_steps = 100
        lower = param_obj.val_reset.meta.lower
        upper = param_obj.val_reset.meta.upper
        step = (upper - lower) / max_steps
        if isinstance(param_obj.val_user, int):
            step = int(max(1, round(step)))
        else:
            lower = float(lower)
            upper = float(upper)
        st.slider(display_name, key=param_obj.ui_widget_key, step=step, value=val, min_value=lower, max_value=upper,
                  disabled=disabled)
    elif isinstance(val, bool):
        st.toggle(display_name, key=param_obj.ui_widget_key, value=val, disabled=disabled)
    elif isinstance(val, (int, float)):
        st.number_input(display_name, key=param_obj.ui_widget_key, value=val, disabled=disabled)
    elif isinstance(val, str):
        st.text_input(display_name, key=param_obj.ui_widget_key, value=val, disabled=disabled)
    elif isinstance(val, dict):
        error_message = f"Parameter '{display_name}' of type 'dict' is not supported: Using default value!"
        st.info(error_message)
    else:
        error_message = f"Parameter '{display_name}' has incompatible type: {str(type(val))}"
        st.error(error_message)


# Visualization of dedicated result types ##############################################################################
def display_result_gentext(obj: bytes):
    """Display generic text object just as text on UI"""
    st.subheader("Generic Text")
    content = obj.decode("utf-8")
    # keep expander closed if text has more than 100 lines
    expand = content.count('\n') < 100
    with st.expander("Text Result", expanded=expand):
        st.text(content)


def display_result_performance(obj: bytes):
    """Show values of a performance JSON file."""
    st.subheader("Core Performance")
    performance = sdf.resultformats.Performance.model_validate_json(obj.decode("utf-8"))
    left, middle, right = st.columns(3)
    left.metric("**Instructions:**", value=performance.instructions)
    middle.metric("**Cycles:**", value=performance.cycles)
    right.metric("**Cycles per Instruction (CPI)**", value=f"{performance.cycles / performance.instructions:.3f}")
    st.write(f"Measured with a core frequency of {performance.frequency_hz/1e6:.3g} MHz"
             + f", so the duration is {performance.cycles/performance.frequency_hz:.3g} seconds.")


def display_result_simspeed(obj: bytes):
    """Show values of a simspeed JSON file."""
    st.subheader("Simulation Speed")
    simspeed = sdf.resultformats.SimSpeed.model_validate_json(obj.decode("utf-8"))
    left, middle, right = st.columns(3)
    left.metric("**Simulated Time:**", value=f"{simspeed.simulated_time_sec:.3g} sec")
    middle.metric("**Wall-Clock Time:**", value=f"{simspeed.execution_time_sec:.3g} sec")
    right.metric("**Real-Time Factor (RTF):**", value=f"{simspeed.get_rtf():.3g}")
    right.text("RTF = T_wallclock / T_simulated")
