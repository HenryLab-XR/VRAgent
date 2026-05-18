# LLM-based Automated Testing with Dependency Analysis for VR Apps

This repository combines two parts:

- `TP_Generation`: Python tooling that analyzes a Unity project, extracts scene dependencies, and generates test plans.
- `VRAgent`: Unity-side runtime components that import and execute those plans in VR.

## Repository Layout

- [TP_Generation/README.md](TP_Generation/README.md): Python environment setup, dependency installation, and pipeline usage.
- [VRAgent/README.md](VRAgent/README.md): Unity-side package overview.
- `TP_Generation/UnityDataAnalyzer/`, `TP_Generation/CSharpScriptAnalyzer/`, `TP_Generation/CodeStructureAnalyzer/`: bundled analyzers used by the Python pipeline.

## Prerequisites

- Windows
- Unity 2021.3.x LTS for the Unity project
- Python `3.8.x` recommended for `TP_Generation`
- An OpenAI API key if you want to run the LLM-based plan generation stages

## New Machine Setup

After cloning on a new machine, set up the Python environment before running any `TP_Generation` script:

```powershell
cd <repo-root>
py -3.8 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python TP_Generation\check_env.py
```

That installs the Python dependencies recorded in version control and verifies that the bundled analyzers are present.

## End-to-End Workflow

1. Use `TP_Generation` to analyze the Unity project and produce scene metadata.
2. Generate or refine test plans from the extracted data.
3. Import the test plans into Unity through `VRAgent`.
4. Execute and iterate inside the target Unity scene.

## Dependency Management

The Python dependencies are now tracked in:

- `requirements.txt`: root convenience entry point
- `TP_Generation/requirements.txt`: runtime dependencies
- `TP_Generation/requirements-dev.txt`: runtime dependencies plus test-only tools

If a required package is missing, the main Python entry scripts now print an installation hint instead of only failing with a raw `ModuleNotFoundError`.

## Where To Read Next

- Python pipeline setup and commands: [TP_Generation/README.md](TP_Generation/README.md)
- Unity runtime usage: [VRAgent/README.md](VRAgent/README.md)
