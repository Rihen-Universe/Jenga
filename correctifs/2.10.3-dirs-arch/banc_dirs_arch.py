# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_dirs_arch.py : les dossiers de sortie Android et HarmonyOS sont SEPARES par architecture (07/11, 2.10.3, defaut a du 05/11).
# Avant : `targetdir(".../Build/Lib/%{cfg.buildcfg}-%{cfg.system}")` (chaque module de Nkentseu) donnait Release-Android pour arm64 ET x86_64 :
# la construction x86_64 ecrasait les .a arm64. Maintenant arm64 garde son dossier (les kits publies en dependent), les autres
# architectures ajoutent leur nom : Release-Android-x86_64.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.3-dirs-arch/banc_dirs_arch.py
# CONTRE-EPREUVE : le code de Builder.py rejoue SANS le suffixe : x86_64 et arm64 retombent dans le MEME dossier (le defaut).
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import Jenga.Core.Builder
BM = sys.modules['Jenga.Core.Builder']
if not hasattr(BM, '__file__'):
    import importlib
    BM = importlib.import_module('Jenga.Core.Builder')
from Jenga.Core.Api import TargetArch

rouge = 0


def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1


def concret(classe):
    """Builder est abstrait : une sous-classe vide des methodes abstraites suffit (aucune compilation ici)."""
    return type('BuilderBanc', (classe,), {n: (lambda *a, **k: None) for n in classe.__abstractmethods__})


def builder(classe, plateforme, arch):
    b = object.__new__(concret(classe))
    b.platform = plateforme
    b.targetArch = arch
    b.workspace = SimpleNamespace(location='C:/ws')
    b._expander = None
    return b


def projet(cible, obj):
    return SimpleNamespace(name='NKCore', targetDir=cible, objDir=obj, kind=None)


LIB = 'C:/ws/Build/Lib/Release-Android'
OBJ = 'C:/ws/Build/Obj/Release-Android/NKCore'
arm = builder(BM.Builder, 'Android-arm64', TargetArch.ARM64)
x86 = builder(BM.Builder, 'Android-x86_64', TargetArch.X86_64)
p = projet(LIB, OBJ)
t(arm.GetTargetDir(p).name == 'Release-Android', "arm64 : le dossier des bibliotheques ne bouge pas (Release-Android)")
t(arm.GetObjectDir(p).parent.name == 'Release-Android', "arm64 : le dossier des objets ne bouge pas")
t(x86.GetTargetDir(p).name == 'Release-Android-x86_64', "x86_64 : Release-Android-x86_64 (plus de collision) : %s" % x86.GetTargetDir(p).name)
t(x86.GetObjectDir(p).parent.name == 'Release-Android-x86_64' and x86.GetObjectDir(p).name == 'NKCore', "x86_64 : les objets aussi : %s" % x86.GetObjectDir(p))
t(arm.GetTargetDir(p) != x86.GetTargetDir(p), "arm64 et x86_64 n'ecrasent plus le meme dossier")
t(builder(BM.Builder, 'Android-arm', TargetArch.ARM).GetTargetDir(p).name == 'Release-Android-arm', "arm 32 bits : son propre dossier")
h = builder(BM.Builder, 'HarmonyOS-x86_64', TargetArch.X86_64)
t(h.GetTargetDir(projet('C:/ws/Build/Lib/Release-HarmonyOS', OBJ)).name == 'Release-HarmonyOS-x86_64', "HarmonyOS x86_64 : meme regle")
win = builder(BM.Builder, 'Windows', TargetArch.X86_64)
t(win.GetTargetDir(projet('C:/ws/Build/Lib/Release-Windows', OBJ)).name == 'Release-Windows', "Windows : rien ne change")
t(x86.GetTargetDir(projet('C:/ws/Build/Lib/Release-Android-x86_64', OBJ)).name == 'Release-Android-x86_64', "un dossier deja separe (build universel) n'est pas suffixe deux fois")

# CONTRE-EPREUVE : Builder.py sans le suffixe
src = Path(BM.__file__).read_text(encoding='utf-8')
ancre = 'return "" if arch in ("", "arm64") else "-" + arch'
t(ancre in src, "l'ancre de la mutation est dans Builder.py (sinon la contre-epreuve ne mesure rien)")
mute = types.ModuleType('Jenga.Core._Builder_sans_suffixe')
mute.__package__ = 'Jenga.Core'
mute.__file__ = 'Builder_mute.py'
exec(compile(src.replace(ancre, 'return ""'), 'Builder_mute.py', 'exec'), mute.__dict__)
x86m = builder(mute.Builder, 'Android-x86_64', TargetArch.X86_64)
t(x86m.GetTargetDir(p) == builder(mute.Builder, 'Android-arm64', TargetArch.ARM64).GetTargetDir(p),
  "CONTRE-EPREUVE : sans le suffixe, x86_64 et arm64 retombent dans le MEME dossier (l'ancien defaut : le banc ROUGIT)")
print('===== banc_dirs_arch : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
