# API embarquée (Embed) / Embedded API

## 🇫🇷 Français

Depuis la **v2.0.9**, Jenga expose une **API programmatique structurée** pour
être piloté depuis une application hôte (ex. l'IDE NKCode, qui embarque un
interpréteur CPython via pybind11) — sans CLI, sans parsing de stdout.

```python
from Jenga.Core.Embed import Build, Rebuild

result = Build(jenga_file="D:/mon/projet.jenga", target="MonApp",
               config="Debug", platform=None, toolchain=None, sink=monSink)
print(result.exitCode, result.totalErrors, result.errorFiles)
```

- **`Build`/`Rebuild`** retournent un `BuildResult` (exitCode, projets
  construits/échoués, erreurs/avertissements, fichiers en erreur, échec de
  lien) — jamais un simple code de sortie.
- **`sink`** (optionnel, duck-typing) reçoit la progression en temps réel :
  `OnProjectTotal(total)`, `OnProjectDone(ok)`, `OnFileTotal(projet, total)`,
  `OnFileDone(projet, index, total, fichier, ok, warned)`,
  `OnCompileError(projet, fichier, message)`, `OnLinkError(...)`,
  `OnLogLine(ligne)` — la sortie console CLI reste identique.
- **`Jenga.Core.CompilerFetch.InstallDefaultCompiler(dest, sink)`** :
  télécharge le compilateur par défaut (llvm-mingw/Clang x86_64, Windows)
  avec progression via le même sink. Idempotent.
- L'état du DSL étant global (non réentrant), **un seul appel à la fois**
  par interprète.

## 🇬🇧 English

Since **v2.0.9**, Jenga exposes a **structured programmatic API** so a host
application (e.g. the NKCode IDE, which embeds CPython via pybind11) can
drive builds without the CLI and without scraping stdout.

`Build`/`Rebuild` return a `BuildResult` (exit code, projects built/failed,
errors/warnings, failing files, link failure). The optional duck-typed
`sink` receives real-time progress events (`OnProjectTotal`, `OnFileDone`,
`OnCompileError`, `OnLogLine`, …) while CLI console output stays unchanged.
`CompilerFetch.InstallDefaultCompiler(dest, sink)` downloads the default
Clang toolchain (llvm-mingw, Windows) with progress. DSL state is global:
**one call at a time** per interpreter.
