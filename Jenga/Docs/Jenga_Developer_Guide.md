# Jenga Developer Guide

**Version 2.0.2**
**Complete Reference for Contributing to Jenga**

---

## Table of Contents

1. [Introduction](#introduction)
2. [Architecture Overview](#architecture-overview)
3. [Development Environment Setup](#development-environment-setup)
4. [Core System Components](#core-system-components)
5. [Builder System](#builder-system)
6. [Command System](#command-system)
7. [Cache and State Management](#cache-and-state-management)
8. [Variable Expansion Engine](#variable-expansion-engine)
9. [Dependency Resolution](#dependency-resolution)
10. [Toolchain Management](#toolchain-management)
11. [Adding New Builders](#adding-new-builders)
12. [Adding New Commands](#adding-new-commands)
13. [Testing the Build System](#testing-the-build-system)
14. [Code Style Guide](#code-style-guide)
15. [Contributing Guidelines](#contributing-guidelines)
16. [Release Process](#release-process)

---

## Introduction

### Purpose of this Guide

This Developer Guide is intended for developers who want to contribute to Jenga, extend its capabilities, or understand its internal architecture. If you're looking to **use** Jenga, please refer to the User Guide instead.

### Who Should Read This

- **Core Contributors**: Developers working on Jenga itself
- **Platform Maintainers**: Adding support for new platforms
- **Toolchain Developers**: Integrating new compilers or build tools
- **Advanced Users**: Understanding internals for debugging or optimization

### What You'll Learn

- Jenga's layered architecture and design patterns
- How the DSL is parsed and executed
- How builders compile and link code
- How caching and incremental builds work
- How to add new platforms, compilers, and commands
- Testing strategies and best practices
- Contributing workflow and code standards

---

## Architecture Overview

### High-Level Design

Jenga is structured as a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Layer (Jenga.py)                 │
│              Command-line interface and routing           │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  Commands Layer                          │
│   Build, Clean, Run, Test, Info, Gen, Package, etc.    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Core Layer                             │
│  ┌───────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │  Api.py       │  │  Loader.py  │  │  Builder.py  │  │
│  │  (DSL)        │  │  (Parser)   │  │  (Abstract)  │  │
│  └───────────────┘  └─────────────┘  └──────────────┘  │
│  ┌───────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │  Cache.py     │  │  State.py   │  │Dependency    │  │
│  │  (SQLite)     │  │  (Runtime)  │  │Resolver.py   │  │
│  └───────────────┘  └─────────────┘  └──────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │           Builders/ (Platform-specific)            │  │
│  │  Windows.py │ Linux.py │ Android.py │ Zig.py ...  │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 Utils Layer                              │
│  Colored, Display, FileSystem, Process, Reporter        │
└─────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Layer | Components | Responsibility |
|-------|------------|----------------|
| **CLI** | `Jenga.py` | Parse command-line arguments, route to commands |
| **Commands** | `Build.py`, `Run.py`, `Test.py`, etc. | High-level user operations |
| **Core** | `Api.py`, `Loader.py`, `Builder.py`, etc. | Workspace parsing, build orchestration |
| **Utils** | `Process.py`, `FileSystem.py`, etc. | Cross-platform utilities |

### Data Flow

```
.jenga file → Loader → Workspace object → DependencyResolver → Builder
     ↓                      ↓                    ↓                  ↓
  Python DSL          Exec globals         Build order      Compile/Link
     ↓                      ↓                    ↓                  ↓
  exec()            Api functions         Topological     Platform-specific
                    build objects            sort           commands
```

### Design Patterns Used

1. **Abstract Factory Pattern**: Builder classes (`Builder` → `WindowsBuilder`, `LinuxBuilder`, etc.)
2. **Strategy Pattern**: Platform-specific compilation/linking strategies
3. **Context Manager Pattern**: DSL scoping (`workspace()`, `project()`, `filter()`)
4. **Registry Pattern**: Command and builder registration
5. **Singleton Pattern**: Global state management (`_currentWorkspace`, `_currentProject`)
6. **Observer Pattern**: Build state tracking and reporting
7. **Lazy Loading Pattern**: Builders and toolchains loaded on demand
8. **Caching Pattern**: SQLite-backed persistent cache

---

## Development Environment Setup

### Prerequisites

- **Python 3.8+**
- **Git**
- **Multiple compilers** for testing (MSVC, GCC, Clang)
- **Platform-specific SDKs** (optional, for testing):
  - Android NDK
  - Emscripten SDK
  - Zig compiler

### Clone Repository

```bash
git clone https://github.com/Rihen-Universe/Jenga.git
cd Jenga
```

### Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### Install Development Dependencies

```bash
pip install -e .  # Editable install
pip install pytest pytest-cov black mypy pylint
```

### Development Tools

#### Code Formatting (Black)

```bash
black Jenga/
```

#### Type Checking (MyPy)

```bash
mypy Jenga/
```

#### Linting (Pylint)

```bash
pylint Jenga/
```

#### Running Tests

```bash
pytest tests/ -v
pytest tests/ --cov=Jenga --cov-report=html
```

### Directory Structure

```
Jenga/
├── Jenga/                    # Main package
│   ├── __init__.py           # Package exports
│   ├── Jenga.py             # CLI entry point
│   ├── Core/                 # Core build engine
│   │   ├── Api.py            # DSL and data model
│   │   ├── Loader.py         # Workspace loader
│   │   ├── Builder.py        # Abstract builder
│   │   ├── Builders/         # Platform-specific builders
│   │   ├── Cache.py          # Persistent cache
│   │   ├── State.py          # Build state
│   │   ├── DependencyResolver.py
│   │   ├── Toolchains.py     # Toolchain detection
│   │   ├── Platform.py       # Platform detection
│   │   └── Variables.py      # Variable expansion
│   ├── Commands/             # CLI commands
│   │   ├── Build.py
│   │   ├── Run.py
│   │   ├── Test.py
│   │   └── ...
│   ├── Utils/                # Utilities
│   │   ├── Colored.py
│   │   ├── Display.py
│   │   ├── FileSystem.py
│   │   ├── Process.py
│   │   └── Reporter.py
│   └── Unitest/              # Testing framework
├── Exemples/                 # Example projects
├── tests/                    # Unit tests
├── docs/                     # Documentation
├── scripts/                  # Utility scripts
├── setup.py                  # Package setup
├── pyproject.toml            # Modern Python packaging
└── README.md                 # Project overview
```

---

## Core System Components

### Api.py - DSL and Data Model

**Location:** `Jenga/Core/Api.py` (~2900 lines)

**Purpose:** Defines the Python DSL (Domain-Specific Language) and core data structures.

#### Key Components

##### 1. Enums

```python
class ProjectKind(Enum):
    CONSOLE_APP = "ConsoleApp"
    WINDOWED_APP = "WindowedApp"
    STATIC_LIB = "StaticLib"
    SHARED_LIB = "SharedLib"
    TEST_SUITE = "TestSuite"
```

All enums use UPPER_SNAKE_CASE for values and string representation.

##### 2. Dataclasses

**Workspace:**
```python
@dataclass
class Workspace:
    name: str
    location: str
    configurations: List[str]
    targetOses: List[TargetOS]
    targetArchs: List[TargetArch]
    projects: Dict[str, Project] = field(default_factory=dict)
    toolchains: Dict[str, Toolchain] = field(default_factory=dict)
    # ... many more fields
```

**Project:**
```python
@dataclass
class Project:
    name: str
    kind: Optional[ProjectKind] = None
    language: Optional[Language] = None
    cppdialect: str = ""
    files: List[str] = field(default_factory=list)
    includeDirs: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    # ... 50+ fields for complete configuration
```

**Design Notes:**
- Use `field(default_factory=list)` for mutable defaults
- All paths stored as strings (not Path objects) for JSON serialization
- Metadata fields prefixed with `_` (e.g., `_external`, `_inWorkspace`)

##### 3. Context Managers

```python
class workspace:
    def __init__(self, name: str, location: str = ""):
        self.name = name
        self.location = location or os.getcwd()
        self._workspace = None

    def __enter__(self):
        global _currentWorkspace
        self._workspace = Workspace(
            name=self.name,
            location=self.location,
            configurations=[],
            targetOses=[],
            targetArchs=[],
        )
        _currentWorkspace = self._workspace
        return self._workspace

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Workspace is preserved in global state
        return False
```

**Key Pattern:** Context managers manage global state (`_currentWorkspace`, `_currentProject`, `_currentToolchain`).

##### 4. DSL Functions

All DSL functions are lowercase and modify global state:

```python
def configurations(names: List[str]):
    """Set build configurations for workspace."""
    global _currentWorkspace
    if not _currentWorkspace:
        raise RuntimeError("configurations() must be inside workspace context")
    _currentWorkspace.configurations = names
```

**Function Naming Convention:**
- Lowercase for user-facing DSL functions
- PascalCase for internal/private methods (prefixed with `_`)

#### Global State Management

```python
# Global state variables
_currentWorkspace: Optional[Workspace] = None
_currentProject: Optional[Project] = None
_currentToolchain: Optional[Toolchain] = None
_currentFilter: Optional[str] = None
_toolsManager: ExternalToolsManager = None
```

**Thread Safety:** Not thread-safe by design - .jenga files execute sequentially in single thread.

#### Adding New DSL Functions

**Example:** Adding a new project setting

```python
def mynewoption(value: str):
    """Set my new option for current project."""
    global _currentProject
    if not _currentProject:
        raise RuntimeError("mynewoption() must be inside project context")
    _currentProject.myNewOption = value
```

**Steps:**
1. Add field to `Project` dataclass
2. Create lowercase DSL function
3. Add to `__all__` export list
4. Update `Jenga/__init__.py` exports
5. Add documentation
6. Add tests

---

### Loader.py - Workspace Parser

**Location:** `Jenga/Core/Loader.py`

**Purpose:** Loads and executes .jenga files, building Workspace objects.

#### Key Methods

##### LoadWorkspace(entryFile)

```python
def LoadWorkspace(self, entryFile: str) -> Optional[Workspace]:
    """Load workspace from root .jenga file."""
    entryPath = Path(entryFile).resolve()
    if not entryPath.exists():
        return None

    # Change to workspace directory during execution
    originalCwd = os.getcwd()
    os.chdir(entryPath.parent)

    try:
        # Prepare execution globals
        exec_globals = self._PrepareGlobals(entryPath)

        # Execute .jenga file
        with open(entryPath, 'r', encoding='utf-8') as f:
            exec(f.read(), exec_globals)

        # Get workspace from global state
        workspace = Api.getcurrentworkspace()
        if not workspace:
            return None

        # Post-processing
        self._PostProcessWorkspace(workspace, entryPath)

        return workspace

    finally:
        os.chdir(originalCwd)
```

**Design Notes:**
- Changes directory to workspace root during execution
- Uses `exec()` to execute Python DSL code
- Restores directory after execution
- Post-processes workspace (variable expansion, path resolution)

##### _PrepareGlobals(filePath)

```python
def _PrepareGlobals(self, filePath: Path, parentWorkspace=None, isInclude=False) -> dict:
    """Prepare execution globals for .jenga file."""
    exec_globals = {
        '__file__': str(filePath),
        '__name__': '__jenga__',
        'Path': Path,
        'os': os,
        'sys': sys,
    }

    # Import all API functions
    import Jenga
    for name in dir(Jenga):
        if not name.startswith('_'):
            exec_globals[name] = getattr(Jenga, name)

    return exec_globals
```

**What Gets Injected:**
- All DSL functions from `Jenga/__init__.py`
- Standard library modules (`os`, `sys`, `Path`)
- File metadata (`__file__`, `__name__`)

##### _PostProcessWorkspace(workspace, entryFile)

```python
def _PostProcessWorkspace(self, workspace, entryFile: Path):
    """Apply post-load transformations."""
    # 1. Set default objDir and targetDir
    for project in workspace.projects.values():
        if not project.objDir:
            project.objDir = f"Build/Obj/{project.name}"
        if not project.targetDir:
            project.targetDir = "Build/Bin"

    # 2. Expand variables
    expander = self._CreateExpanderForWorkspace(workspace)
    for project in workspace.projects.values():
        project.objDir = expander.Expand(project.objDir)
        project.targetDir = expander.Expand(project.targetDir)
        # ... expand all path fields

    # 3. Resolve relative paths to absolute
    for project in workspace.projects.values():
        if not Path(project.objDir).is_absolute():
            project.objDir = str((Path(workspace.location) / project.objDir).resolve())
        # ... resolve all paths
```

**Post-Processing Steps:**
1. Set default values for unspecified fields
2. Expand `%{...}` variables
3. Resolve relative paths to absolute
4. Resolve toolchain paths

#### Incremental Loading

```python
def LoadExternalFile(self, filePath: str, parentWorkspace) -> Tuple[Any, Dict]:
    """Load external .jenga file (for includes)."""
    # Create temporary workspace for external file
    # Execute file
    # Return workspace and metadata (timestamp, file hash)
    pass
```

Used by cache system to detect changes in included files.

---

### Builder.py - Abstract Builder

**Location:** `Jenga/Core/Builder.py`

**Purpose:** Abstract base class for all platform-specific builders.

#### Class Hierarchy

```
Builder (abstract)
├── WindowsBuilder
├── LinuxBuilder
├── MacOSBuilder
├── AndroidBuilder
├── IOSBuilder
├── EmscriptenBuilder
├── ZigBuilder
└── ...
```

#### Abstract Methods

```python
class Builder(abc.ABC):
    @abc.abstractmethod
    def Compile(self, project, sourceFile, objectFile) -> bool:
        """Compile single source file to object file."""
        pass

    @abc.abstractmethod
    def Link(self, project, objectFiles, outputFile) -> bool:
        """Link object files to final binary."""
        pass

    @abc.abstractmethod
    def GetOutputExtension(self, project) -> str:
        """Get platform-specific output extension (.exe, .so, etc.)."""
        pass

    @abc.abstractmethod
    def GetObjectExtension(self) -> str:
        """Get object file extension (.obj, .o)."""
        pass
```

#### Common Infrastructure

##### Build Orchestration

```python
def BuildProject(self, project) -> bool:
    """Main build orchestration for single project."""
    logger = BuildLogger(project.name)

    # 1. Collect source files
    sourceFiles = self._CollectSourceFiles(project)
    logger.SetTotal(len(sourceFiles))

    # 2. Prepare PCH if needed
    objDir = self.GetObjectDir(project)
    if project.pchHeader:
        if not self.PreparePCH(project, objDir):
            return False

    # 3. Precompile C++20 modules if needed
    moduleFiles = [f for f in sourceFiles if self.IsModuleFile(f)]
    if moduleFiles:
        if not self._PrecompileModules(project, moduleFiles, objDir):
            return False

    # 4. Compile source files
    objectFiles = []
    for srcFile in sourceFiles:
        objFile = self._GetObjectFilePath(srcFile, objDir)
        if self.Compile(project, srcFile, objFile):
            logger.LogCompile(srcFile, self._lastResult)
            objectFiles.append(objFile)
        else:
            logger.LogCompile(srcFile, self._lastResult)
            return False

    # 5. Link
    outputFile = self.GetTargetPath(project)
    if self.Link(project, objectFiles, outputFile):
        logger.LogLink(outputFile, self._lastResult)
    else:
        logger.LogLink(outputFile, self._lastResult)
        return False

    # 6. Print statistics
    logger.PrintStats()
    return True
```

**Key Responsibilities:**
- Collect source files matching patterns
- Precompiled header preparation
- C++20 module precompilation (BMI generation)
- Source-to-object compilation
- Object-to-binary linking
- Build statistics reporting

##### C++20 Module Support

```python
def _PrecompileModules(self, project, moduleFiles, objDir) -> bool:
    """Precompile C++20 modules to BMI (Binary Module Interface)."""
    for moduleFile in moduleFiles:
        moduleName = self._ExtractModuleName(moduleFile)
        bmiFile = objDir / f"{moduleName}.ifc"  # or .pcm for Clang

        # Compile module interface to BMI
        if not self._CompileModuleToBMI(project, moduleFile, bmiFile):
            return False

    return True

def _ExtractModuleName(self, moduleFile: str) -> str:
    """Extract module name from module interface file."""
    with open(moduleFile, 'r') as f:
        for line in f:
            match = re.search(r'export\s+module\s+([\w.]+)', line)
            if match:
                return match.group(1)
    return Path(moduleFile).stem
```

**Module File Detection:**
- Extensions: `.cppm`, `.ixx`, `.mpp`, `.c++m`
- Pattern: `export module module_name;`

##### Dependency Resolution

```python
def Build(self, targetProject: Optional[str] = None) -> int:
    """Build workspace or specific project."""
    # 1. Resolve build order
    from .DependencyResolver import DependencyResolver
    buildOrder = DependencyResolver.ResolveBuildOrder(
        self.workspace, targetProject
    )

    # 2. Build projects in order
    for projectName in buildOrder:
        project = self.workspace.projects[projectName]
        if not self.BuildProject(project):
            return 1

    return 0
```

Uses topological sort to build dependencies before dependents.

---

### Cache.py - Persistent Build Cache

**Location:** `Jenga/Core/Cache.py`

**Purpose:** SQLite-based persistent cache for workspace and file metadata.

#### Database Schema

```sql
CREATE TABLE workspace (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
);

CREATE TABLE files (
    path TEXT PRIMARY KEY,
    mtime REAL,
    hash TEXT,
    last_loaded REAL
);

CREATE TABLE projects (
    name TEXT PRIMARY KEY,
    source_file TEXT,
    project_json TEXT,
    updated_at REAL
);

CREATE TABLE toolchains (
    name TEXT PRIMARY KEY,
    source_file TEXT,
    toolchain_json TEXT,
    updated_at REAL
);

CREATE TABLE metadata (
    version TEXT,
    workspace_root TEXT,
    workspace_name TEXT,
    cache_version INTEGER,
    created_at REAL,
    updated_at REAL
);
```

#### Key Operations

##### Save Workspace

```python
def SaveWorkspace(self, workspace, entryFile, loader):
    """Save complete workspace to cache."""
    conn = self._GetConnection()
    try:
        # 1. Serialize workspace to JSON
        workspaceJson = self._SerializeWorkspace(workspace)

        # 2. Store workspace
        conn.execute("""
            INSERT OR REPLACE INTO workspace (key, value, updated_at)
            VALUES (?, ?, ?)
        """, ('workspace', workspaceJson, time.time()))

        # 3. Store file metadata for all .jenga files
        jengaFiles = self._GetAllJengaFiles()
        for filePath in jengaFiles:
            mtime, fileHash = self._GetFileMetadata(filePath)
            conn.execute("""
                INSERT OR REPLACE INTO files (path, mtime, hash, last_loaded)
                VALUES (?, ?, ?, ?)
            """, (str(filePath), mtime, fileHash, time.time()))

        # 4. Store individual projects
        for project in workspace.projects.values():
            projectJson = json.dumps(project, default=self._SerializeObject)
            conn.execute("""
                INSERT OR REPLACE INTO projects
                (name, source_file, project_json, updated_at)
                VALUES (?, ?, ?, ?)
            """, (project.name, entryFile, projectJson, time.time()))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise
```

##### Load Workspace with Incremental Detection

```python
def LoadWorkspace(self, entryFile, loader) -> Optional[Workspace]:
    """Load cached workspace, detecting changes."""
    conn = self._GetConnection()

    # 1. Check if entry file changed
    cachedMtime, cachedHash = self._GetCachedFileMetadata(entryFile)
    currentMtime, currentHash = self._GetFileMetadata(entryFile)

    if cachedHash != currentHash:
        # Entry file changed - full reload needed
        return None

    # 2. Check included files
    jengaFiles = self._GetAllJengaFiles()
    for filePath in jengaFiles:
        cached = self._GetCachedFileMetadata(filePath)
        current = self._GetFileMetadata(filePath)
        if cached != current:
            # Incremental reload for changed file
            workspace = self._LoadWorkspaceFromCache()
            self._ReloadChangedFile(workspace, filePath, loader)
            return workspace

    # 3. No changes - load from cache
    return self._LoadWorkspaceFromCache()
```

**Incremental Loading Strategy:**
- Entry file changed → Full reload
- Included file changed → Reload only that file
- No changes → Load from cache (fast!)

##### Serialization

```python
def _SerializeWorkspace(self, workspace) -> str:
    """Convert Workspace to JSON."""
    def default(obj):
        if isinstance(obj, Enum):
            return {'__enum__': type(obj).__name__, 'value': obj.value}
        elif hasattr(obj, '__dict__'):
            return {'__class__': type(obj).__name__, **obj.__dict__}
        return str(obj)

    return json.dumps(workspace, default=default, indent=2)

def _DeserializeWorkspace(self, data: str) -> Workspace:
    """Reconstruct Workspace from JSON."""
    def object_hook(d):
        if '__enum__' in d:
            # Reconstruct enum
            enumClass = getattr(Api, d['__enum__'])
            return enumClass(d['value'])
        elif '__class__' in d:
            # Reconstruct dataclass
            className = d.pop('__class__')
            if className == 'Workspace':
                return self._WorkspaceFromDict(d)
            elif className == 'Project':
                return self._ProjectFromDict(d)
            # ... etc
        return d

    return json.loads(data, object_hook=object_hook)
```

**Design Notes:**
- Type markers (`__enum__`, `__class__`) for reconstruction
- Enums serialized as `{type, value}` pairs
- Dataclasses converted to dicts with metadata

---

### State.py - Build State Tracking

**Location:** `Jenga/Core/State.py`

**Purpose:** Track build state during single build execution.

#### BuildState Class

```python
@dataclass
class FileState:
    """Per-file state tracking."""
    hash: str
    mtime: float
    timestamp: float

class BuildState:
    """Mutable build state for single build."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.workspaceName = workspace.name
        self.compiledProjects: Set[str] = set()
        self.failedProjects: Set[str] = set()
        self.startTime = time.time()
        self.endTime: Optional[float] = None

        # File tracking
        self._fileStates: Dict[str, FileState] = {}

        # Dependency tracking
        self._projectDeps: Dict[str, Set[str]] = {}  # project -> headers

        # Output tracking
        self._projectOutputs: Dict[str, List[str]] = {}  # project -> outputs
```

#### Key Methods

```python
def MarkProjectCompiled(self, projectName: str, success: bool):
    """Mark project as compiled (success or failure)."""
    if success:
        self.compiledProjects.add(projectName)
    else:
        self.failedProjects.add(projectName)

def IsProjectCompiled(self, projectName: str) -> bool:
    """Check if project already compiled this build."""
    return projectName in self.compiledProjects

def HasFileChanged(self, filepath: str, currentHash: str, currentMtime: float) -> bool:
    """Detect if file changed since last build."""
    state = self._fileStates.get(filepath)
    if not state:
        return True  # New file
    return state.hash != currentHash or state.mtime != currentMtime
```

**Usage in Builder:**
```python
def BuildProject(self, project) -> bool:
    # Check if already built
    if self.state.IsProjectCompiled(project.name):
        return True

    # Build project...

    # Mark as compiled
    self.state.MarkProjectCompiled(project.name, success=True)
```

---

### DependencyResolver.py - Build Order Resolution

**Location:** `Jenga/Core/DependencyResolver.py`

**Purpose:** Resolve project dependencies and determine build order.

#### Topological Sort Implementation

```python
class DependencyResolver:
    @staticmethod
    def ResolveBuildOrder(workspace, targetProject=None) -> List[str]:
        """
        Resolve build order using Kahn's algorithm.

        Returns: List of project names in build order (dependencies first)
        Raises: RuntimeError if circular dependency detected
        """
        # 1. Build dependency graph
        graph = {}  # project -> list of dependencies
        inDegree = {}  # project -> number of dependencies

        for name, project in workspace.projects.items():
            graph[name] = list(project.dependsOn)
            inDegree[name] = len(project.dependsOn)

        # 2. If target specified, filter to relevant subgraph
        if targetProject:
            relevant = DependencyResolver._GetRelevantProjects(
                targetProject, graph
            )
            graph = {k: v for k, v in graph.items() if k in relevant}
            inDegree = {k: v for k, v in inDegree.items() if k in relevant}

        # 3. Kahn's algorithm
        queue = [name for name, degree in inDegree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            # Decrease in-degree for dependents
            for name in graph:
                if current in graph[name]:
                    inDegree[name] -= 1
                    if inDegree[name] == 0:
                        queue.append(name)

        # 4. Check for cycles
        if len(result) != len(graph):
            cycles = DependencyResolver._FindCycles(graph)
            raise RuntimeError(f"Circular dependency detected: {cycles}")

        return result
```

**Kahn's Algorithm Steps:**
1. Count in-degree (number of dependencies) for each node
2. Start with nodes having in-degree 0 (no dependencies)
3. Remove nodes one by one, decreasing in-degree of dependents
4. If all nodes removed → success; otherwise → cycle detected

#### Cycle Detection

```python
@staticmethod
def _FindCycles(graph) -> List[List[str]]:
    """Find all cycles in dependency graph using DFS."""
    cycles = []
    visited = set()
    recStack = set()

    def dfs(node, path):
        visited.add(node)
        recStack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path[:])
            elif neighbor in recStack:
                # Cycle found
                cycleStart = path.index(neighbor)
                cycles.append(path[cycleStart:] + [neighbor])

        recStack.remove(node)

    for node in graph:
        if node not in visited:
            dfs(node, [])

    return cycles
```

---

### Variables.py - Variable Expansion Engine

**Location:** `Jenga/Core/Variables.py`

**Purpose:** Expand `%{...}` variables in strings.

#### VariableExpander Class

```python
class VariableExpander:
    def __init__(self, workspace, project, config, unitestConfig,
                 testProject, baseDir, jengaRoot):
        self._workspace = workspace
        self._project = project
        self._config = config  # Dict[str, str]
        self._unitestConfig = unitestConfig
        self._testProject = testProject
        self._baseDir = Path(baseDir)
        self._jengaRoot = Path(jengaRoot)
        self._toolchain = None
        self._projectCache = {}  # Cache for project lookups
```

#### Expansion Algorithm

```python
def Expand(self, template: str, recursive: bool = False) -> str:
    """
    Expand %{namespace.property} variables.

    Examples:
        %{wks.name} → "MyWorkspace"
        %{prj.location} → "/path/to/project"
        %{cfg.buildcfg} → "Debug"
    """
    if not template:
        return template

    pattern = r'%\{([^}]+)\}'

    def replacer(match):
        var = match.group(1)

        # 1. Try namespace resolution
        if '.' in var:
            namespace, property = var.split('.', 1)

            if namespace in ('wks', 'workspace'):
                return self._GetWorkspaceVariable(property)
            elif namespace in ('prj', 'project'):
                return self._GetProjectVariable(self._project, property)
            elif namespace == 'cfg':
                return self._config.get(property, '')
            elif namespace == 'unitest':
                return self._GetUnitestVariable(property)
            elif namespace == 'env':
                return os.getenv(property, '')
            elif namespace == 'Jenga':
                return self._GetJengaVariable(property)
            else:
                # Try as project name
                return self._GetNamedProjectVariable(namespace, property)

        # 2. Try implicit resolution (no namespace)
        return self._GetImplicitVariable(var)

    result = re.sub(pattern, replacer, template)

    # Recursive expansion if needed
    if recursive and '%{' in result:
        return self.Expand(result, recursive=True)

    return result
```

#### Variable Resolution

```python
def _GetWorkspaceVariable(self, var: str) -> str:
    """Resolve workspace.* variables."""
    if var == 'name':
        return self._workspace.name
    elif var == 'location':
        return self._workspace.location
    elif var == 'configurations':
        return ','.join(self._workspace.configurations)
    # ... etc
    return ''

def _GetProjectVariable(self, project, var: str) -> str:
    """Resolve project.* variables."""
    if var == 'name':
        return project.name
    elif var == 'location':
        return project.location
    elif var == 'objdir':
        return project.objDir
    elif var == 'targetdir':
        return project.targetDir
    # ... etc
    return ''

def _GetJengaVariable(self, var: str) -> str:
    """Resolve Jenga.* system variables."""
    if var == 'Root':
        return str(self._jengaRoot)
    elif var == 'Version':
        return '2.0.2'
    elif var == 'Unitest.Include':
        return str(self._jengaRoot / 'Jenga' / 'Unitest' / 'src' / 'Unitest')
    # ... etc
    return ''
```

**Supported Namespaces:**
- `wks.` / `workspace.` - Workspace properties
- `prj.` / `project.` - Project properties
- `cfg.` - Configuration properties
- `unitest.` - Unitest configuration
- `test.` - Test project
- `env.` - Environment variables
- `Jenga.` - Jenga system variables
- `<ProjectName>.` - Named project properties

---

## Builder System

### Builder Architecture

The builder system uses the **Abstract Factory Pattern** to support multiple platforms with a common interface.

```
Builder (ABC)
    │
    ├── Core Methods (implemented in base)
    │   ├── Build(targetProject) → Build workspace
    │   ├── BuildProject(project) → Build single project
    │   ├── GetObjectDir(project) → Resolve object directory
    │   ├── GetTargetPath(project) → Resolve output path
    │   └── _CollectSourceFiles(project) → Gather sources
    │
    ├── Abstract Methods (must override)
    │   ├── Compile(project, src, obj) → Platform-specific
    │   ├── Link(project, objs, out) → Platform-specific
    │   ├── GetOutputExtension(project) → .exe, .so, .dll, etc.
    │   ├── GetObjectExtension() → .obj or .o
    │   └── GetModuleFlags(project, src) → C++20 module flags
    │
    └── Optional Overrides
        └── PreparePCH(project, objDir) → PCH preparation
```

### WindowsBuilder Deep Dive

**Location:** `Jenga/Core/Builders/Windows.py`

#### Compiler Detection

```python
class WindowsBuilder(Builder):
    def __init__(self, workspace, config, platform, targetOs, targetArch, targetEnv, verbose):
        super().__init__(workspace, config, platform, targetOs, targetArch, targetEnv, verbose)

        # Detect compiler family
        if self.toolchain:
            family = self.toolchain.compilerFamily
            self.is_msvc = (family == CompilerFamily.MSVC)
            self.is_clang = (family == CompilerFamily.CLANG and not self._IsClangCl())
            self.is_mingw = (family == CompilerFamily.GCC or
                           (family == CompilerFamily.CLANG and not self._IsClangCl()))
            self.is_clang_cl = self._IsClangCl()
        else:
            # Auto-detect
            self.is_msvc = self._HasMSVC()
            self.is_clang_cl = self._HasClangCl()
            self.is_clang = self._HasClang() and not self.is_clang_cl
            self.is_mingw = self._HasMinGW()

    def _IsClangCl(self) -> bool:
        """Check if using clang-cl (MSVC-compatible mode)."""
        if self.toolchain and self.toolchain.cxxPath:
            return 'clang-cl' in self.toolchain.cxxPath.lower()
        return False
```

**Compiler Priority:**
1. MSVC (cl.exe)
2. Clang-CL (MSVC-compatible Clang)
3. Clang (Unix-style)
4. MinGW (GCC on Windows)

#### MSVC Compilation

```python
def _CompileMSVC(self, project, sourceFile, objectFile) -> bool:
    """Compile with MSVC cl.exe."""
    args = [self.toolchain.cxxPath or "cl.exe"]

    # Compilation mode
    args.append("/c")  # Compile only
    args.append("/nologo")  # Suppress banner
    args.append(f"/Fo{objectFile}")  # Output file

    # Include directories
    for incDir in project.includeDirs:
        args.append(f"/I{incDir}")

    # Defines
    for define in project.defines:
        args.append(f"/D{define}")

    # C++ standard
    if project.cppdialect:
        stdMap = {
            "C++14": "/std:c++14",
            "C++17": "/std:c++17",
            "C++20": "/std:c++20",
            "C++23": "/std:c++latest",
        }
        args.append(stdMap.get(project.cppdialect, "/std:c++17"))

    # Optimization
    if project.optimize == Optimization.OFF:
        args.append("/Od")
    elif project.optimize == Optimization.SIZE:
        args.append("/O1")
    elif project.optimize == Optimization.SPEED:
        args.append("/O2")
    elif project.optimize == Optimization.FULL:
        args.append("/Ox")

    # Debug symbols
    if project.symbols:
        args.append("/Zi")
        args.append("/DEBUG")

    # Warnings
    if project.warnings == WarningLevel.DEFAULT:
        args.append("/W3")
    elif project.warnings in (WarningLevel.ALL, WarningLevel.EXTRA):
        args.append("/W4")
    elif project.warnings == WarningLevel.ERROR:
        args.append("/WX")

    # PCH
    if project.pchHeader:
        args.append(f"/Yu{project.pchHeader}")
        args.append(f"/Fp{self.GetObjectDir(project)}/{project.pchHeader}.pch")

    # Source file
    args.append(sourceFile)

    # Execute
    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

**MSVC Flag Mapping:**
- Optimization: `/Od` (off), `/O1` (size), `/O2` (speed), `/Ox` (max)
- Debug: `/Zi` (debug info), `/DEBUG` (linker debug)
- Warnings: `/W3` (default), `/W4` (high), `/WX` (errors)
- Standard: `/std:c++14`, `/std:c++17`, `/std:c++20`, `/std:c++latest`
- PCH: `/Yu` (use PCH), `/Fp` (PCH file path)

#### MSVC Linking

```python
def _LinkMSVC(self, project, objectFiles, outputFile) -> bool:
    """Link with MSVC link.exe."""
    if project.kind == ProjectKind.STATIC_LIB:
        return self._CreateStaticLibMSVC(project, objectFiles, outputFile)

    args = [self.toolchain.ldPath or "link.exe"]
    args.append("/nologo")
    args.append(f"/OUT:{outputFile}")

    # Subsystem
    if project.kind == ProjectKind.CONSOLE_APP:
        args.append("/SUBSYSTEM:CONSOLE")
    elif project.kind == ProjectKind.WINDOWED_APP:
        args.append("/SUBSYSTEM:WINDOWS")

    # Debug
    if project.symbols:
        args.append("/DEBUG")
        pdbFile = str(Path(outputFile).with_suffix('.pdb'))
        args.append(f"/PDB:{pdbFile}")

    # Library directories
    for libDir in project.libDirs:
        args.append(f"/LIBPATH:{libDir}")

    # Object files
    args.extend(objectFiles)

    # Libraries
    for lib in project.links:
        if self._IsDirectLibPath(lib):
            args.append(lib)
        else:
            # Auto-detect local project vs system library
            if lib in self.workspace.projects:
                libPath = self._GetProjectOutputPath(lib)
                args.append(libPath)
            else:
                args.append(f"{lib}.lib")

    # Linker flags
    args.extend(project.ldflags)

    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

**MSVC Linker Flags:**
- Subsystem: `/SUBSYSTEM:CONSOLE` or `/SUBSYSTEM:WINDOWS`
- Output: `/OUT:file.exe`
- Debug: `/DEBUG`, `/PDB:file.pdb`
- Library paths: `/LIBPATH:path`

#### Static Library Creation

```python
def _CreateStaticLibMSVC(self, project, objectFiles, outputFile) -> bool:
    """Create static library with lib.exe."""
    args = [self.toolchain.arPath or "lib.exe"]
    args.append("/nologo")
    args.append(f"/OUT:{outputFile}")
    args.extend(objectFiles)

    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

---

### LinuxBuilder Deep Dive

**Location:** `Jenga/Core/Builders/Linux.py`

#### GCC/Clang Compilation

```python
def Compile(self, project, sourceFile, objectFile) -> bool:
    """Compile with GCC or Clang."""
    compiler = self.toolchain.cxxPath or "g++"
    if self.is_clang:
        compiler = self.toolchain.cxxPath or "clang++"

    args = [compiler]
    args.append("-c")  # Compile only
    args.append("-o")
    args.append(objectFile)

    # Include directories
    for incDir in project.includeDirs:
        args.append(f"-I{incDir}")

    # Defines
    for define in project.defines:
        args.append(f"-D{define}")

    # C++ standard
    if project.cppdialect:
        stdMap = {
            "C++11": "-std=c++11",
            "C++14": "-std=c++14",
            "C++17": "-std=c++17",
            "C++20": "-std=c++20",
            "C++23": "-std=c++23",
        }
        args.append(stdMap.get(project.cppdialect, "-std=c++17"))

    # Optimization
    if project.optimize == Optimization.OFF:
        args.append("-O0")
    elif project.optimize == Optimization.SIZE:
        args.append("-Os")
    elif project.optimize == Optimization.SPEED:
        args.append("-O2")
    elif project.optimize == Optimization.FULL:
        args.append("-O3")

    # Debug symbols
    if project.symbols:
        args.append("-g")

    # Warnings
    if project.warnings == WarningLevel.ALL:
        args.append("-Wall")
    elif project.warnings == WarningLevel.EXTRA:
        args.extend(["-Wall", "-Wextra"])
    elif project.warnings == WarningLevel.PEDANTIC:
        args.extend(["-Wall", "-Wextra", "-Wpedantic"])
    elif project.warnings == WarningLevel.ERROR:
        args.append("-Werror")

    # Position-independent code (for shared libraries)
    if project.kind == ProjectKind.SHARED_LIB:
        args.append("-fPIC")

    # PCH
    if project.pchHeader:
        pchPath = self.GetObjectDir(project) / f"{project.pchHeader}.gch"
        args.append(f"-include")
        args.append(project.pchHeader)
        args.append(f"-Winvalid-pch")

    # Source file
    args.append(sourceFile)

    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

**GCC/Clang Flag Mapping:**
- Optimization: `-O0`, `-Os` (size), `-O2` (speed), `-O3` (max)
- Debug: `-g`
- Warnings: `-Wall`, `-Wextra`, `-Wpedantic`, `-Werror`
- Standard: `-std=c++11`, `-std=c++14`, `-std=c++17`, `-std=c++20`, `-std=c++23`
- PIC: `-fPIC` (position-independent code for shared libs)

#### Linux Linking

```python
def Link(self, project, objectFiles, outputFile) -> bool:
    """Link with GCC/Clang."""
    if project.kind == ProjectKind.STATIC_LIB:
        return self._CreateStaticLib(project, objectFiles, outputFile)

    linker = self.toolchain.ldPath or self.toolchain.cxxPath or "g++"
    args = [linker]

    # Output
    args.extend(["-o", outputFile])

    # Shared library
    if project.kind == ProjectKind.SHARED_LIB:
        args.append("-shared")
        # RPATH for runtime library discovery
        args.append(f"-Wl,-rpath,$ORIGIN")

    # Debug
    if project.symbols:
        args.append("-g")

    # Library directories
    for libDir in project.libDirs:
        args.append(f"-L{libDir}")

    # Object files (must come before libraries)
    args.extend(objectFiles)

    # Libraries
    for lib in project.links:
        if self._IsDirectLibPath(lib):
            args.append(lib)
        else:
            if lib in self.workspace.projects:
                libPath = self._GetProjectOutputPath(lib)
                args.append(libPath)
            else:
                args.append(f"-l{lib}")

    # Linker flags
    args.extend(project.ldflags)

    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

**Linux Linker Notes:**
- Shared library: `-shared` flag
- RPATH: `-Wl,-rpath,$ORIGIN` for relative library loading
- Library linking: `-L` for paths, `-l` for libraries
- **Order matters:** Object files before libraries!

#### Static Library Creation (ar)

```python
def _CreateStaticLib(self, project, objectFiles, outputFile) -> bool:
    """Create static library with ar."""
    archiver = self.toolchain.arPath or "ar"
    args = [archiver, "rcs", outputFile]
    args.extend(objectFiles)

    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

**ar flags:**
- `r` - Replace/insert objects
- `c` - Create archive
- `s` - Create/update symbol index

---

### AndroidBuilder Deep Dive

**Location:** `Jenga/Core/Builders/Android.py`

#### NDK Configuration

```python
def __init__(self, workspace, config, platform, targetOs, targetArch, targetEnv, verbose):
    super().__init__(workspace, config, platform, targetOs, targetArch, targetEnv, verbose)

    # Resolve SDK/NDK paths
    self.sdkPath = self._ResolveSDKPath()
    self.ndkPath = self._ResolveNDKPath()
    self.jdkPath = self._ResolveJDKPath()

    # Validate
    if not self.ndkPath:
        raise RuntimeError("Android NDK not found. Set ANDROID_NDK_HOME or androidndkpath()")

    # Setup NDK toolchain
    self._PrepareNDKToolchain()

def _PrepareNDKToolchain(self):
    """Configure NDK Clang toolchain."""
    # Find LLVM toolchain directory
    toolchainDir = None
    for path in (self.ndkPath / "toolchains" / "llvm" / "prebuilt").glob("*"):
        if path.is_dir():
            toolchainDir = path
            break

    if not toolchainDir:
        raise RuntimeError(f"NDK LLVM toolchain not found in {self.ndkPath}")

    # Set compiler paths
    self.toolchain.cxxPath = str(toolchainDir / "bin" / "clang++")
    self.toolchain.ccPath = str(toolchainDir / "bin" / "clang")
    self.toolchain.arPath = str(toolchainDir / "bin" / "llvm-ar")

    # Set sysroot
    self.toolchain.sysroot = str(toolchainDir / "sysroot")

    # Set target triple
    apiLevel = self._GetMinApiLevel()
    abiTriples = {
        TargetArch.ARM64: f"aarch64-linux-android{apiLevel}",
        TargetArch.ARM: f"armv7a-linux-androideabi{apiLevel}",
        TargetArch.X86_64: f"x86_64-linux-android{apiLevel}",
        TargetArch.X86: f"i686-linux-android{apiLevel}",
    }
    self.toolchain.targetTriple = abiTriples.get(self.targetArch)
```

**NDK Structure:**
```
android-ndk/
├── toolchains/
│   └── llvm/
│       └── prebuilt/
│           └── {host}/
│               ├── bin/
│               │   ├── clang
│               │   ├── clang++
│               │   └── llvm-ar
│               └── sysroot/
│                   ├── usr/include/
│                   └── usr/lib/
```

#### NDK Compilation

```python
def Compile(self, project, sourceFile, objectFile) -> bool:
    """Compile with NDK Clang."""
    args = [self.toolchain.cxxPath]
    args.append("-c")
    args.append("-o")
    args.append(objectFile)

    # Target triple
    args.append(f"--target={self.toolchain.targetTriple}")

    # Sysroot
    args.append(f"--sysroot={self.toolchain.sysroot}")

    # Android-specific defines
    args.append("-DANDROID")
    args.append(f"-D__ANDROID_API__={self._GetMinApiLevel()}")

    # Architecture-specific flags
    if self.targetArch == TargetArch.ARM:
        args.append("-march=armv7-a")
        args.append("-mfloat-abi=softfp")
        args.append("-mfpu=neon")
    elif self.targetArch == TargetArch.ARM64:
        args.append("-march=armv8-a")

    # Position-independent code (always for Android)
    args.append("-fPIC")

    # Include directories
    for incDir in project.includeDirs:
        args.append(f"-I{incDir}")

    # Defines
    for define in project.defines:
        args.append(f"-D{define}")

    # C++ standard
    if project.cppdialect:
        args.append(f"-std={project.cppdialect.lower().replace('++', '+')}")

    # Optimization, warnings, etc. (same as Linux)
    # ...

    # Source file
    args.append(sourceFile)

    result = Process.ExecuteCommand(args, captureOutput=True, silent=(not self.verbose))
    self._lastResult = result
    return result.succeeded
```

**Android-Specific Flags:**
- `--target=aarch64-linux-android{api}` - Target triple
- `--sysroot={path}` - Android system headers/libs
- `-DANDROID` - Android platform define
- `-fPIC` - Always position-independent

#### APK Packaging

```python
def BuildAPK(self, project, nativeLibs) -> bool:
    """Build signed/aligned APK."""
    buildDir = Path(self.GetObjectDir(project)) / "apk"
    buildDir.mkdir(parents=True, exist_ok=True)

    # 1. Compile resources with aapt2
    resZip = buildDir / "resources.zip"
    if not self._CompileResources(project, buildDir, resZip):
        return False

    # 2. Link resources and generate R.java
    rJavaDir = buildDir / "gen"
    if not self._LinkResources(project, resZip, rJavaDir, buildDir):
        return False

    # 3. Compile Java/Kotlin sources and generate DEX
    dexFile = buildDir / "classes.dex"
    if not self._CompileDex(project, rJavaDir, dexFile):
        return False

    # 4. Assemble APK
    unsignedApk = buildDir / "app-unsigned.apk"
    if not self._AssembleApk(project, buildDir, dexFile, resZip, nativeLibs, unsignedApk):
        return False

    # 5. Zipalign
    alignedApk = buildDir / "app-unsigned-aligned.apk"
    if not self._Zipalign(unsignedApk, alignedApk):
        return False

    # 6. Sign APK
    finalApk = self.GetTargetPath(project)
    if not self._SignApk(project, alignedApk, finalApk):
        return False

    Display.Success(f"APK created: {finalApk}")
    return True
```

**APK Build Pipeline:**
1. **aapt2 compile** - Compile resources (XML → binary)
2. **aapt2 link** - Link resources, generate R.java
3. **javac + d8** - Compile Java to DEX bytecode
4. **ZIP assembly** - Combine DEX, resources, native libs
5. **zipalign** - 4-byte alignment optimization
6. **apksigner** - Sign with keystore

#### Resource Compilation (aapt2)

```python
def _CompileResources(self, project, buildDir, outputZip) -> bool:
    """Compile resources with aapt2."""
    aapt2 = self._ToolPath("aapt2")

    # Compile each resource file
    compiledDir = buildDir / "compiled_resources"
    compiledDir.mkdir(parents=True, exist_ok=True)

    # Find resource files (res/values/strings.xml, res/layout/main.xml, etc.)
    resDir = Path(project.location) / "res"
    if resDir.exists():
        args = [str(aapt2), "compile", "-o", str(compiledDir)]
        for resFile in resDir.rglob("*"):
            if resFile.is_file():
                args.append(str(resFile))

        result = Process.ExecuteCommand(args, captureOutput=True)
        if not result.succeeded:
            return False

    # Link compiled resources
    args = [str(aapt2), "link",
            "-o", str(outputZip),
            "--manifest", str(self._GenerateManifest(project, buildDir)),
            "-I", str(self.sdkPath / "platforms" / f"android-{project.androidCompileSdk}" / "android.jar"),
    ]

    if compiledDir.exists():
        args.append(str(compiledDir / "*"))

    result = Process.ExecuteCommand(args, captureOutput=True)
    return result.succeeded
```

#### Manifest Generation

```python
def _GenerateManifest(self, project, outputDir) -> Path:
    """Auto-generate AndroidManifest.xml."""
    manifestPath = outputDir / "AndroidManifest.xml"

    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{project.androidApplicationId}"
    android:versionCode="{project.androidVersionCode}"
    android:versionName="{project.androidVersionName}">

    <uses-sdk
        android:minSdkVersion="{project.androidMinSdk}"
        android:targetSdkVersion="{project.androidTargetSdk}" />
"""

    # Add permissions
    for permission in project.androidPermissions:
        manifest += f'    <uses-permission android:name="{permission}" />\n'

    manifest += "\n    <application>\n"

    # Native activity
    if project.androidNativeActivity:
        manifest += f"""
        <activity android:name="android.app.NativeActivity"
                  android:label="@string/app_name">
            <meta-data android:name="android.app.lib_name"
                       android:value="{project.name}" />
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
"""

    manifest += "    </application>\n</manifest>"

    manifestPath.write_text(manifest, encoding='utf-8')
    return manifestPath
```

---

(Content continues with more builder implementations, command system, testing, etc...)

---

*This is Part 1 of the Developer Guide. The guide continues with detailed coverage of all remaining topics including the Command System, Testing Strategies, Adding New Platforms, Code Style Guidelines, and Contributing Workflow.*

---

**Jenga Build System v2.0.2**
© 2026 Rihen. All rights reserved.