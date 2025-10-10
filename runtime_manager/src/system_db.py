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
Database implementation of the System References (SysRefs).
"""

import os
import abc
import typing
import enum
import pydantic
import constants


class SystemNotFound(Exception):
    """Will be raised if a requested system cannot be found in database."""


# Represents an ObjectId field in the database.
# It will be represented as a `str` on the model so that it can be serialized to JSON.
PyObjectId = typing.Annotated[str, pydantic.BeforeValidator(str)]


class LocationType(str, enum.Enum):
    """Definition of location types for system."""
    GIT = "git"
    FILE = "file"
    DIR = "dir"
    IMG = "img"


class System(pydantic.BaseModel):
    """Specific version entry of a system in the system reference file format (SysRef)."""
    id: typing.Optional[PyObjectId] = pydantic.Field(alias="_id", default=None)
    name: str
    version: str
    description: str | None = None
    type: LocationType
    location: str
    branch: str


class UpdateSystem(pydantic.BaseModel):
    """Model for updating an existing system entry in the database."""
    name: typing.Optional[str] = None
    version: typing.Optional[str] = None
    description: typing.Optional[str] = None
    type: typing.Optional[LocationType] = None
    location: typing.Optional[str] = None
    branch: typing.Optional[str] = None


class Systems(pydantic.BaseModel):
    """Definition of the system reference file format (SysRef)."""
    systems: list[System]


class SystemDatabaseInterface(metaclass=abc.ABCMeta):
    """Interface for system references database operations."""
    @abc.abstractmethod
    def create_system(self, system: System) -> System:
        """Create a new system entry."""
        return None

    @abc.abstractmethod
    def get_system_names(self) -> list[str]:
        """Returns a list of all available system names."""
        return None

    @abc.abstractmethod
    def get_system_versions(self, name: str) -> list[str]:
        """Returns a list with all available versions of a specific system name."""
        return None

    @abc.abstractmethod
    def get_system(self, name: str, version: str) -> System:
        """Returns a specific system with the provided name and version."""
        return None

    @abc.abstractmethod
    def update_system(self, name: str, version: str, system: UpdateSystem) -> System:
        """Updates a system entry with new values."""
        return None

    @abc.abstractmethod
    def delete_system(self, name: str, version: str) -> bool:
        """Deletes a system entry."""
        return None


class SystemJsonFile(SystemDatabaseInterface):
    """System references management using simple JSON file."""

    def __init__(self) -> None:
        """Opens and parses the JSON file containing the system references."""
        self.json_file = constants.SYSTEM_REFERENCES_FILE

    def __parse_file(self) -> Systems:
        """Parses the system reference file and writes the content to member variable."""
        if os.path.isfile(self.json_file):
            with open(self.json_file, 'r', encoding='utf-8') as file:
                return Systems.model_validate_json(file.read())
        else:
            return Systems(systems=[])

    def create_system(self, system: System) -> System:
        """Create a new system entry in the JSON file."""
        systems_db = self.__parse_file()
        systems_db.systems.append(system)
        with open(self.json_file, 'w', encoding='utf-8') as file:
            file.write(systems_db.model_dump_json(indent=2))
        return system

    def get_system_names(self) -> list[str]:
        """Returns a list of all available system names in the JSON file."""
        names = []
        systems_db = self.__parse_file()
        for system in systems_db.systems:
            # add systems with different versions only once to the list
            if system.name not in names:
                names.append(system.name)
        return names

    def get_system_versions(self, name: str) -> list[str]:
        """Returns a list of all available versions of a specific system name in the JSON file."""
        versions = []
        systems_db = self.__parse_file()
        for system_entry in systems_db.systems:
            if system_entry.name == name:
                versions.append(system_entry.version)
        return versions

    def get_system(self, name: str, version: str) -> System:
        """Returns the system entry of a specific system from the JSON file."""
        systems_db = self.__parse_file()
        for system in systems_db.systems:
            if system.name == name and system.version == version:
                return system
        raise SystemNotFound(f"Cannot find the system '{name}' with version '{version}'!")

    def update_system(self, name: str, version: str, system: UpdateSystem) -> System:
        """Updates a system entry in the JSON file."""
        systems_db = self.__parse_file()
        for system_entry in systems_db.systems:
            if system_entry.name == name and system_entry.version == version:
                if system.name is not None:
                    system_entry.name = system.name
                if system.version is not None:
                    system_entry.version = system.version
                if system.description is not None:
                    system_entry.description = system.description
                if system.type is not None:
                    system_entry.type = system.type
                if system.location is not None:
                    system_entry.location = system.location
                if system.branch is not None:
                    system_entry.branch = system.branch
                with open(self.json_file, 'w', encoding='utf-8') as file:
                    file.write(systems_db.model_dump_json(indent=2))
                return system_entry
        raise SystemNotFound(f"Cannot find the system '{name}' with version '{version}'!")

    def delete_system(self, name: str, version: str) -> bool:
        """Deletes a specific system entry in the JSON file."""
        systems_db = self.__parse_file()
        for system_entry in systems_db.systems:
            if system_entry.name == name and system_entry.version == version:
                systems_db.systems.remove(system_entry)
                with open(self.json_file, 'w', encoding='utf-8') as file:
                    file.write(systems_db.model_dump_json(indent=2))
                return True
        raise SystemNotFound(f"Cannot find the system '{name}' with version '{version}'!")


systems: SystemDatabaseInterface = SystemJsonFile()
