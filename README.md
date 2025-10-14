# SUNRISE Demonstrator
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

This repository provides a minimal demonstration of the **SUNRISE** infrastructure.

**SUNRISE** stands for _**S**calable **Un**ified **R**ESTful **I**nfrastructure for **S**ystem **E**valuation_. It offers users a uniform approach to utilizing simulation technologies, typically, but not limited to the context of virtual prototyping.
The goal is to facilitate access to diverse simulation solutions and boost cooperation by leveraging decentralized compute resources and defining open APIs.

For more information, take a look at the [publications](#citing) listed below.

![SUNRISE components](doc/sunrise_overview.svg)


## Getting Started
### Repository Structure
This project provides a comprehensive setup for all typical components within the SUNRISE environment:
- The  [:file_folder: runtime_manager](runtime_manager/) subdirectory contains the implementation of a Server application that acts as SUNRISE Runtime Manager.
- The [:file_folder: user_interface](user_interface/) folder contains a demonstrator for a Front End in SUNRISE.
- In the [:file_folder: demo_system](demo_system/) directory, a very basic example of a system can be found.

### Running the Demonstrator
- :clipboard: **Prerequisites:**
  - A Linux operating system
  - The Docker runtime installed and running
  - Docker Compose to orchestrate everything (usually included with Docker Desktop)
- :hammer_and_wrench: **Preparation**
  - Configure the **ports** on which the servers will listen in the [.env-file](.env).
  - Configure the **Docker socket** that the Runtime Manager operates on in the [.env-file](.env). Hint: Call `docker context ls` from a UNIX shell to identify your current docker socket.
- :arrow_forward: **Execution Steps (from a UNIX Shell)**\
    First, build the Docker images:
    ```sh
    # Build the Docker images for all sub-components
    docker compose build
    ```

    To run the containers _interactively_:
    ```sh
    # Start the Docker containers with an interactive shell (Use CTRL-C to stop and exit)
    docker compose -p sunrise_demonstrator up

    # Remove the containers completely to clean up
    docker compose -p sunrise_demonstrator rm -f
    ```

    Alternatively, run the containers in the _background_:
    ```sh
    # Start the Docker containers in detached mode
    docker compose -p sunrise_demonstrator up -d

    # Check the logs of the containers that run in the background
    docker compose -p sunrise_demonstrator logs

    # Shut down the containers
    docker compose -p sunrise_demonstrator down
    ```
    _Note: Only the `runtime_manager` and `user_interface` services from the Docker Compose file are intended to run continuously. The `system` service will intentionally terminate directly. For the system, Docker Compose is only used to trigger the image build, which is then started later by the Runtime Manager._
- :globe_with_meridians: **Accessing the User Interface**\
  Once the containers are up and running, you can access the front-end through your web browser using the port you configured. The default address to access the UI is: **[http://localhost:9999](http://localhost:9999)**.


## Contributing
A core goal of SUNRISE is to connect parties in the industry to improve efficiency in the domain of simulation.
Therefore, we strongly encourage anyone interested to bring input to the project, preferably through code contributions.

Questions and requests can be raised via **GitHub issues**.
Please see the [contribution guide](CONTRIBUTING.md) for further information on how to get involved.


## License
This work is published under the [Apache License 2.0](LICENSE).


## Citing
Cite this work as defined in the included [citation file](CITATION.cff).

**Publications related to SUNRISE:**
- _Cloud-Enabled Virtual Prototypes_,  DVCon Europe 2025
- _Deployment of Containerized Simulations in an API-Driven Distributed Infrastructure_, DVCon Europe 2024,
https://doi.org/10.48550/arXiv.2506.10642
- _Scalable Software Testing in Fast Virtual Platforms: Leveraging SystemC, QEMU and Containerization_, DVCon China 2025, https://doi.org/10.48550/arXiv.2506.10624


## Acknowledgments
This work was initiated as a research project by [Robert Bosch GmbH](https://www.bosch.com/research/).
