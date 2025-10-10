# SUNRISE Data Formats
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

This folder provides common data types used in the **SUNRISE** framework.
The types are defined in Python using the [**Pydantic**](https://docs.pydantic.dev/latest/) library. Pydantic models describe content and format of data structures. They can be used for importing and exporting JSON files with an integrated validation check. Additionally, custom helper functions are added to the models, e.g. a check of the *enabled_by* reference of results in the SysDef or a method for conversion of a SysDef to a SysCfg file.


The minimal required Python version is 3.9.

## Content
The data formats are defined as Pydantic models in Python.
The following data formats are defined:

- **System Definition (SysDef)**: Specification of a *System* including exposed parameters, result objects and documentation
- **Experiment Handling**:
  - **System Configuration (SysCfg)**: Experiment configuration of a *System*
  - **Session Creation Data**: Data needed to create a new experiment
  - **Session Information**: State and logs of an experiment
- **Results Objects**: Definition of specific common result formats generated during the experiment.


## Usage Information
The data formats are used by the *Runtime Manager* and the *User Interface*. It can be integrated into any Python-based project to easily align the data formats with the *SUNRISE* framework:
- To use the Pydantic models, just import the *dataformats.py* file in your custom Python script.
- The import strategy requires that the parent directory of the submodule is in `PYTHONPATH` and the directory name is *dataformats*. This limitation comes from the need to type check objects of the included classes with `isinstance()` which requires objects to have the exact module path to pass a type comparison.

## Result Formats

| SysDef 'type' field                      | Description                                                      |
| ---------------------------------------- | ---------------------------------------------------------------- |
| binary                                   | Any custom binary file                                           |
| text                                     | Any custom text file                                             |
| vcd                                      | VCD trace file                                                   |
| fst                                      | FST trace file                                                   |
| [performance](#performance-json)         | SUNRISE Performance JSON file                                    |
| [simulation_speed](#performance-json)    | SUNRISE SimSpeed JSON file                                       |
| junit_xml                                | XML test results                                                 |
| gprof                                    | gprof profiling text file (with *flat profile* and *call graph*) |
| [profile_csv](#function-profiling-table) | SUNRISE Function Profile as CSV file                             |

SUNRISE uses standardized formats to enable result comparison between different systems.
Wherever possible, market standard solutions are used.
If there is no established format for a case, new definitions are made here.

### Function Profiling Table
For custom function profiling tools, it is recommended to save the result in this format.
The table uses one row per function and holds the profiling metrics in the columns.
The rows are not sorted by any column.

The **columns** are:
- *function*: Name of the function
- *address*: Address of the function in the memory (hexadecimal, leading *0x* will be truncated.)
- *count*: Number of calls of the function
- *percent*: Share of cycles spent in the function in relation to the total cycles
- *self_cycles*: Number of cycles spend in the functions itself (without sub-calls)
- *cumulative_cycles*: Overall number of cycles spend in the function including sub-calls


The overall **table** looks like this:
| function      | address  | count | percent | self_cycles | cumulative_cycles |
| ------------- | -------- | ----- | ------- | ----------- | ----------------- |
| some_function | 20001470 | 15    | 25.2    | 177         | 508               |
| another_func  | 20000630 | 1     | 44.0    | 167         | 885               |
| third_fn      | 2000052a | 4     | 59.1    | 59          | 1190              |

The table is stored as a **CSV file**, so the columns are separated with commas:
```csv
function,address,count,percent,self_cycles,cumulative_cycles
some_function,20001470,15,25.2,177,508
another_function,20000630,1,44.0,167,885
third_fn,2000052a,4,59.1,59,1190
```

### Performance JSON
A dictionary that is used to document performance metrics of a CPU.
Cycles and instructions are counts. Frequency is optional.
```json
{
  "cycles": 601607,
  "instructions": 342413,
  "frequency_hz": 1e+08
}
```
See pydantic class definition `Performance` in the [resultformats](resultformats.py) module.

### Simulation Speed JSON
A dictionary to enable comparing simulation speed by recording simulated time and execution (wall-clock) time in seconds as floating point number:
```json
{
  "simulated_time_sec": 0.0103042,
  "execution_time_sec": 0.154422
}
```
See pydantic class definition `SimSpeed` in the [resultformats](resultformats.py) module.
It also has a `get_rtf()` method, that calculates the real-time-factor from the values.