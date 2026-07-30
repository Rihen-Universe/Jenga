#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jenga Global Configuration System
Gère la configuration globale utilisateur, toolchains personnalisés, et sysroots.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import platform

from .._version import __version__


class JengaConfig:
    """
    Gestionnaire de configuration globale Jenga.

    Structure:
    ~/.jenga/
        config.json          # Configuration principale
        toolchains/          # Toolchains personnalisés
            my-gcc.json
            my-clang.json
        sysroots/            # Sysroots enregistrés
            linux-x64/
            android-arm64/
        cache/               # Cache global
        logs/                # Logs de build
    """

    def __init__(self):
        self._config_dir = self._GetConfigDir()
        self._config_file = self._config_dir / "config.json"
        self._config = self._LoadConfig()
        self._EnsureDirectories()

    @staticmethod
    def _GetConfigDir() -> Path:
        """Retourne le répertoire de configuration Jenga."""
        # Optional override for CI/sandboxed environments.
        override = os.environ.get("JENGA_CONFIG_DIR") or os.environ.get("JENGA_HOME")
        if override:
            return Path(override).expanduser().resolve()

        if platform.system() == "Windows":
            # Windows: %USERPROFILE%/.jenga
            base = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
        else:
            # Linux/macOS: ~/.jenga
            base = Path.home()

        return base / ".jenga"

    def _LoadConfig(self) -> Dict[str, Any]:
        """Charge la configuration depuis config.json."""
        if self._config_file.exists():
            try:
                # 'utf-8-sig' : tolere un BOM UTF-8 (Notepad, PowerShell 5.1)
                # sur un fichier que l'utilisateur peut editer a la main.
                with open(self._config_file, 'r', encoding='utf-8-sig') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load config: {e}")
                return self._GetDefaultConfig()
        else:
            return self._GetDefaultConfig()

    def _GetDefaultConfig(self) -> Dict[str, Any]:
        """Configuration par défaut."""
        return {
            "version": __version__,
            "toolchains_paths": [],
            "sysroots_paths": [],
            "global_cache_enabled": True,
            "max_parallel_jobs": os.cpu_count() or 4,
            "default_toolchain": None,
            "verbose_errors": True,
            "auto_discover_toolchains": True,
            "user_settings": {}
        }

    def _EnsureDirectories(self):
        """Crée les répertoires nécessaires."""
        dirs = [
            self._config_dir,
            self._config_dir / "toolchains",
            self._config_dir / "sysroots",
            self._config_dir / "cache",
            self._config_dir / "logs"
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def Save(self):
        """Sauvegarde la configuration."""
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    # ============================================================
    # Toolchains
    # ============================================================

    def RegisterToolchain(self, name: str, toolchain_data: Dict[str, Any]) -> bool:
        """
        Enregistre un nouveau toolchain personnalisé.

        Args:
            name: Nom du toolchain (ex: "my-gcc-13")
            toolchain_data: Données du toolchain
                {
                    "type": "gcc",
                    "target": {"os": "Linux", "arch": "x86_64"},
                    "cc": "/usr/bin/gcc-13",
                    "cxx": "/usr/bin/g++-13",
                    "ar": "/usr/bin/ar",
                    "cflags": ["-march=native"],
                    "cxxflags": ["-std=c++20"],
                    "ldflags": []
                }
        """
        toolchain_file = self._config_dir / "toolchains" / f"{name}.json"
        try:
            with open(toolchain_file, 'w', encoding='utf-8') as f:
                json.dump(toolchain_data, f, indent=2)

            # Ajouter au config si pas déjà présent
            if str(toolchain_file) not in self._config.get("toolchains_paths", []):
                if "toolchains_paths" not in self._config:
                    self._config["toolchains_paths"] = []
                self._config["toolchains_paths"].append(str(toolchain_file))
                self.Save()

            return True
        except Exception as e:
            print(f"Error registering toolchain {name}: {e}")
            return False

    def GetToolchain(self, name: str) -> Optional[Dict[str, Any]]:
        """Récupère un toolchain par nom."""
        toolchain_file = self._config_dir / "toolchains" / f"{name}.json"
        if toolchain_file.exists():
            try:
                # 'utf-8-sig' : le fichier peut avoir ete depose/edite a la main.
                with open(toolchain_file, 'r', encoding='utf-8-sig') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading toolchain {name}: {e}")
        return None

    def ListToolchains(self) -> List[str]:
        """Liste tous les toolchains enregistrés."""
        toolchains_dir = self._config_dir / "toolchains"
        if not toolchains_dir.exists():
            return []

        return [f.stem for f in toolchains_dir.glob("*.json")]

    def RemoveToolchain(self, name: str) -> bool:
        """Supprime un toolchain."""
        toolchain_file = self._config_dir / "toolchains" / f"{name}.json"
        if toolchain_file.exists():
            try:
                toolchain_file.unlink()
                # Retirer de la config
                paths = self._config.get("toolchains_paths", [])
                self._config["toolchains_paths"] = [p for p in paths if not p.endswith(f"{name}.json")]
                self.Save()
                return True
            except Exception as e:
                print(f"Error removing toolchain {name}: {e}")
        return False

    # ============================================================
    # Sysroots
    # ============================================================

    def RegisterSysroot(self, name: str, path: str, target_os: str = "Linux", target_arch: str = "x86_64") -> bool:
        """
        Enregistre un nouveau sysroot.

        Args:
            name: Nom du sysroot (ex: "ubuntu-22.04-x64")
            path: Chemin absolu vers le sysroot
            target_os: OS cible
            target_arch: Architecture cible
        """
        sysroot_info = {
            "name": name,
            "path": str(Path(path).absolute()),
            "target_os": target_os,
            "target_arch": target_arch,
            "registered_date": str(Path(path).stat().st_mtime)
        }

        sysroot_file = self._config_dir / "sysroots" / f"{name}.json"
        try:
            with open(sysroot_file, 'w', encoding='utf-8') as f:
                json.dump(sysroot_info, f, indent=2)

            # Ajouter au config
            if "sysroots_paths" not in self._config:
                self._config["sysroots_paths"] = []
            if str(sysroot_file) not in self._config["sysroots_paths"]:
                self._config["sysroots_paths"].append(str(sysroot_file))
                self.Save()

            return True
        except Exception as e:
            print(f"Error registering sysroot {name}: {e}")
            return False

    def GetSysroot(self, name: str) -> Optional[Dict[str, Any]]:
        """Récupère un sysroot par nom."""
        sysroot_file = self._config_dir / "sysroots" / f"{name}.json"
        if sysroot_file.exists():
            try:
                # 'utf-8-sig' : idem toolchains, fichier editable a la main.
                with open(sysroot_file, 'r', encoding='utf-8-sig') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading sysroot {name}: {e}")
        return None

    def ListSysroots(self) -> List[str]:
        """Liste tous les sysroots enregistrés."""
        sysroots_dir = self._config_dir / "sysroots"
        if not sysroots_dir.exists():
            return []

        return [f.stem for f in sysroots_dir.glob("*.json")]

    def RemoveSysroot(self, name: str) -> bool:
        """Supprime un sysroot (seulement la référence, pas les fichiers)."""
        sysroot_file = self._config_dir / "sysroots" / f"{name}.json"
        if sysroot_file.exists():
            try:
                sysroot_file.unlink()
                # Retirer de la config
                paths = self._config.get("sysroots_paths", [])
                self._config["sysroots_paths"] = [p for p in paths if not p.endswith(f"{name}.json")]
                self.Save()
                return True
            except Exception as e:
                print(f"Error removing sysroot {name}: {e}")
        return False

    # ============================================================
    # Propriétés
    # ============================================================

    @property
    def config_dir(self) -> Path:
        """Répertoire de configuration."""
        return self._config_dir

    @property
    def cache_dir(self) -> Path:
        """Répertoire de cache."""
        return self._config_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        """Répertoire des logs."""
        return self._config_dir / "logs"

    def Get(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur de configuration."""
        return self._config.get(key, default)

    def Set(self, key: str, value: Any) -> bool:
        """Définit une valeur de configuration."""
        self._config[key] = value
        return self.Save()

    # ============================================================
    # Instance globale
    # ============================================================

    _instance: Optional['JengaConfig'] = None

    @classmethod
    def GetInstance(cls) -> 'JengaConfig':
        """Récupère l'instance globale (singleton)."""
        if cls._instance is None:
            cls._instance = JengaConfig()
        return cls._instance


# Fonction d'accès global
def GetGlobalConfig() -> JengaConfig:
    """Récupère la configuration globale Jenga."""
    return JengaConfig.GetInstance()
