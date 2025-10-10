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
Handles all constants and parameters of SUNRISE Runtime Manager.
"""

import os
import pathlib


# name of the session storage file
SESSION_FILE = 'sessions'

# base directory of sessions data
SESSIONS_BASE_DIR = os.environ.get('SUNRISE_RUNTIME_MANAGER_SESSION_PATH', os.path.join(os.getcwd(), 'sessions'))

# working dir inside Docker container (mount point of Docker volume), use absolute path
CONTAINER_WORKDIR = '/sysapi'

# default name of a session creator
DEFAULT_CREATOR_NAME = 'default-user'

# absolute filepath to the SUNRISE Runtime Manager root directory
SUNRISE_RUNTIME_MANAGER_FULL_PATH = pathlib.Path(__file__).parent.parent.resolve()

# version of SUNRISE Runtime Manager as string (major.minor version number)
with open(os.path.join(SUNRISE_RUNTIME_MANAGER_FULL_PATH, 'VERSION'), mode="r", encoding="utf-8") as version_file:
    SUNRISE_RUNTIME_MANAGER_VERSION = version_file.readline().strip()

# absolute filepath to the system references (SysRefs) in case local database is used
SYSTEM_REFERENCES_FILE = os.path.join(SUNRISE_RUNTIME_MANAGER_FULL_PATH, 'config', 'systems', 'systems.json')
