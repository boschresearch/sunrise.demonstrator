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
Handles the configuration file parsing.
"""

import enum
import uuid
import dataclasses
import re
import os
import logging
import pathlib
import shutil
import typing
import pydantic
import git
import docker
import parameters
from dataformats import dataformats
import system_db
import documentation
import compute_if
import compute_docker
import constants


class SysRefEntry(pydantic.BaseModel):
    """Specific version entry of a system in the system reference file format (SysRef)."""
    description: str | None = None
    type: str
    location: str
    branch: str


class SysRef(pydantic.BaseModel):
    """Definition of the system reference file format (SysRef)."""
    dataformat: typing.Literal['sysref:1.0'] = 'sysref:1.0'
    name: str
    versions: dict[str, SysRefEntry]


@dataclasses.dataclass
class SystemIdentifier:
    """Name and version of system as unique identifier."""
    name: str
    version: str


@dataclasses.dataclass
class SystemData:
    """Contains system related data."""
    parameters: dict[dataformats.ParameterGroup, list[parameters.Parameter]]
    results: dict[str, dataformats.SysDefResult]


class ParameterGroupIdentifier(str, enum.Enum):
    """Parameter group identifiers used by REST API (EvalAPI)."""
    COMMON = "common"
    BUILD = "build"
    RUN = "run"


class ComputeBackend(enum.Enum):
    """Enumeration of supported compute backends."""
    DOCKER = "docker"


# Mapping of ComputeBackend enum to corresponding compute backend classes
backend_mapping = {
    ComputeBackend.DOCKER: compute_docker.ComputeDocker
}


class System:
    """Defines all system-instance related parts.

    This includes getting system artifacts, parsing system-parameters, start of
    build and run or extracting results.
    """

    # get sunrise system logger for static methods
    log = logging.getLogger('sunrise.system')

    def __init__(self, session_id: str, syscfg: dataformats.SysCfg, repo_clone_path: os.PathLike, remote: bool) -> None:
        """Parses SysCfg and creates a system instance from it."""
        # get sunrise system logger for instance methods
        self._log = logging.getLogger('sunrise.system')
        self.session_id = session_id
        # system related data
        self.data: SystemData
        self.system_id: SystemIdentifier
        self.has_build: bool
        # syscfg file path for backend computation (in perspective of container for SysAPI)
        self.syscfg_container_path = os.path.join(constants.CONTAINER_WORKDIR, 'inputs', 'syscfg.json')
        # computation backend instance
        self.compute_backend = self.__get_compute_backend(remote)
        # create a system based on system configuration file
        self.__parse_system_config(syscfg, repo_clone_path)

    def __get_compute_backend(self, remote: bool) -> compute_if.ComputeInterface:
        """Returns the appropriate compute backend based on environment variables."""
        if remote:
            self._log.warning("Remote compute backend not supported. Switching to default Docker backend...")

        self._log.info("Cloud simulation is disabled. Using local Docker daemon as the compute backend.")
        return compute_docker.ComputeDocker()

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
        self._log = logging.getLogger('sunrise.system')

    def __get_system_definition(self, source: os.PathLike) -> dataformats.SysDef:
        """Extracts the system definition file from the already cloned git repository of the system."""
        # access system definition with standard file operations as repository containing the sysdef
        # file is already cloned
        if not os.path.isfile(source):
            message = "sysdef.json is missing in cloned repository!"
            self._log.error(message)
            raise FileNotFoundError(message)
        with open(source, 'r', encoding='utf-8') as sysdef_file:
            system_definition: dataformats.SysDef = dataformats.SysDef.model_validate_json(sysdef_file.read())
        return system_definition

    def __clone_repository(self, url, branch, path):
        """Clones recursively repositories into the session workspace."""
        self._log.debug("Cloning repository from URL '%s'", url)
        try:
            system_repo = git.Repo.init(path)
            git_remote = system_repo.create_remote("origin", url)
            git_remote.fetch(branch, depth=1)
            system_repo.git.checkout("FETCH_HEAD")
            for submodule in system_repo.submodules:
                self.__clone_repository(submodule.url, submodule.branch_name,
                                        os.path.join(path, submodule.path))
        except git.GitCommandError as exc:
            message = f"Failed to clone the git repository '{url}': {str(exc)}"
            self._log.error(message)
            raise RuntimeError(message) from exc
        # remove git folder as no git operations are required for the cloned repository
        shutil.rmtree(os.path.join(path, '.git'))
        self._log.debug("Cloning was successful.")

    def __parse_parameter_group(self, sysdef_parameters, syscfg_parameters):
        """This helper function parses all parameters of a given parameter group of the system definition file.

        If a parameter is missing in the system configuration file then the
        default value of the parameter from the system definition file is used.
        """
        # check if config file contains valid parameters
        # (shall match with parameters of system file)
        if syscfg_parameters is not None:
            if sysdef_parameters is None and len(syscfg_parameters) > 0:
                message = "Cannot find parameter group of SysCfg file in SysDef file!"
                self._log.error(message)
                raise ValueError(message)
            # check if all parameters in SysCfg are defined in SysDef
            for param_name in syscfg_parameters.keys():
                if param_name not in sysdef_parameters:
                    message = f"Cannot find parameter '{param_name}' of SysCfg file in SysDef file!"
                    self._log.error(message)
                    raise ValueError(message)
        if sysdef_parameters is None:
            # the parameter group doesn't exist both in SysDef and SysCfg -> return empty parameter group
            return []

        parameter_group = []
        # list of all parameter names to check if all parameter names are unique
        all_parameter_names = []
        # iterate through all parameters of the system definition file
        for param_name, sysdef_param_value in sysdef_parameters.items():
            # check if parameter name is unique over all parameter groups
            if param_name in all_parameter_names:
                message = f"Parameter '{param_name}' is multiple times defined. "\
                           "Parameter names must be unique inside a parameter group."
                self._log.error(message)
                raise ValueError(message)
            all_parameter_names.append(param_name)
            # in case a matching parameter name is found in the system configuration file the system
            # definition parameter will be overwritten
            if syscfg_parameters is not None and param_name in syscfg_parameters and\
               syscfg_parameters[param_name] is not None:
                param_value = syscfg_parameters[param_name]
                overwritten = True
            else:
                param_value = sysdef_param_value
                overwritten = False
            parameter = parameters.Parameter(param_name, param_value, sysdef_param_value, overwritten)
            parameter_group.append(parameter)
        return parameter_group

    def __copy_system_files(self, sysref, dest_folder):
        """Copies the system files based on the system reference entry to the destination folder."""
        # create a new empty working directory for repository clone
        self._log.info("Creating working directory '%s'...", dest_folder)
        work_dir_obj = pathlib.Path(dest_folder)

        # check if the location string is pointing to a local file
        if sysref.type is system_db.LocationType.FILE and os.path.isfile(sysref.location):
            # copy sysdef to session folder as location string contains a local file path
            work_dir_obj.mkdir(parents=True)
            shutil.copyfile(sysref.location, work_dir_obj / "sysdef.json")
        elif sysref.type is system_db.LocationType.DIR and os.path.isdir(sysref.location):
            # location is a local directory -> copy full directory to session folder
            shutil.copytree(pathlib.Path(sysref.location), work_dir_obj)
        elif sysref.type is system_db.LocationType.GIT:
            # clone the associated repository into the session folder as location contains a git repo url
            work_dir_obj.mkdir(parents=True)
            self.__clone_repository(sysref.location, sysref.branch, dest_folder)
        elif sysref.type is system_db.LocationType.IMG:
            # system reference is a docker image -> extract sysdef from meta-data (labels)
            work_dir_obj.mkdir(parents=True)
            System.__extract_sysdef_from_image(sysref.location, sysref.branch, work_dir_obj)
        else:
            message = f"Location entry '{sysref.location}' is conflicting with type entry '{sysref.type}'!"
            self._log.error(message)
            raise AttributeError(message)

    def __parse_system_config(self, syscfg: dataformats.SysCfg, repo_clone_path: str):
        """Parses the system configuration file contents and clones the repository.

            Parameters:
                system_configuration (SysCfg): Contains deserialized content of the system configuration file.
                repo_clone_path (str): absolute path where system repository should be cloned to.

            Returns:
                Dataclass object of Configuration.
        """

        self._log.info("#### Parsing system configuration file ...")

        self.system_id = SystemIdentifier(name=syscfg.system.name, version=syscfg.system.version)

        # get system reference file for the selected system
        sysref = system_db.systems.get_system(self.system_id.name, self.system_id.version)

        # copy system files based on system reference entry to session folder
        self.__copy_system_files(sysref, repo_clone_path)

        # get system definition file from git repository
        sysdef: dataformats.SysDef = self.__get_system_definition(os.path.join(repo_clone_path, 'sysdef.json'))

        # parse content of system definition file
        if sysdef.name != self.system_id.name:
            message = f"System name '{self.system_id.name}' not matching in system definition file!"
            self._log.error(message)
            raise FileNotFoundError(message)
        if sysdef.version != self.system_id.version:
            message = f"System version '{self.system_id.version}' not matching in system definition file!"
            self._log.error(message)
            raise FileNotFoundError(message)

        if sysdef.build_command is not None:
            build_command = sysdef.build_command
            self.has_build = True
            # ignore empty build commands
            if len(build_command) == 0:
                build_command = None
                self.has_build = False
        else:
            build_command = None
            self.has_build = False

        # run command is mandatory
        if len(sysdef.run_command) == 0:
            message = "No 'run_command' specified in system definition file!"
            self._log.error(message)
            raise AttributeError(message)
        run_command = sysdef.run_command

        # append syscfg file path to commands (in perspective of container for SysAPI)
        build_command = f"{build_command} {self.syscfg_container_path}"
        run_command = f"{run_command} {self.syscfg_container_path}"
        if sysdef.delete_command is not None and len(sysdef.delete_command) > 0:
            delete_command = f"{sysdef.delete_command} {self.syscfg_container_path}"
        else:
            delete_command = None

        docker_image = sysdef.docker_image

        # save all system related data
        parameter_groups = {}
        parameter_groups[dataformats.ParameterGroup.COMMON] = self.__parse_parameter_group(
            sysdef.common_parameters, syscfg.common_parameters)
        parameter_groups[dataformats.ParameterGroup.BUILD] = self.__parse_parameter_group(
            sysdef.build_parameters, syscfg.build_parameters)
        parameter_groups[dataformats.ParameterGroup.RUN] = self.__parse_parameter_group(
            sysdef.run_parameters, syscfg.run_parameters)
        self.data = SystemData(parameters=parameter_groups, results=sysdef.results)

        # get all repo files for compute backend
        repo_files = []
        container_repo_path = os.path.join(constants.CONTAINER_WORKDIR, 'repository')
        for file in pathlib.Path(repo_clone_path).rglob('*'):
            repo_files.append(
                compute_if.ComputeFile(source_path=str(file),
                                       destination_path=os.path.join(
                                           container_repo_path,
                                           str(file.relative_to(repo_clone_path)))))
        # set compute backend to local docker daemon
        compute_data = compute_if.ComputeSystem(
            session_id=self.session_id, image=docker_image, mount_dir=constants.CONTAINER_WORKDIR,
            local_dir=os.path.join(constants.SESSIONS_BASE_DIR, self.session_id), work_dir=container_repo_path,
            build_command=build_command, run_command=run_command, delete_command=delete_command,
            # add all files from the locally cloned repo to the compute backend
            files=repo_files,
            requirements={}
        )

        self.compute_backend.create_resource(compute_data)

        self._log.info("Found following system: %s:%s", self.system_id.name, self.system_id.version)

        self._log.info("#### End of system configuration file parsing ...")

    def get_current_system_config(self) -> dataformats.SysCfg:
        """Returns the current system configuration of the provided session."""
        syscfg_parameters = {dataformats.ParameterGroup.COMMON: {},
                             dataformats.ParameterGroup.BUILD: {},
                             dataformats.ParameterGroup.RUN: {}}

        for group_name, parameter_group in self.data.parameters.items():
            for parameter in parameter_group:
                if parameter.file_data is not None and parameter.file_data.file_path_container is not None:
                    # if this is a file and the workspace path is already set then file is already available
                    # -> add path of workspace to command
                    self._log.debug("Adding file '%s' as parameter, which is already available in the workspace.",
                                    parameter.file_data.file_path_container)
                    syscfg_parameters[group_name][parameter.name] = parameter.file_data.file_path_container
                else:
                    # simple parameter -> just add to dict
                    syscfg_parameters[group_name][parameter.name] = parameter.value

        return dataformats.SysCfg(system=dataformats.SysCfgSystem(name=self.system_id.name,
                                                                  version=self.system_id.version),
                                  common_parameters=syscfg_parameters[dataformats.ParameterGroup.COMMON],
                                  build_parameters=syscfg_parameters[dataformats.ParameterGroup.BUILD],
                                  run_parameters=syscfg_parameters[dataformats.ParameterGroup.RUN])

    def get_parameter(self, parameter_group: dataformats.ParameterGroup | str,
                      parameter_name: str) -> parameters.Parameter | None:
        """Tries to return a parameter based on its name and parameter group.

            Parameters:
                parameter_name (str): Name of the parameter to be searched for.
                parameter_group (ParameterGroup): Name of the parameter group.

            Returns:
                The parameter object will be returned. Returns None if parameter was not found.
        """
        for parameter in self.data.parameters[parameter_group]:
            if parameter.name == parameter_name:
                return parameter
        return None

    def mark_file_parameters_available_for_build(self):
        """Marks all staged files as available for build parameters.

        This function should only be called if all files are
        successfully copied to the workspace of the compute backend.
        """
        for parameter in self.data.parameters[dataformats.ParameterGroup.BUILD]:
            parameter.mark_file_parameter_available()

    def mark_file_parameters_available_for_run(self):
        """Marks all staged files as available for run parameters.

        This function should only be called if all files are
        successfully copied to the workspace of the compute backend.
        """
        for parameter in self.data.parameters[dataformats.ParameterGroup.RUN]:
            parameter.mark_file_parameter_available()

    @staticmethod
    def get_system_definition(system_name: str, system_version: str) -> dataformats.SysDef:
        """Extracts the system definition file from the git repository of the system."""
        try:
            files_path = System.extract_files_from_system_repo(system_name, system_version, 'sysdef.json')
            with open(os.path.join(files_path, 'sysdef.json'), 'r', encoding='UTF-8') as sysdef_file:
                sysdef = dataformats.SysDef.model_validate_json(sysdef_file.read())
        except pydantic.ValidationError as exc:
            error_listing = "SysDef Validation Errors:\n"
            for err_inst in exc.errors():
                error_listing += f"\t{err_inst['loc']}: {err_inst['msg']}\n"
            System.log.error(error_listing)
            raise RuntimeError(error_listing) from exc
        finally:
            try:
                shutil.rmtree(files_path)
            # suppress exception raised by remove operation in case folder has not yet been created if an error
            # occurred before
            except (OSError, UnboundLocalError):
                pass
        return sysdef

    @staticmethod
    def __extract_sysdef_from_image(image_url, label_name, work_dir: pathlib.Path):
        """Extracts the sysdef from the label meta-data of the system docker image."""
        try:
            # initialize docker client
            client = docker.from_env()

            # If image is from remote: pull it
            if "/" in image_url:
                System.log.debug('Pulling docker image')
                client.images.pull(image_url)
            else:
                # using local available Docker image as image name does not contain a full URL
                System.log.debug('Using local docker image without container registry')

            image = client.images.get(image_url)
            # get labels from the image configuration
            labels = image.attrs['Config'].get('Labels', {})
            # label name with sysdef is stored in branch entry of system reference or use "SYSDEF" as default value
            if label_name is not None and len(label_name) > 0:
                sysdef_label = label_name
            else:
                sysdef_label = "SYSDEF"
            # extract sysdef label and decode all escape sequences (e.g. \n and \") to generate a valid json file
            if labels is None or sysdef_label not in labels:
                message = f"Cannot find label {sysdef_label} in docker image to extract SysDef!"
                System.log.error(message)
                raise AttributeError(message)
            sysdef = bytes(labels[sysdef_label], "utf-8").decode("unicode_escape").strip().strip('"')
            with open(work_dir / "sysdef.json", "w", encoding="utf-8") as sysdef_file:
                sysdef_file.write(sysdef)
        except docker.errors.ImageNotFound as exc:
            message = f"Error: Docker image '{image_url}' not found: {str(exc)}"
            System.log.error(message)
            raise AttributeError(message) from exc

    @staticmethod
    def extract_files_from_system_repo(system_name: str, system_version: str,
                                       files: os.PathLike | list[os.PathLike]) -> str:
        """Extracts the specified files from the system repository and returns the directory path to the files.

        The file parameter can contain a single path to a file or a list of file paths. This method check outs
        only the required files and does not clone the whole repository.
        """
        # get system reference file for the selected system
        sysref = system_db.systems.get_system(system_name, system_version)
        # temporary folder for repository clone
        tmp_repo = 'temprepo_' + str(uuid.uuid4())

        # check if sysdef location is a local file -> only sysdef.json itself can be extracted
        if sysref.type is system_db.LocationType.FILE and os.path.isfile(sysref.location):
            if not isinstance(files, list) and files == "sysdef.json":
                tmp_dir_obj = pathlib.Path(tmp_repo)
                tmp_dir_obj.mkdir(parents=True)
                shutil.copyfile(sysref.location, tmp_dir_obj / "sysdef.json")
                return tmp_repo
            message = f"Illegal operation: Cannot fetch files '{files}' from local sysdef path '{sysref.location}'!"
            System.log.error(message)
            raise RuntimeError(message)
        # check if sysref is a directory -> local file copy operation possible
        if sysref.type is system_db.LocationType.DIR and os.path.isdir(sysref.location):
            tmp_dir_obj = pathlib.Path(tmp_repo)
            tmp_dir_obj.mkdir(parents=True)
            if not isinstance(files, list):
                files = [files]
            for file in files:
                os.makedirs(os.path.dirname(tmp_dir_obj / file), exist_ok=True)
                shutil.copyfile(pathlib.Path(sysref.location) / file, tmp_dir_obj / file)
            return tmp_repo
        # check if sysref is a docker image -> only sysdef.json can be extracted from image label
        if sysref.type is system_db.LocationType.IMG:
            tmp_dir_obj = pathlib.Path(tmp_repo)
            tmp_dir_obj.mkdir(parents=True)
            System.__extract_sysdef_from_image(sysref.location, sysref.branch, tmp_dir_obj)
            if not isinstance(files, list) and files == "sysdef.json":
                return tmp_repo
            message = f"Illegal operation: Cannot fetch files '{files}' from docker image '{sysref.location}'!"
            System.log.error(message)
            raise RuntimeError(message)

        try:
            url = sysref.location
            branch = sysref.branch
            # set the git clone options to check out only the requested files
            git_clone_options = ["--depth 1", "--filter=blob:none", "--no-checkout"]
            # check if branch is a commit id -> no branch flag required
            commit_id_pattern = re.compile(r'^[0-9a-f]{40}$')
            if not bool(commit_id_pattern.match(branch)):
                git_clone_options.append(f"-b {branch}")
            repo = git.Repo.clone_from(url=url, to_path=tmp_repo, multi_options=git_clone_options)
            # iterate over requested files and enable sparse checkout for these files
            if isinstance(files, list):
                repo.git.execute(["git", "sparse-checkout", "set"] + files)
            else:
                repo.git.execute(["git", "sparse-checkout", "set", files])
            # checkout requested files to temporary folder
            repo.git.execute(["git", "checkout", branch])
            System.log.debug('Successfully retrieved files from git repository.')
        except git.GitCommandError as exc:
            message = f"Failed to fetch data from git repository '{sysref.location}': {str(exc)}"
            System.log.error(message)
            raise RuntimeError(message) from exc

        return tmp_repo

    @staticmethod
    def get_system_description(system_name: str, system_version: str) -> str:
        """Returns the system description as markdown-formatted string."""
        files_path = System.extract_files_from_system_repo(system_name, system_version, 'sysdef.json')
        with open(os.path.join(files_path, 'sysdef.json'), 'r', encoding='UTF-8') as sysdef_file:
            sysdef = dataformats.SysDef.model_validate_json(sysdef_file.read())
        shutil.rmtree(files_path)

        # return information if no documentation is available for the system
        if sysdef.documentation is None:
            return "No system documentation available."
        # check if full documentation is available, otherwise return only summary entry
        if sysdef.documentation.description is None or len(sysdef.documentation.description) == 0:
            return sysdef.documentation.summary

        try:
            files_path = System.extract_files_from_system_repo(system_name, system_version,
                                                               sysdef.documentation.description)
        except RuntimeError:
            # markdown file is not present -> just return the field content
            return sysdef.documentation.description

        markdown_path = os.path.join(files_path, sysdef.documentation.description)
        if os.path.isfile(markdown_path):
            with open(markdown_path, "r", encoding="UTF-8") as input_file:
                markdown_content = input_file.read()
            markdown_dir = os.path.dirname(sysdef.documentation.description)
            markdown_embedder = documentation.MarkdownImageEmbedder(markdown_content, markdown_dir)
            # add relative path of markdown file to all images paths to get valid images paths in perspective
            # of git repository root
            image_paths = []
            for image_path in markdown_embedder.extract_images_paths_from_markdown():
                image_paths.append(os.path.join(markdown_dir, image_path))
        else:
            return sysdef.documentation.description
        shutil.rmtree(files_path)

        files_path = System.extract_files_from_system_repo(system_name, system_version, image_paths)
        description_md = markdown_embedder.embed_images_in_markdown(files_path)
        shutil.rmtree(files_path)

        return description_md

    def __generate_syscfg_file(self) -> str:
        """Generates a syscfg.json file with the current system configuration used by the compute backend.

        Returns:
            syscfg file path (str): local file path to the generated syscfg file
        """
        syscfg: dataformats.SysCfg = self.get_current_system_config()
        destination_path = os.path.join(constants.SESSIONS_BASE_DIR, str(self.session_id), 'inputs')
        destination_file = os.path.join(destination_path, 'syscfg.json')
        if not os.path.isdir(destination_path):
            os.mkdir(destination_path)
        with open(destination_file, 'w', encoding='utf-8') as syscfg_file:
            syscfg_file.write(syscfg.model_dump_json())
        return destination_file

    def __get_file_copy_list(self, parameter_group: dataformats.ParameterGroup) -> list[compute_if.ComputeFile]:
        """Returns the list of file copy objects for staged files of a specific parameter group."""
        files: list[compute_if.ComputeFile] = []
        for parameter in self.data.parameters[parameter_group]:
            parameter.stage_file(self.session_id, parameter_group)
            if parameter.file_data is not None and parameter.file_data.file_state == parameters.FileState.STAGED:
                files.append(compute_if.ComputeFile(source_path=parameter.file_data.file_path_local,
                                                    destination_path=parameter.file_data.file_path_container))
        return files

    def execute(self, command: str, timeout: int = None, progress: compute_if.ComputeProgress = None) -> str:
        """Executes the build/run command for the system."""
        # syscfg file is always required for build and run command
        output: str = ""
        if command == 'build':
            # check if optional build command is available for the system
            if self.has_build:
                files = self.__get_file_copy_list(dataformats.ParameterGroup.COMMON)
                files += self.__get_file_copy_list(dataformats.ParameterGroup.BUILD)
                files.append(compute_if.ComputeFile(source_path=self.__generate_syscfg_file(),
                                                    destination_path=self.syscfg_container_path))
                output = self.compute_backend.build_system(files=files, timeout=timeout, progress=progress)
                self.mark_file_parameters_available_for_build()
        else:
            files = self.__get_file_copy_list(dataformats.ParameterGroup.COMMON)
            files += self.__get_file_copy_list(dataformats.ParameterGroup.RUN)
            files.append(compute_if.ComputeFile(source_path=self.__generate_syscfg_file(),
                                                destination_path=self.syscfg_container_path))
            output = self.compute_backend.run_system(files=files, timeout=timeout, progress=progress)
            self.mark_file_parameters_available_for_run()
        return output

    def stop(self):
        """Stops the compute backend if still running."""
        self.compute_backend.stop_command()

    def remove(self):
        """Removes all compute resources in the compute backend."""
        self.compute_backend.remove_resource()

    def get_result(self, path) -> os.PathLike:
        """Returns the result file as path."""
        return self.compute_backend.get_result(path)
