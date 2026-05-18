# TP_Generation

`TP_Generation` contains the Python-side pipeline for Unity scene analysis, dependency extraction, hierarchy traversal, and LLM-assisted test-plan generation.

## What This Folder Does

The pipeline is typically used in this order:

1. `ExtractSceneDependency.py`
2. `TraverseSceneHierarchy.py`
3. `SpecialLogicPreprocessor.py` or other preprocessing steps as needed
4. `GenerateTestPlanModified.py`

It also includes:

- bundled analyzer executables
- the `vragent2` Python package
- the Jelly dashboard server
- verification and test scripts

## Python Environment

Use a dedicated virtual environment on every machine. The project is currently recommended to run on Python `3.8.x` for consistency with the existing workflow.

### First-Time Setup On A New Machine

From the repository root:

```powershell
cd <repo-root>
py -3.8 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python TP_Generation\check_env.py
```

If you also want the test-only dependencies:

```powershell
python -m pip install -r TP_Generation\requirements-dev.txt
python TP_Generation\check_env.py --dev
```

### Daily Use

Each time you open a new terminal:

```powershell
cd <repo-root>
.\.venv\Scripts\activate
```

Check which interpreter is active:

```powershell
python -c "import sys; print(sys.executable)"
```

### Jelly GUI Paths

The Jelly GUI is designed to be portable across machines:

- Leave `Python Path` empty to use the Python interpreter that started Jelly, preferring the repo-local `.venv` when available.
- Leave `Work Dir` empty to use this `TP_Generation` folder.
- Use relative project paths when possible, for example `VRAgent` for the Unity project inside this repository.
- Supported path tokens in GUI config: `{repo}`, `{repo_root}`, `{tp_generation}`.
- Stale absolute paths from another machine are ignored at load time, so the GUI falls back to local defaults instead of launching an old drive path.

## Dependency Files

- `requirements.txt`: runtime dependencies used by the shipped scripts
- `requirements-dev.txt`: runtime dependencies plus `pytest`
- `check_env.py`: verifies Python version, required packages, and bundled analyzers

The main entry scripts now fail with a friendly installation message if a required package such as `networkx` is missing.

## Runtime Dependencies

The committed runtime dependency list currently includes:

- `networkx`
- `openai`
- `jsonschema`

Development-only extras:

- `pytest`

## External Analyzers

These analyzers are expected to exist inside this folder:

- `UnityDataAnalyzer/UnityDataAnalyzer.exe`
- `CSharpScriptAnalyzer/CSharpAnalyzer.exe`
- `CodeStructureAnalyzer/CodeStructureAnalyzer.exe`

Run the environment check to verify all three:

```powershell
python TP_Generation\check_env.py
```

## Configuration

Before running the LLM stages, review `config.py` and confirm:

- analyzer paths are correct
- API key or base URL configuration matches your environment
- prompt templates are the ones you want to use

## Typical Commands

Run from `TP_Generation`:

```powershell
cd <repo-root>\TP_Generation
python .\ExtractSceneDependency.py -p "<UnityProjectPath>" -r "<ResultsDir>"
python .\TraverseSceneHierarchy.py -r "<ResultsDir>"
python .\SpecialLogicPreprocessor.py -r "<ResultsDir>" -s "<SceneName>" -a "<AppName>"
python .\GenerateTestPlanModified.py -r "<ResultsDir>" -s "<SceneName>" -a "<AppName>"
```

If you only want to verify environment readiness before a handoff or machine migration:

```powershell
python .\check_env.py
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'networkx'`

Your Python environment has not installed the project dependencies yet.

```powershell
cd <repo-root>
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Then rerun:

```powershell
python TP_Generation\check_env.py
```

### Analyzer File Not Found

If `check_env.py` reports a missing analyzer executable, confirm that the corresponding folder is present in the repository checkout and that no file was excluded during copy or sync.

### Different Machines Use Different Python Interpreters

Prefer the repo-local `.venv` on every machine. `start_jelly.ps1` now looks for `.venv\Scripts\python.exe` before falling back to a machine-specific global Python path.
