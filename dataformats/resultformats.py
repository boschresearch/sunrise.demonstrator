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

import csv
import enum
from typing import Union, Optional
import pydantic


class ResultTypes(str, enum.Enum):
    """List of all pre-defined result types."""
    GENERIC_BINARY = "binary"
    GENERIC_TEXT = "text"
    VCD_TRACE = "vcd"
    FST_TRACE = "fst"
    PERFORMANCE = "performance"
    SIM_SPEED = "simulation_speed"
    JUNIT_XML = "junit_xml"
    PROFILE_GPROF = "gprof"
    PROFILE_TABLE = "profile_csv"


class Performance(pydantic.BaseModel):
    """Format to describe performance metrics of a CPU."""
    instructions: Optional[int] = None  # Number of executed instructions
    cycles: Optional[int] = None  # Number of required clock cycles
    frequency_hz: Optional[float] = None  # Core clock frequency, defines the cycle period


class SimSpeed(pydantic.BaseModel):
    """Format to define execution performance of a simulation."""
    simulated_time_sec: float  # Duration that was simulated in seconds.
    execution_time_sec: float  # The time how long the simulation ran (wall-clock time) in seconds.

    def get_rtf(self) -> float:
        """Return the real-time factor of the simulation run (smaller number indicates faster simulation)"""
        return self.execution_time_sec / self.simulated_time_sec


class FunctionProfileData(pydantic.BaseModel):
    """Profiling results for a single function"""
    function: str
    address: int
    count: int
    percent: float
    self_cycles: int
    cumulative_cycles: int

    @pydantic.field_validator("address", mode="before")
    @classmethod
    def validate_address(cls, value: Union[int, str]):
        """Address typically is a hexadecimal number read as string - store it as integer"""
        if isinstance(value, str):
            if value.startswith("0x"):
                value = value[2:]
            try:
                return int(value, 16)
            except ValueError as exc:
                raise ValueError("Address must be a hexadecimal number") from exc
        else:
            return value


class FunctionProfile:
    """Overall function profiling result table, typically from parsing a CSV file"""
    def __init__(self, function_data_list: list[FunctionProfileData]):
        self.functions = function_data_list

    @classmethod
    def from_csv_file(cls, filepath):
        """Read the a CSV file and convert the data to a list of FunctionProfileData dictionaries"""
        with open(filepath, 'r', encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            functions = []
            for row in reader:
                functions.append(FunctionProfileData.model_validate(row))
        return cls(functions)

    def len(self):
        """Return number of functions tracked"""
        return len(self.functions)

    def cycles(self):
        """calculate how many cycles are recorded in the profile"""
        return sum(fn.self_cycles for fn in self.functions)
