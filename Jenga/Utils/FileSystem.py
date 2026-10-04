#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileSystem – Utilities for file and directory operations.
All public methods are PascalCase; private helpers are module‑level functions.
"""

import os
import shutil
import hashlib
import tempfile
from pathlib import Path
from typing import List, Union, Optional, Callable, Iterator
import fnmatch
import stat
import errno
import re

# ---------------------------------------------------------------------------
# Private helpers (module level) – _PascalCase
# ---------------------------------------------------------------------------

def _EnsureParentDirectory(filePath: Union[str, Path]) -> None:
    """Ensure the parent directory of a file exists."""
    Path(filePath).parent.mkdir(parents=True, exist_ok=True)

def _HandleRemoveReadonly(func: Callable, path: str, exc_info) -> None:
    """Handle readonly files on Windows during remove/rmtree."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def _GlobRecursive(root: Path, pattern: str, ignoreHidden: bool = True) -> Iterator[Path]:
    """Recursive glob that respects hidden‑file convention.

    Un motif qui nomme un dossier (il contient « / », ex. « src/**/*.cpp ») est
    ANCRE a `root` : « src » y est un enfant direct de la location (Path.glob).
    Un motif sans dossier (« *.obj ») reste cherche a toute profondeur
    (Path.rglob). Jusqu'a 2.8.9 tout passait par rglob, qui revient a
    « **/src/**/*.cpp » : un projet ramassait aussi les src/ de ses sous-dossiers
    (constate le 04/10/2026 quand des applications sont passees sous
    Engine/NKEditorKit/Applications/ : leurs main.cpp entraient dans la bibliotheque).
    """
    candidats = root.glob(pattern) if "/" in pattern else root.rglob(pattern)
    for path in candidats:
        if ignoreHidden:
            try:
                parts = path.relative_to(root).parts
            except ValueError:  # motif « ../autre/** » : hors de root
                parts = Path(os.path.relpath(path, root)).parts
            if any(part.startswith('.') and part not in ('.', '..') for part in parts):
                continue
        yield path

def _NormalizeGlobPattern(pattern: str) -> str:
    """
    Normalize permissive user patterns to pathlib-compatible globs.
    Examples:
      - **.cpp   -> **/*.cpp
      - src/**.h -> src/**/*.h
    """
    if not pattern:
        return "*"
    normalized = pattern.replace("\\", "/")
    # Common user shorthand used in samples: **.ext or src/**.ext
    normalized = normalized.replace("**.", "**/*.")
    # Generic fallback: if '**' is immediately followed by a non-separator token.
    normalized = re.sub(r"(^|/)\*\*([A-Za-z0-9_\\-])", r"\1**/*\2", normalized)
    return normalized

def _IsWorkspaceFile(filepath: Path) -> bool:
    """
    Vérifie si le fichier .jenga définit un workspace.
    Ignore les lignes commençant par # (commentaires Python).
    """
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        lines = content.splitlines()
        for line in lines:
            # Supprimer les commentaires (simplifié : on enlève tout après un # non protégé)
            # On ne gère pas les # dans les chaînes, mais c'est suffisant pour la détection.
            if '#' in line:
                line = line[:line.index('#')]
            line = line.strip()
            if re.search(r'with\s+workspace\s*\(', line):
                return True
            if re.search(r'workspace\s*=\s*Workspace\s*\(', line):
                return True
        return False
    except Exception:
        return False

def _CollectJengaFiles(directory: Path) -> List[Path]:
    """
    Collecte les fichiers .jenga UNIQUEMENT dans directory (non récursif),
    en excluant :
      - les dossiers (ex: le dossier de cache .jenga/)
      - les fichiers dont un composant du chemin absolu est ".jenga"
        (ex: .jenga/something.jenga dans le cache)

    Cette exclusion est la clé : Path.iterdir() ne descend pas dans les
    sous-dossiers, mais on vérifie quand même les composants pour être
    robuste face aux symlinks ou cas exotiques.
    """
    candidates: List[Path] = []
    try:
        for entry in directory.iterdir():
            # Fichiers uniquement — exclut le dossier .jenga/ lui-même
            if not entry.is_file():
                continue
            # Extension .jenga (insensible à la casse)
            if entry.suffix.lower() != ".jenga":
                continue
            # Exclure tout fichier dont l'un des composants du chemin est ".jenga"
            # Cela protège contre les fichiers de cache dans .jenga/
            if any(part == ".jenga" for part in entry.resolve().parts):
                continue
            candidates.append(entry)
    except PermissionError:
        pass
    return sorted(candidates)  # tri alphabétique stable et reproductible

def _PickBestJengaFile(candidates: List[Path], directory: Path) -> Optional[Path]:
    """
    Parmi une liste de fichiers .jenga, choisit le meilleur selon ces priorités :

      1. Fichier workspace valide dont le stem == nom exact du dossier.
         Ex : dossier NKWindow01/ → NKWindow01.jenga
      2. Fichier workspace valide dont le stem est un préfixe/suffixe du dossier.
         Ex : dossier NKWindow01/ → NKWindow.jenga
      3. Unique fichier workspace valide présent.
      4. Premier fichier valide alphabétiquement (fallback).

    "Valide" signifie que _IsWorkspaceFile() retourne True.
    """
    if not candidates:
        return None

    dir_name = directory.name

    # Séparer les fichiers workspace valides des autres
    workspace_files = [c for c in candidates if _IsWorkspaceFile(c)]
    if not workspace_files:
        return None

    # Priorité 1 : stem == nom exact du dossier
    for c in workspace_files:
        if c.stem == dir_name:
            return c

    # Priorité 2 : correspondance partielle (NKWindow dans NKWindow01, ou l'inverse)
    for c in workspace_files:
        if dir_name.startswith(c.stem) or c.stem.startswith(dir_name):
            return c

    # Priorité 3 : unique fichier workspace
    if len(workspace_files) == 1:
        return workspace_files[0]

    # Fallback : premier alphabétiquement
    return workspace_files[0]

# ---------------------------------------------------------------------------
# FileSystem class – all methods static
# ---------------------------------------------------------------------------

class FileSystem:

    @staticmethod
    def PathExists(path: Union[str, Path]) -> bool:
        """Check if a file or directory exists."""
        return Path(path).exists()

    @staticmethod
    def IsFile(path: Union[str, Path]) -> bool:
        """Check if path is a file."""
        return Path(path).is_file()

    @staticmethod
    def IsDirectory(path: Union[str, Path]) -> bool:
        """Check if path is a directory."""
        return Path(path).is_dir()

    @staticmethod
    def GetAbsolutePath(path: Union[str, Path]) -> str:
        """Return absolute path as string."""
        return str(Path(path).absolute())

    @staticmethod
    def GetRelativePath(path: Union[str, Path], start: Union[str, Path] = None) -> str:
        """Return relative path from start to path."""
        p = Path(path)
        if start is None:
            return str(p.relative_to(Path.cwd()))
        return str(p.relative_to(Path(start)))

    @staticmethod
    def NormalizePath(path: Union[str, Path]) -> str:
        """Normalize path separators to OS default."""
        return str(Path(path))

    @staticmethod
    def JoinPaths(*parts: Union[str, Path]) -> str:
        """Join path parts safely."""
        return str(Path(*parts))

    @staticmethod
    def MakeDirectory(path: Union[str, Path], existOk: bool = True) -> None:
        """Create directory and parents if needed."""
        Path(path).mkdir(parents=True, exist_ok=existOk)

    @staticmethod
    def RemoveDirectory(path: Union[str, Path], recursive: bool = False,
                        ignoreErrors: bool = False) -> None:
        """Remove directory (optionally recursive)."""
        p = Path(path)
        if not p.exists():
            if ignoreErrors:
                return
            raise FileNotFoundError(f"Directory not found: {path}")
        if recursive:
            shutil.rmtree(p,
                          onerror=_HandleRemoveReadonly if os.name == 'nt' else None,
                          ignore_errors=ignoreErrors)
        else:
            try:
                p.rmdir()
            except OSError as e:
                if e.errno == errno.ENOTEMPTY:
                    raise OSError(f"Directory not empty: {path}. Use recursive=True.")
                raise

    @staticmethod
    def RemoveFile(path: Union[str, Path], ignoreErrors: bool = False) -> None:
        """Remove a single file."""
        p = Path(path)
        if not p.exists():
            if ignoreErrors:
                return
            raise FileNotFoundError(f"File not found: {path}")
        if os.name == 'nt':
            os.chmod(p, stat.S_IWRITE)
        p.unlink()

    @staticmethod
    def CopyFile(src: Union[str, Path], dst: Union[str, Path],
                 overwrite: bool = True) -> None:
        """Copy a file, optionally overwrite."""
        srcPath = Path(src)
        dstPath = Path(dst)
        if not srcPath.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if not overwrite and dstPath.exists():
            raise FileExistsError(f"Destination exists and overwrite=False: {dst}")
        _EnsureParentDirectory(dstPath)
        shutil.copy2(srcPath, dstPath)

    @staticmethod
    def CopyDirectory(src: Union[str, Path], dst: Union[str, Path],
                      ignorePatterns: Optional[List[str]] = None,
                      overwrite: bool = True) -> None:
        """Copy entire directory."""
        srcPath = Path(src)
        dstPath = Path(dst)
        if not srcPath.is_dir():
            raise NotADirectoryError(f"Source not a directory: {src}")

        def _IgnoreFunc(path: str, names: List[str]) -> List[str]:
            if not ignorePatterns:
                return []
            ignored = set()
            for pattern in ignorePatterns:
                ignored.update(fnmatch.filter(names, pattern))
            return list(ignored)

        shutil.copytree(srcPath, dstPath,
                        ignore=_IgnoreFunc if ignorePatterns else None,
                        dirs_exist_ok=overwrite)

    @staticmethod
    def MoveFile(src: Union[str, Path], dst: Union[str, Path],
                 overwrite: bool = True) -> None:
        """Move or rename a file."""
        srcPath = Path(src)
        dstPath = Path(dst)
        if not srcPath.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if not overwrite and dstPath.exists():
            raise FileExistsError(f"Destination exists and overwrite=False: {dst}")
        _EnsureParentDirectory(dstPath)
        shutil.move(str(srcPath), str(dstPath))

    @staticmethod
    def ListFiles(directory: Union[str, Path], pattern: str = "*",
                  recursive: bool = False, fullPath: bool = False,
                  ignoreHidden: bool = True) -> List[str]:
        """
        List files matching pattern.
        Returns relative paths from directory unless fullPath=True.
        """
        root = Path(directory)
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        results = []
        normalized_pattern = _NormalizeGlobPattern(pattern)
        if recursive:
            for path in _GlobRecursive(root, normalized_pattern, ignoreHidden):
                if path.is_file():
                    results.append(str(path if fullPath else path.relative_to(root)))
        else:
            for path in root.glob(normalized_pattern):
                if path.is_file():
                    if ignoreHidden and path.name.startswith('.'):
                        continue
                    results.append(str(path if fullPath else path.relative_to(root)))
        return results

    @staticmethod
    def ListDirectories(directory: Union[str, Path], pattern: str = "*",
                        recursive: bool = False, fullPath: bool = False,
                        ignoreHidden: bool = True) -> List[str]:
        """List directories matching pattern."""
        root = Path(directory)
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        results = []
        normalized_pattern = _NormalizeGlobPattern(pattern)
        if recursive:
            for path in _GlobRecursive(root, normalized_pattern, ignoreHidden):
                if path.is_dir():
                    results.append(str(path if fullPath else path.relative_to(root)))
        else:
            for path in root.glob(normalized_pattern):
                if path.is_dir():
                    if ignoreHidden and path.name.startswith('.'):
                        continue
                    results.append(str(path if fullPath else path.relative_to(root)))
        return results

    @staticmethod
    def ReadFile(path: Union[str, Path], encoding: str = "utf-8") -> str:
        """Read text file content."""
        return Path(path).read_text(encoding=encoding)

    @staticmethod
    def WriteFile(path: Union[str, Path], content: str,
                  encoding: str = "utf-8", append: bool = False) -> None:
        """Write text content to file."""
        p = Path(path)
        _EnsureParentDirectory(p)
        mode = "a" if append else "w"
        with p.open(mode, encoding=encoding) as f:
            f.write(content)

    @staticmethod
    def ReadBinaryFile(path: Union[str, Path]) -> bytes:
        """Read binary file."""
        return Path(path).read_bytes()

    @staticmethod
    def WriteBinaryFile(path: Union[str, Path], data: bytes) -> None:
        """Write binary data to file."""
        p = Path(path)
        _EnsureParentDirectory(p)
        p.write_bytes(data)

    @staticmethod
    def GetFileSize(path: Union[str, Path]) -> int:
        """Return file size in bytes."""
        return Path(path).stat().st_size

    @staticmethod
    def GetModificationTime(path: Union[str, Path]) -> float:
        """Return last modification timestamp."""
        return Path(path).stat().st_mtime

    @staticmethod
    def ComputeFileHash(path: Union[str, Path], algorithm: str = "md5") -> str:
        """Compute hash of file content (md5, sha1, sha256)."""
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def ComputeStringHash(content: str, algorithm: str = "md5") -> str:
        """Compute hash of a string."""
        hasher = hashlib.new(algorithm)
        hasher.update(content.encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def MakeTemporaryDirectory(prefix: str = "jenga_") -> str:
        """Create a temporary directory and return its path."""
        return tempfile.mkdtemp(prefix=prefix)

    @staticmethod
    def MakeTemporaryFile(suffix: str = "", prefix: str = "jenga_",
                          text: bool = False) -> str:
        """Create a temporary file and return its path."""
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, text=text)
        os.close(fd)
        return path

    @staticmethod
    def FindExecutable(name: str) -> Optional[str]:
        """Find an executable in PATH."""
        return shutil.which(name)

    @staticmethod
    def IsSameFile(path1: Union[str, Path], path2: Union[str, Path]) -> bool:
        """Check if two paths refer to the same file (symlink‑aware)."""
        try:
            return os.path.samefile(path1, path2)
        except OSError:
            return False

    @staticmethod
    def Glob(pattern: str, root: Union[str, Path] = ".",
             recursive: bool = False) -> List[str]:
        """
        Glob files matching pattern relative to root.
        Returns absolute paths.
        """
        rootPath = Path(root).resolve()
        if recursive and '**' in pattern:
            return [str(p) for p in rootPath.glob(pattern) if p.is_file()]
        return [str(p) for p in rootPath.glob(pattern) if p.is_file()]

    @staticmethod
    def EnsureTrailingSlash(path: Union[str, Path]) -> str:
        """Ensure directory path ends with separator."""
        s = str(path)
        if s and s[-1] not in (os.sep, os.altsep):
            return s + os.sep
        return s

    @staticmethod
    def RemoveTrailingSlash(path: Union[str, Path]) -> str:
        """Remove trailing separator if present."""
        s = str(path)
        while s and s[-1] in (os.sep, os.altsep):
            s = s[:-1]
        return s

    @staticmethod
    def FindWorkspaceEntry(start_dir: Optional[Path] = None) -> Optional[Path]:
        """
        Trouve le fichier d'entrée du workspace Jenga en remontant depuis start_dir.

        Stratégie par niveau :
          1. Chercher les fichiers .jenga FICHIERS uniquement (pas les dossiers),
             en excluant tout fichier dont un composant du chemin est ".jenga"
             (le dossier de cache Jenga).
          2. Parmi les candidats, choisir le meilleur via _PickBestJengaFile() :
               a. Stem == nom exact du dossier courant
               b. Correspondance partielle stem/dossier
               c. Unique fichier workspace valide
               d. Premier alphabétiquement
          3. Si rien trouvé à ce niveau, remonter d'un niveau et recommencer.

        Exemple :
          Dossier NKWindow01/ contient NKWindow.jenga et .jenga/ (cache)
          → Retourne NKWindow.jenga  (correspondance partielle NKWindow / NKWindow01)

        Args:
            start_dir: Répertoire de départ (défaut: Path.cwd()).

        Returns:
            Path absolu du fichier .jenga workspace, ou None si introuvable.
        """
        if start_dir is None:
            start_dir = Path.cwd()

        current = Path(start_dir).resolve()
        visited: set = set()

        while True:
            if current in visited:
                break
            visited.add(current)

            candidates = _CollectJengaFiles(current)
            if candidates:
                result = _PickBestJengaFile(candidates, current)
                if result is not None:
                    return result

            parent = current.parent
            if parent == current:
                # Racine du système de fichiers atteinte
                break
            current = parent

        return None