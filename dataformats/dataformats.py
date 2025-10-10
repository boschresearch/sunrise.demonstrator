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

import datetime
import enum
import os
from typing import Union, Optional
import pydantic
from . import resultformats

# expected format identifiers
SYSCFG_DATAFORMAT_IDENTIFIER = 'syscfg:0.3'
SYSDEF_DATAFORMAT_IDENTIFIER = 'sysdef:0.4'
SESSIONINFO_DATAFORMAT_IDENTIFIER = 'sessioninfo:0.3'


class State(str, enum.Enum):
    """Definition of states of a Session."""
    CREATED = "created"
    BUILDING = "building"
    BUILT = "built"
    FAILED_BUILD = "failed build"
    RUNNING = "running"
    RAN = "ran"
    FAILED_RUN = "failed run"


class ParameterGroup(str, enum.Enum):
    """Available parameter groups in SysDef and SysCfg."""
    COMMON = "common_parameters"
    BUILD = "build_parameters"
    RUN = "run_parameters"

    def rootname(self) -> str:
        """Return the group name without trailing '_parameters'"""
        return self.value.rstrip("_parameters")


class SysDefParameterEnum(pydantic.BaseModel):
    """Definition of a enum constraint of a parameter of the SysDef file."""
    values: Union[list[str], list[bool], list[int], list[float]]


class SysDefParameterRange(pydantic.BaseModel):
    """Definition of a min-max constraint of a parameter of the SysDef file."""
    lower: Union[int, float]
    upper: Union[int, float]


class SysDefParameterFile(pydantic.BaseModel):
    """Definition of a file parameter in the SysDef file."""
    is_file: bool = True


class SysDefCmplxParameter(pydantic.BaseModel):
    """Definition of a parameter of the SysDef file."""
    default_value: Union[str, bool, int, float]
    meta: Union[SysDefParameterEnum, SysDefParameterRange, SysDefParameterFile, None] = None
    description: Optional[str] = None

    def is_fileparam(self) -> bool:
        """"return true if this object is a file parameter"""
        return isinstance(self.meta, SysDefParameterFile)

    @pydantic.model_validator(mode='after')
    def check_default_value(self):
        """Check if the default value is legal for the used type, which is specified in 'meta'."""
        if isinstance(self.meta, SysDefParameterEnum):
            if not isinstance(self.default_value, type(self.meta.values[0])):
                raise ValueError(f"Default value of enum-parameter has unexpected type {type(self.default_value)}")
            if self.default_value not in self.meta.values:
                raise ValueError(f"Unexpected default value of enum-parameter '{self.default_value}'")
        elif isinstance(self.meta, SysDefParameterRange):
            if not isinstance(self.default_value, (int, float)):
                raise ValueError(f"Default value of range-parameter has unexpected type {type(self.default_value)}")
            if not self.meta.lower <= self.default_value <= self.meta.upper:
                raise ValueError(f"Default value of range-parameter is not inside boundaries: {self.default_value}")
        elif isinstance(self.meta, SysDefParameterFile):
            if not isinstance(self.default_value, str):
                raise ValueError(f"Default value of file-parameter is not a string: '{self.default_value}'")
        return self


class SysDefResult(pydantic.BaseModel):
    """Definition of a complex result of the SysDef file."""
    type: resultformats.ResultTypes
    path: str
    enabled_by: Optional[list[str]] = None
    description: Optional[str] = None


class SysDefDoc(pydantic.BaseModel):
    """Definition of System Documentation"""
    contact: str
    summary: str
    description: Union[str, os.PathLike]


class SysDef(pydantic.BaseModel):
    """Definition of the system definition file format (SysDef)."""
    dataformat: Optional[str] = SYSDEF_DATAFORMAT_IDENTIFIER
    name: str
    version: str
    documentation: Optional[SysDefDoc] = None
    docker_image: str
    build_command: Optional[str] = None
    run_command: str
    delete_command: Optional[str] = None
    common_parameters: Optional[
        dict[str, Union[str, bool, int, float, SysDefCmplxParameter, None]]] = None
    build_parameters: Optional[
        dict[str, Union[str, bool, int, float, SysDefCmplxParameter, None]]] = None
    run_parameters: Optional[
        dict[str, Union[str, bool, int, float, SysDefCmplxParameter, None]]] = None
    results: Optional[dict[str, SysDefResult]] = None

    @pydantic.model_validator(mode='after')
    def check_result_enabled_by(self):
        """Check of the 'enabled_by' switch of the result objects during model validation."""
        for result in self.results.values():
            if result.enabled_by is not None:
                for enabler in result.enabled_by:
                    if not enabler.startswith("#/"):
                        raise ValueError(f"'enabled_by' must start with '#/' to be a valid JSON pointer: '{enabler}'")

                    enabler_hierarchy = enabler.split('/')
                    parameter_group = ParameterGroup(enabler_hierarchy[1])
                    parameter_name = enabler_hierarchy[2]
                    if parameter_name not in self[parameter_group]:
                        raise ValueError(f"Enabling parameter name does not exist: '{enabler}'")
                    if not isinstance(self[parameter_group][parameter_name], bool):
                        raise ValueError(f"Enabling parameter must be of type bool: '{enabler}'")
        return self

    def __getitem__(self, item):
        """Make class indexable e.g. to read parameter groups with name: my_sysdef["build_parameters"]"""
        return getattr(self, item)

    def __setitem__(self, item, value):
        """Make class indexable e.g. to writer parameter groups with name: my_sysdef["build_parameters"] = {...}"""
        return setattr(self, item, value)


class SysCfgSystem(pydantic.BaseModel):
    """Definition of the system description part of the SysCfg file."""
    name: str
    version: str


class SysCfgUrlParameter(pydantic.BaseModel):
    """Definition of a URL-based file parameter entry in the SysCfg file."""
    url: str
    credentials: Optional[str] = None


class SysCfg(pydantic.BaseModel):
    """Definition of the system configuration file format (SysCfg)."""
    dataformat: Optional[str] = SYSCFG_DATAFORMAT_IDENTIFIER
    system: SysCfgSystem
    common_parameters: Optional[dict[str, Union[str, bool, int, float, SysCfgUrlParameter, None]]] = None
    build_parameters: Optional[dict[str, Union[str, bool, int, float, SysCfgUrlParameter, None]]] = None
    run_parameters: Optional[dict[str, Union[str, bool, int, float, SysCfgUrlParameter, None]]] = None

    def __getitem__(self, item):
        """Make class indexable e.g. to read parameter groups with name: my_syscfg["build_parameters"]"""
        return getattr(self, item)

    def __setitem__(self, item, value):
        """Make class indexable e.g. to writer parameter groups with name: my_syscfg["build_parameters"] = {...}"""
        return setattr(self, item, value)

    @classmethod
    def from_sysdef(cls, sysdef: SysDef):
        """Create a new SysCfg instance with default values from a SysDef object."""
        instance = cls(system=SysCfgSystem(name=sysdef.name, version=sysdef.version))
        for param_grp in ParameterGroup:
            if sysdef[param_grp]:
                instance[param_grp] = {}
                for key in sysdef[param_grp]:
                    if isinstance(sysdef[param_grp][key], SysDefCmplxParameter):
                        instance[param_grp][key] = sysdef[param_grp][key].default_value
                    else:
                        instance[param_grp][key] = sysdef[param_grp][key]
        return instance


class LogEntry(pydantic.BaseModel):
    """Definition of a log entry inside the SessionInfo object"""
    timestamp: datetime.datetime
    producer: str
    message: str


class SessionInfo(pydantic.BaseModel):
    """Definition of the session information data format."""
    dataformat: Optional[str] = SESSIONINFO_DATAFORMAT_IDENTIFIER
    display_name: str
    system_name: str
    system_version: str
    creator_name: str
    creation_date: datetime.datetime
    session_description: str
    session_state: State
    session_logs: list[LogEntry]
    syscfg: SysCfg


class ResultInfo(pydantic.BaseModel):
    """Holds information about a result."""
    name: str
    type: resultformats.ResultTypes
    is_available: bool
    message: Optional[str]


class CreateSessionItem(pydantic.BaseModel):
    """Contains session configuration settings."""
    syscfg: SysCfg
    creator: Optional[str] = None
    description: Optional[str] = None
    display_name: Optional[str] = None
    remote: Optional[bool] = False


class UpdateParameterItem(pydantic.BaseModel):
    """Dataclass holding parameter values or file parameter content"""
    name: str
    value: Union[str, bool, int, float, dict]
