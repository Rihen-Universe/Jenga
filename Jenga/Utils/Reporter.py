#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reporter – Generate reports and handle build/test logging.
Contains data classes (Report, BuildReport, TestReport) and a static
Reporter class for console logging with verbosity control.
All public methods are PascalCase.
"""

import json
import time, sys, re as _re, threading
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from datetime import datetime

from .Colored import Colored
from .FileSystem import FileSystem
from .Display import Display
from .Process import ProcessResult

# ---------------------------------------------------------------------------
# Data classes – camelCase fields (conteneurs)
# ---------------------------------------------------------------------------

class Report:
    """Base report container."""
    def __init__(self, title: str = "Jenga Report"):
        self.title = title
        self.timestamp = time.time()
        self.sections: List[Dict[str, Any]] = []

    def AddSection(self, name: str, content: Any = None) -> None:
        self.sections.append({"name": name, "content": content, "timestamp": time.time()})

    def Clear(self) -> None:
        self.sections.clear()

    def ToDict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "sections": self.sections,
        }

    def ToJson(self, indent: int = 2) -> str:
        return json.dumps(self.ToDict(), indent=indent, ensure_ascii=False)

    def SaveJson(self, path: Union[str, Path]) -> None:
        FileSystem.WriteFile(path, self.ToJson())

    def ToText(self, colored: bool = True) -> str:
        """Generate human‑readable text report."""
        lines = []
        if colored:
            lines.append(Colored.Colorize(f"=== {self.title} ===", bold=True, color="white"))
        else:
            lines.append(f"=== {self.title} ===")
        dt = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        if colored:
            lines.append(Colored.Colorize(f"Generated: {dt}", dim=True))
        else:
            lines.append(f"Generated: {dt}")
        lines.append("")

        for sec in self.sections:
            if colored:
                lines.append(Colored.Colorize(f"▶ {sec['name']}", bold=True, color="cyan"))
            else:
                lines.append(f"▶ {sec['name']}")
            content = sec.get("content")
            if content is not None:
                if isinstance(content, str):
                    lines.append(content)
                elif isinstance(content, list):
                    lines.extend([f"  - {item}" for item in content])
                elif isinstance(content, dict):
                    for k, v in content.items():
                        lines.append(f"  {k}: {v}")
                else:
                    lines.append(str(content))
            lines.append("")
        return "\n".join(lines)

    def Print(self, colored: bool = True) -> None:
        print(self.ToText(colored=colored))


class BuildReport(Report):
    """Specialized report for build operations."""
    def __init__(self):
        super().__init__("Jenga Build Report")
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.startTime = time.time()
        self.endTime = None

    def AddProjectResult(self, project: str, success: bool,
                         duration: float, output: Optional[str] = None,
                         errors: Optional[List[str]] = None) -> None:
        self.projects[project] = {
            "success": success,
            "duration": duration,
            "output": output,
            "errors": errors or []
        }

    def Finish(self) -> None:
        self.endTime = time.time()

    @property
    def totalDuration(self) -> float:
        if self.endTime:
            return self.endTime - self.startTime
        return time.time() - self.startTime

    @property
    def successCount(self) -> int:
        return sum(1 for p in self.projects.values() if p["success"])

    @property
    def failureCount(self) -> int:
        return sum(1 for p in self.projects.values() if not p["success"])

    def ToDict(self) -> Dict[str, Any]:
        d = super().ToDict()
        d.update({
            "type": "build",
            "startTime": self.startTime,
            "endTime": self.endTime,
            "totalDuration": self.totalDuration,
            "projects": self.projects,
            "successCount": self.successCount,
            "failureCount": self.failureCount,
        })
        return d

    def ToText(self, colored: bool = True) -> str:
        lines = []
        if colored:
            lines.append(Colored.Colorize(f"=== {self.title} ===", bold=True, color="white"))
        else:
            lines.append(f"=== {self.title} ===")
        dt = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Generated: {dt}")
        lines.append(f"Total time: {self.totalDuration:.3f}s")
        lines.append(f"Projects: {len(self.projects)} (✓ {self.successCount} ✗ {self.failureCount})")
        lines.append("")

        for proj, data in self.projects.items():
            if data["success"]:
                status = Colored.Colorize("✓ PASS", color="green") if colored else "PASS"
            else:
                status = Colored.Colorize("✗ FAIL", color="red", bold=True) if colored else "FAIL"
            lines.append(f"{status}  {proj}  ({data['duration']:.3f}s)")
            if not data["success"] and data["errors"]:
                for err in data["errors"][:3]:
                    lines.append(f"      {err}")
        return "\n".join(lines)


class TestReport(Report):
    """Specialized report for test execution."""
    def __init__(self):
        super().__init__("Jenga Test Report")
        self.tests: Dict[str, Dict[str, Any]] = {}
        self.totalTests = 0
        self.passedTests = 0
        self.failedTests = 0
        self.skippedTests = 0

    def AddTestCase(self, name: str, result: str, duration: float,
                    message: str = "", suite: str = "") -> None:
        """result: 'pass', 'fail', 'skip'"""
        self.tests[name] = {
            "name": name,
            "result": result,
            "duration": duration,
            "message": message,
            "suite": suite,
        }
        self.totalTests += 1
        if result == "pass":
            self.passedTests += 1
        elif result == "fail":
            self.failedTests += 1
        elif result == "skip":
            self.skippedTests += 1

    def ToDict(self) -> Dict[str, Any]:
        d = super().ToDict()
        d.update({
            "type": "test",
            "total": self.totalTests,
            "passed": self.passedTests,
            "failed": self.failedTests,
            "skipped": self.skippedTests,
            "tests": list(self.tests.values()),
        })
        return d

    def ToText(self, colored: bool = True) -> str:
        lines = []
        if colored:
            lines.append(Colored.Colorize(f"=== {self.title} ===", bold=True, color="white"))
        else:
            lines.append(f"=== {self.title} ===")
        dt = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Generated: {dt}")
        lines.append(f"Tests: {self.totalTests} total, {self.passedTests} passed, "
                     f"{self.failedTests} failed, {self.skippedTests} skipped")
        lines.append("")

        if self.failedTests > 0:
            if colored:
                lines.append(Colored.Colorize("Failed tests:", color="red", bold=True))
            else:
                lines.append("Failed tests:")
            for name, test in self.tests.items():
                if test["result"] == "fail":
                    lines.append(f"  ✗ {name}  ({test['duration']:.3f}s)")
                    if test["message"]:
                        lines.append(f"      {test['message']}")
            lines.append("")

        if self.passedTests > 0 and colored:
            lines.append(Colored.Colorize(f"✓ {self.passedTests} passed", color="green"))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory functions (PascalCase) – pour créer les rapports
# ---------------------------------------------------------------------------

def CreateBuildReport() -> BuildReport:
    return BuildReport()

def CreateTestReport() -> TestReport:
    return TestReport()

def GenerateReportFromData(data: Dict[str, Any], title: str = "Report") -> Report:
    """Convert a generic dictionary to a Report object."""
    report = Report(title)
    report.timestamp = data.get("timestamp", time.time())
    for key, value in data.items():
        if key not in ("title", "timestamp", "datetime"):
            report.AddSection(key, value)
    return report

def ExportJUnitXml(report: TestReport, path: Union[str, Path]) -> None:
    """Export test report in JUnit XML format (for CI integration)."""
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    testsuites = ET.Element("testsuites")
    testsuite = ET.SubElement(testsuites, "testsuite",
                              name="Jenga",
                              tests=str(report.totalTests),
                              failures=str(report.failedTests),
                              skipped=str(report.skippedTests),
                              time=str(report.totalDuration if hasattr(report, 'totalDuration') else 0),
                              timestamp=datetime.fromtimestamp(report.timestamp).isoformat())

    for test in report.tests.values():
        case = ET.SubElement(testsuite, "testcase",
                             name=test["name"],
                             classname=test.get("suite", ""),
                             time=str(test["duration"]))
        if test["result"] == "fail":
            failure = ET.SubElement(case, "failure", message=test.get("message", ""))
            failure.text = test.get("message", "")
        elif test["result"] == "skip":
            ET.SubElement(case, "skipped")

    xml_str = ET.tostring(testsuites, encoding="utf-8")
    dom = minidom.parseString(xml_str)
    pretty = dom.toprettyxml(indent="  ")
    FileSystem.WriteFile(path, pretty)


# ---------------------------------------------------------------------------
# Reporter class – Console logging with verbosity and timing
# ---------------------------------------------------------------------------

class Reporter:
    """Build reporter for logging and progress.

    Collecte aussi tous les Warning/Error de haut niveau (DSL, packaging, sign,
    keystore...) dans des listes class-level pour les re-afficher en encadré à
    la toute fin du build (cf. PrintCollectedSummary). Les warnings 'critical'
    surfacent en rouge et peuvent élever le code de retour."""
    verbose = False
    start_time = None
    # Collectes (lifetime = entre Reset() et PrintCollectedSummary())
    _collectedWarnings: list = []         # list[str]  — warnings non critiques
    _collectedCriticals: list = []        # list[str]  — warnings flagués critical=True
    _collectedErrors: list = []           # list[str]  — erreurs de haut niveau

    @classmethod
    def Start(cls) -> None:
        """Start build timer."""
        cls.start_time = time.time()

    @classmethod
    def End(cls) -> None:
        """End build and print elapsed time."""
        if cls.start_time:
            elapsed = time.time() - cls.start_time
            Display.Info(f"Build completed in {elapsed:.2f}s")

    @classmethod
    def Section(cls, title: str) -> None:
        """Print section header."""
        Display.Section(title)

    @classmethod
    def Subsection(cls, title: str) -> None:
        """Print subsection header."""
        Display.Subsection(title)

    @classmethod
    def Success(cls, message: str) -> None:
        """Print success message."""
        Display.Success(message)

    @classmethod
    def Error(cls, message: str) -> None:
        """Print error message + collecte pour le résumé final."""
        cls._collectedErrors.append(str(message))
        Display.Error(message)

    @classmethod
    def Warning(cls, message: str, critical: bool = False) -> None:
        """Print warning message + collecte pour le résumé final.

        `critical=True` indique un warning bloquant fonctionnellement (ex. APK
        non signable → Android refuse l'install). Surfacé en rouge dans le
        résumé final et peut élever le code de retour selon la configuration."""
        if critical:
            cls._collectedCriticals.append(str(message))
        else:
            cls._collectedWarnings.append(str(message))
        Display.Warning(message)

    @classmethod
    def Info(cls, message: str) -> None:
        """Print info message."""
        Display.Info(message)

    @classmethod
    def Detail(cls, message: str) -> None:
        """Print detail message (only in verbose mode)."""
        if cls.verbose:
            Display.Detail(message)

    @classmethod
    def Debug(cls, message: str) -> None:
        """Print debug message (only in verbose mode)."""
        if cls.verbose:
            Display.Debug(message)

    # -----------------------------------------------------------------------
    # Collecte et résumé final (anti-warning-noye-dans-1000-lignes)
    # -----------------------------------------------------------------------
    @classmethod
    def Reset(cls) -> None:
        """Vide les listes collectées. Appelé au début de chaque BuildCommand.Execute."""
        cls._collectedWarnings = []
        cls._collectedCriticals = []
        cls._collectedErrors = []

    @classmethod
    def HasCriticalWarnings(cls) -> bool:
        """Indique si au moins un warning critique a été collecté."""
        return bool(cls._collectedCriticals)

    @classmethod
    def GetCollectedCounts(cls) -> tuple:
        """Retourne (nbCriticals, nbWarnings, nbErrors)."""
        return (len(cls._collectedCriticals), len(cls._collectedWarnings),
                len(cls._collectedErrors))

    @classmethod
    def PrintCollectedSummary(cls) -> None:
        """Imprime, en TOUTE FIN de build (après packaging APK/MSI/...), un
        encadré listant TOUS les warnings et erreurs collectés. Visible même
        au milieu de 1000 lignes de logs : c'est le 'dernier mot' du build.

        Rien à dire → no-op silencieux. Sinon : criticals en rouge, warnings
        en jaune, errors en rouge. Texte intégral, pas seulement des compteurs."""
        if not (cls._collectedCriticals or cls._collectedWarnings or cls._collectedErrors):
            return
        w = 80

        def _box(items, label, color):
            print()
            print(Colored.Colorize("┌" + "─" * (w - 2) + "┐", color=color, bold=True))
            heading = f" {label} ({len(items)}) "
            print(Colored.Colorize("│" + heading.ljust(w - 2) + "│", color=color, bold=True))
            print(Colored.Colorize("├" + "─" * (w - 2) + "┤", color=color))
            for index, item in enumerate(items, start=1):
                # Wrap les longs messages sur plusieurs lignes (largeur w-6).
                inner_width = w - 6
                first_prefix = f"  {index:>2}. "
                lines = _WrapLines(item, inner_width)
                if not lines:
                    lines = [""]
                print(Colored.Colorize("│" + (first_prefix + lines[0]).ljust(w - 2) + "│",
                                       color=color))
                for sub in lines[1:]:
                    print(Colored.Colorize("│" + ("      " + sub).ljust(w - 2) + "│",
                                           color=color))
            print(Colored.Colorize("└" + "─" * (w - 2) + "┘", color=color, bold=True))

        if cls._collectedErrors:
            _box(cls._collectedErrors, "ERRORS", "red")
        if cls._collectedCriticals:
            _box(cls._collectedCriticals, "CRITICAL WARNINGS (action requise)", "red")
        if cls._collectedWarnings:
            _box(cls._collectedWarnings, "WARNINGS", "yellow")


def _WrapLines(text: str, width: int) -> list:
    """Soft-wrap pour rester dans la largeur de l'encadré, sans casser les
    chemins de fichier ni les commandes."""
    import textwrap
    if not text:
        return []
    return textwrap.wrap(str(text), width=max(20, width),
                         break_long_words=False, break_on_hyphens=False) or [str(text)]


# ---------------------------------------------------------------------------
# BuildLogger – Real-time build progress and error formatting
# ---------------------------------------------------------------------------

class BuildLogger:
    """Tracks compilation progress and formats compiler output in real-time.
    Produces beautiful Jenga-style output with double-line bordered boxes."""

    # Double-line box drawing characters
    _TL = "╔"  # top-left
    _TR = "╗"  # top-right
    _BL = "╚"  # bottom-left
    _BR = "╝"  # bottom-right
    _H = "═"   # horizontal
    _V = "║"   # vertical
    _ML = "╠"  # middle-left
    _MR = "╣"  # middle-right

    # Single-line box drawing characters for result boxes
    _STL = "┌"  # single top-left
    _STR = "┐"  # single top-right
    _SBL = "└"  # single bottom-left
    _SBR = "┘"  # single bottom-right
    _SH = "─"   # single horizontal
    _SV = "│"   # single vertical

    _BOX_WIDTH = 96

    def __init__(self, project_name: str, project_kind: str = "", workspace_root: str = None):
        self.project_name = project_name
        self.project_kind = project_kind
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self.total_files = 0
        self.compiled = 0
        self.cached = 0
        self.failed = 0
        self.linked = 0
        self.warnings_count = 0
        self.errors_count = 0
        self._start_time = time.time()
        self._lock = threading.Lock()  # Thread safety for parallel compilation

    def SetTotal(self, total: int) -> None:
        """Set total number of files to compile."""
        self.total_files = total
        Display.Info(f"Found {total} source file(s)")

    def LogCompile(self, source_file: str, result: Optional[ProcessResult]) -> None:
        """
        Enregistre la compilation d'un fichier et affiche le résultat de manière structurée.
        En cas d'erreur, tout le message du compilateur est affiché dans un cadre.
        Thread-safe for parallel compilation.
        """
        with self._lock:
            self.compiled += 1
            filename = Path(source_file).name
            progress = f"[{self.compiled}/{self.total_files}]"

            # Cas particulier : pas de ProcessResult (modules précompilés, etc.)
            if result is None:
                status = Colored.Colorize(progress, color='green')
                print(f"{Colored.Colorize('✓', color='green')}   {status} Compiled module: {filename}")
                return

            # Fusionner stdout et stderr pour avoir tout le message
            output = (result.stderr or "") + (result.stdout or "")

            if result.returnCode == 0:
                # Compilation réussie – on vérifie les warnings
                has_warnings = output and self._HasWarnings(output)
                if has_warnings:
                    self.warnings_count += self._CountPattern(output, r'\bwarning\b')
                    status = Colored.Colorize(progress, color='yellow')
                    print(f"{Colored.Colorize('✓', color='yellow')}   {status} Compiled with warnings: {Colored.Colorize(filename, color='yellow')}")
                    self._PrintWarningBox(filename, output)
                else:
                    status = Colored.Colorize(progress, color='green')
                    print(f"{Colored.Colorize('✓', color='green')}   {status} Compiled: {filename}")
            else:
                # Échec de compilation
                self.failed += 1
                self.errors_count += max(1, self._CountPattern(output, r'\berror\b'))
                status = Colored.Colorize(progress, color='red')

                # Ligne vide pour séparer du contexte précédent
                print()
                # Affiche tout le message d'erreur dans un cadre
                self._PrintErrorBox(filename, output)
                # Récapitulatif de l'échec
                print(f"\n{Colored.Colorize('✗', color='red')} {Colored.Colorize('✗', color='red')} Compilation failed: {source_file}")
            
    # def LogCompile(self, source_file: str, result=None) -> None:
    #     """Log a file compilation with optional captured output."""
    #     self.compiled += 1
    #     filename = Path(source_file).name
    #     progress = f"[{self.compiled}/{self.total_files}]"

    #     if result is None or result.returnCode == 0:
    #         has_warnings = result and result.stderr and self._HasWarnings(result.stderr)
    #         if has_warnings:
    #             self.warnings_count += self._CountPattern(result.stderr, r'\bwarning\b')
    #             status = Colored.Colorize(progress, color='yellow')
    #             print(f"{Colored.Colorize('✓', color='yellow')}   {status} Compiled: {Colored.Colorize(filename, color='yellow')}")
    #             self._PrintWarningBox(filename, result.stderr)
    #         else:
    #             status = Colored.Colorize(progress, color='green')
    #             print(f"{Colored.Colorize('✓', color='green')}   {status} Compiled: {filename}")
    #     else:
    #         self.failed += 1
    #         self.errors_count += max(1, self._CountPattern(result.stderr or result.stdout or "", r'\berror\b'))
    #         status = Colored.Colorize(progress, color='red')
    #         output = (result.stderr or "") + (result.stdout or "")
    #         print()
    #         self._PrintErrorBox(filename, output)
    #         print(f"\n{Colored.Colorize('✗', color='red')} {Colored.Colorize('✗', color='red')} Compilation failed: {source_file}")

    def LogCached(self, source_file: str) -> None:
        """Log a cached (skipped) file."""
        self.cached += 1
        self.compiled += 1

    def LogUpToDate(self) -> None:
        """Log that all files are up to date."""
        Display.Success("All files up to date")

    def LogCompiling(self, count: int, cached: int) -> None:
        """Log start of compilation with file count."""
        if cached > 0:
            Display.Info(f"Compiling {count} file(s) ({cached} cached)")
        else:
            Display.Info(f"Compiling {count} file(s)")

    def LogLink(self, output_file: str, result=None) -> None:
        """Log link step. Count link errors and failures like compilation errors."""
        # Convert to relative path if workspace_root is set
        display_path = self._GetRelativePath(output_file)

        with self._lock:
            if result is None or result.returnCode == 0:
                self.linked += 1
                Display.Info("Linking...")
                Display.Success(f"Built: {display_path}")
                if result and result.stderr and self._HasWarnings(result.stderr):
                    self.warnings_count += self._CountPattern(result.stderr, r'\bwarning\b')
                    self._PrintWarningBox("Linker", result.stderr)
            else:
                # Link failed - count errors like compilation failures
                self.failed += 1
                output = (result.stderr or "") + (result.stdout or "")
                self.errors_count += max(1, self._CountPattern(output, r'\bError\b|\bunresolved\b|\bundefined reference\b'))
                
                Display.Info("Linking...")
                if output.strip():
                    self._PrintErrorBox("Link Failed", output)
                Display.Error(f"Link failed: {display_path}")

    def PrintProjectHeader(self) -> None:
        """Print a beautiful project header box with double borders."""
        w = self._BOX_WIDTH
        inner = w - 2

        # Top border in cyan
        top = Colored.Colorize(self._TL + self._H * inner + self._TR, color='cyan', bold=True)
        print()
        print(top)

        # Project name and kind
        left_text = f"  Project: {self.project_name}"
        right_text = f"Kind: {self.project_kind}  " if self.project_kind else ""

        # Calculate spacing
        text_len = len(left_text) + len(right_text)
        spacing = max(1, inner - text_len)

        # Left side colored in white bold, right side in green
        left_colored = Colored.Colorize(left_text, color='white', bold=True)
        right_colored = Colored.Colorize(right_text, color='green', bold=True)
        border_v = Colored.Colorize(self._V, color='cyan', bold=True)

        print(f"{border_v}{left_colored}{' ' * spacing}{right_colored}{border_v}")

        # Bottom border in cyan
        bottom = Colored.Colorize(self._BL + self._H * inner + self._BR, color='cyan', bold=True)
        print(bottom)
        print()

    def PrintResultBox(self, success: bool) -> None:
        """Print a compact result box for the project build with error/warning stats."""
        w = self._BOX_WIDTH
        inner = w - 2
        elapsed = time.time() - self._start_time
        elapsed_str = f"{elapsed:.2f}s" if elapsed < 60 else f"{int(elapsed // 60)}m{elapsed % 60:.1f}s"

        color = 'green' if success else 'red'

        # Top border
        top = Colored.Colorize(self._STL + self._SH * inner + self._STR, color=color)
        print()
        print(top)

        # Status line
        if success:
            status_icon = Colored.Colorize("✓", color='green', bold=True)
            status_text = Colored.Colorize("Build Successful", color='green', bold=True)
        else:
            status_icon = Colored.Colorize("✗", color='red', bold=True)
            status_text = Colored.Colorize("Build Failed", color='red', bold=True)

        time_text = Colored.Colorize(f"Time: {elapsed_str}", color=color)
        left = f"  {status_icon} {status_text}"
        right = f"{time_text}  "

        # Strip ANSI codes for length calculation
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        left_plain = ansi_escape.sub('', left)
        right_plain = ansi_escape.sub('', right)

        spacing = max(1, inner - len(left_plain) - len(right_plain))
        border_v = Colored.Colorize(self._SV, color=color)

        print(f"{border_v}{left}{' ' * spacing}{right}{border_v}")

        # Error/Warning statistics line
        stats_parts = []
        if self.errors_count > 0:
            error_text = Colored.Colorize(f"Errors: {self.errors_count}", color='red', bold=True)
            stats_parts.append(error_text)
        if self.warnings_count > 0:
            warning_text = Colored.Colorize(f"Warnings: {self.warnings_count}", color='yellow', bold=True)
            stats_parts.append(warning_text)
        if self.failed > 0:
            failed_text = Colored.Colorize(f"Failed files: {self.failed}", color='red')
            stats_parts.append(failed_text)
        
        if stats_parts:
            stats_line = "  | ".join(stats_parts)
            stats_plain = ansi_escape.sub('', stats_line)
            padding = max(0, inner - 2 - len(stats_plain))
            print(f"{border_v} {stats_line}{' ' * padding} {border_v}")

        # Bottom border
        bottom = Colored.Colorize(self._SBL + self._SH * inner + self._SBR, color=color)
        print(bottom)

    def PrintStats(self) -> None:
        """Print build statistics summary - DEPRECATED, use PrintResultBox instead."""
        # This method is kept for backwards compatibility but does nothing
        # The new design uses PrintResultBox() instead
        pass

    def _PrintErrorBox(self, title: str, output: str) -> None:
        """Print a double-bordered error box with enhanced file:line:column parsing."""
        w = self._BOX_WIDTH
        inner = w - 2

        # Header
        header_text = f" Compilation Error: {title} "
        top = Colored.Colorize(self._TL + self._H * inner + self._TR, color='red', bold=True)
        header_line = self._PadBoxLine(header_text, inner)
        mid = Colored.Colorize(self._ML + self._H * inner + self._MR, color='red', bold=True)

        print(top)
        print(Colored.Colorize(self._V, color='red', bold=True) + Colored.Colorize(header_line, bold=True, color='white') + Colored.Colorize(self._V, color='red', bold=True))
        print(mid)

        # Content lines - parse and enhance error messages
        border_v = Colored.Colorize(self._V, color='red', bold=True)

        for raw_line in output.strip().splitlines():
            line = raw_line.rstrip()
            if not line:
                continue

            # Enhanced colorization with file:line:column highlighting
            colorized = self._ColorizeErrorLine(line)

            # Wrap long lines instead of truncating
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            line_plain = ansi_escape.sub('', line)

            if len(line_plain) > inner - 2:
                # Line is too long, wrap it intelligently
                wrapped_lines = self._WrapLine(line, inner - 2)
                for wrapped in wrapped_lines:
                    wrapped_colored = self._ColorizeErrorLine(wrapped) if wrapped == line else wrapped
                    wrapped_plain = ansi_escape.sub('', wrapped)
                    padding = max(0, inner - 2 - len(wrapped_plain))
                    print(f"{border_v} {wrapped_colored}{' ' * padding} {border_v}")
            else:
                # Line fits, display normally
                padding = max(0, inner - 2 - len(line_plain))
                print(f"{border_v} {colorized}{' ' * padding} {border_v}")

        # Bottom
        bottom = Colored.Colorize(self._BL + self._H * inner + self._BR, color='red', bold=True)
        print(bottom)

    def _PrintWarningBox(self, title: str, output: str) -> None:
        """Print a double-bordered warning box with enhanced formatting."""
        w = self._BOX_WIDTH
        inner = w - 2

        header_text = f" Warning: {title} "
        top = Colored.Colorize(self._TL + self._H * inner + self._TR, color='yellow', bold=True)
        header_line = self._PadBoxLine(header_text, inner)
        mid = Colored.Colorize(self._ML + self._H * inner + self._MR, color='yellow', bold=True)

        print(top)
        print(Colored.Colorize(self._V, color='yellow', bold=True) + Colored.Colorize(header_line, bold=True, color='white') + Colored.Colorize(self._V, color='yellow', bold=True))
        print(mid)

        border_v = Colored.Colorize(self._V, color='yellow', bold=True)

        for raw_line in output.strip().splitlines():
            line = raw_line.rstrip()
            if not line:
                continue

            colorized = self._ColorizeErrorLine(line)

            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            line_plain = ansi_escape.sub('', line)

            if len(line_plain) > inner - 2:
                # Wrap long lines
                wrapped_lines = self._WrapLine(line, inner - 2)
                for wrapped in wrapped_lines:
                    wrapped_colored = self._ColorizeErrorLine(wrapped) if wrapped == line else wrapped
                    wrapped_plain = ansi_escape.sub('', wrapped)
                    padding = max(0, inner - 2 - len(wrapped_plain))
                    print(f"{border_v} {wrapped_colored}{' ' * padding} {border_v}")
            else:
                padding = max(0, inner - 2 - len(line_plain))
                print(f"{border_v} {colorized}{' ' * padding} {border_v}")

        bottom = Colored.Colorize(self._BL + self._H * inner + self._BR, color='yellow', bold=True)
        print(bottom)

    @staticmethod
    def _PadBoxLine(text: str, width: int) -> str:
        """Center-pad text within the box width."""
        padding = max(0, width - len(text))
        left = padding // 2
        right = padding - left
        return " " * left + text + " " * right

    @staticmethod
    def _WrapLine(line: str, max_width: int) -> List[str]:
        """Intelligently wrap a long line into multiple lines.

        Args:
            line: The line to wrap
            max_width: Maximum width per line

        Returns:
            List of wrapped lines
        """
        if len(line) <= max_width:
            return [line]

        # Try to break at word boundaries
        lines = []
        current_line = ""
        words = line.split(' ')

        for word in words:
            # If word itself is too long, break it forcefully
            if len(word) > max_width:
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                # Break long word into chunks
                for i in range(0, len(word), max_width):
                    chunk = word[i:i + max_width]
                    if i + max_width < len(word):
                        lines.append(chunk)
                    else:
                        current_line = chunk
                continue

            # Check if adding this word would exceed limit
            test_line = current_line + (' ' if current_line else '') + word
            if len(test_line) > max_width:
                if current_line:
                    lines.append(current_line)
                current_line = word
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)

        return lines if lines else [line[:max_width]]

    @staticmethod
    def _ColorizeErrorLine(line: str) -> str:
        """Enhanced colorization with file:line:column highlighting."""
        # Highlight file:line:column patterns (e.g., main.cpp:42:5:)
        line = _re.sub(
            r'([a-zA-Z0-9_\-./\\]+\.[a-zA-Z]+):(\d+):(\d+):',
            lambda m: Colored.Colorize(m.group(1), color='cyan', bold=True) + ':' +
                     Colored.Colorize(m.group(2), color='magenta', bold=True) + ':' +
                     Colored.Colorize(m.group(3), color='magenta', bold=True) + ':',
            line
        )

        # Highlight keywords
        line = _re.sub(r'\bfatal error:', Colored.Colorize('fatal error:', color='red', bold=True), line)
        line = _re.sub(r'(?<!fatal )\berror:', Colored.Colorize('error:', color='red', bold=True), line)
        line = _re.sub(r'\bwarning:', Colored.Colorize('warning:', color='yellow', bold=True), line)
        line = _re.sub(r'\bnote:', Colored.Colorize('note:', color='cyan'), line)

        return line

    def _GetRelativePath(self, path: str) -> str:
        """Convert absolute path to relative path from workspace root."""
        if not self.workspace_root:
            return path

        try:
            abs_path = Path(path).resolve()
            rel_path = abs_path.relative_to(self.workspace_root)
            return str(rel_path)
        except (ValueError, Exception):
            # If path is not relative to workspace, return as-is
            return path

    @staticmethod
    def _HasWarnings(output: str) -> bool:
        return bool(_re.search(r'\bwarning\b', output, _re.IGNORECASE))

    @staticmethod
    def _CountPattern(output: str, pattern: str) -> int:
        return len(_re.findall(pattern, output, _re.IGNORECASE))


# ---------------------------------------------------------------------------
# BuildCoordinator – Global build header/footer and project coordination
# ---------------------------------------------------------------------------

class BuildCoordinator:
    """Coordinates the overall build process with beautiful headers and footers."""

    def __init__(self, workspace_name: str, config: str, target_os: str, target_arch: str, toolchain: str = ""):
        self.workspace_name = workspace_name
        self.config = config
        self.target_os = target_os
        self.target_arch = target_arch
        self.toolchain = toolchain
        self._start_time = time.time()
        self._projects_built = 0
        self._projects_total = 0
        self._projects_failed = 0
        self._total_errors = 0
        self._total_warnings = 0

    def PrintHeader(self, build_order: List[tuple], cache_status: str = None) -> None:
        """Print the global build header with build order visualization.

        Args:
            build_order: List of (project_name, project_kind, dependencies) tuples
            cache_status: Optional cache status message
        """
        print()

        # Configuration info
        print(Colored.Colorize("Configuration:", color='cyan') + f" {self.config}")
        print(Colored.Colorize("Target:       ", color='cyan') + f" {self.target_os} {self.target_arch}")
        if self.toolchain:
            print(Colored.Colorize("Toolchain:    ", color='cyan') + f" {self.toolchain}")

        # Cache status at same level as configuration
        if cache_status:
            if cache_status == "no_changes":
                print(Colored.Colorize("Cache:        ", color='cyan') + f" Workspace loaded from cache (no changes)")
            else:
                print(Colored.Colorize("Cache:        ", color='cyan') + f" {cache_status}")

        print()

        # Build order visualization
        self._projects_total = len(build_order)
        print(Colored.Colorize(f"Build Order ({self._projects_total} projects):", color='yellow', bold=True))

        for idx, (proj_name, proj_kind, deps) in enumerate(build_order, 1):
            kind_colored = Colored.Colorize(f"[{proj_kind}]", color='green')

            if deps:
                deps_str = ", ".join(deps)
                dep_info = Colored.Colorize(f" (depends: {deps_str})", color='magenta', dim=True)
            else:
                dep_info = ""

            arrow = " → " if idx < len(build_order) else ""
            print(f"  {idx}. {Colored.Colorize(proj_name, color='white', bold=True)} {kind_colored}{dep_info}{arrow}", end="")

            if idx < len(build_order):
                print()  # New line for next item
            else:
                print()  # Final newline

        print()

    def PrintFooter(self) -> None:
        """Print the global build footer with statistics."""
        elapsed = time.time() - self._start_time
        elapsed_str = f"{elapsed:.2f}s" if elapsed < 60 else f"{int(elapsed // 60)}m{elapsed % 60:.1f}s"

        w = 80
        success = self._projects_failed == 0

        print()
        print(Colored.Colorize("═" * w, color='cyan', bold=True))
        title = "BUILD COMPLETED" if success else "BUILD FAILED"
        color = 'green' if success else 'red'
        title_line = title.center(w)
        print(Colored.Colorize(title_line, color=color, bold=True))
        print(Colored.Colorize("═" * w, color='cyan', bold=True))

        # Statistics
        print(Colored.Colorize("Projects Built: ", color='cyan') + f" {self._projects_built}/{self._projects_total}")

        if self._projects_failed > 0:
            print(Colored.Colorize("Failed:        ", color='cyan') + f" {Colored.Colorize(str(self._projects_failed), color='red', bold=True)}")

        if self._total_errors > 0:
            print(Colored.Colorize("Errors:        ", color='cyan') + f" {Colored.Colorize(str(self._total_errors), color='red', bold=True)}")

        if self._total_warnings > 0:
            print(Colored.Colorize("Warnings:      ", color='cyan') + f" {Colored.Colorize(str(self._total_warnings), color='yellow', bold=True)}")

        print(Colored.Colorize("Time:          ", color='cyan') + f" {elapsed_str}")

        if success:
            status_text = Colored.Colorize("✓ SUCCESS", color='green', bold=True)
        else:
            status_text = Colored.Colorize("✗ FAILURE", color='red', bold=True)

        print(Colored.Colorize("Status:        ", color='cyan') + f" {status_text}")
        print(Colored.Colorize("═" * w, color='cyan', bold=True))
        print()

    def MarkProjectBuilt(self, success: bool) -> None:
        """Mark a project as built."""
        self._projects_built += 1
        if not success:
            self._projects_failed += 1

    def AccumulateStats(self, errors: int, warnings: int) -> None:
        """Accumulate error/warning counts from a project build."""
        self._total_errors += errors
        self._total_warnings += warnings
