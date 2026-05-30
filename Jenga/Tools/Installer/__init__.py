"""
Jenga Installer — système d'installateur self-extracting multi-plateforme.

Produit un exécutable d'installation autonome (stub C compilé + payload) sans
aucune dépendance externe. Voir DESIGN.md.

API principale : Builder.BuildInstaller(...).
"""
from .Builder import BuildInstaller, DetectCCompiler, BuilderError
from .Signing import SignBinary, HasSigningInfo, SigningError, SignResult
from .Resource import CompileWindowsResource, RenderUacManifest, RenderVersionInfoRc
from .Branding import ComposeInstallerIcon, IsAvailable as IsBrandingAvailable

__all__ = [
    "BuildInstaller", "DetectCCompiler", "BuilderError",
    "SignBinary", "HasSigningInfo", "SigningError", "SignResult",
    "CompileWindowsResource", "RenderUacManifest", "RenderVersionInfoRc",
    "ComposeInstallerIcon", "IsBrandingAvailable",
]
