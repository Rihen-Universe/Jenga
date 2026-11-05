# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_kit_abi.py : `jenga kit` SEPARE LES ABI (05/11, lot multi-ABI). Avant, lib/<config>-<systeme> recevait TOUTES les
# architectures d'un meme systeme (arm64-v8a et x86_64 d'Android, arm64 et x86_64 de macOS) : la derniere ecrasait les autres.
# Maintenant lib/<config>-<systeme>-<arch>, et le .jenga du kit choisit par `architecture:`.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.1-kit-abi/banc_kit_abi.py
# Le NEGATIF est dans le meme binaire : l'ancienne cle (le systeme seul) est rejouee, et le banc voit les deux ABI se confondre.
import os, sys, tempfile, shutil, py_compile
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from Jenga.Commands.Kit import KitCommand as K

rouge = 0
def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1

class Proj:
    def __init__(self, n, deps=()):
        self.name = n
        self.dependsOn = list(deps)

class Ws:
    name = "Faux"
    projects = {"Noyau": Proj("Noyau"), "App": Proj("App", ["Noyau"])}

def ecrire(cle_de):
    """Fabrique un kit pour android-arm64 et android-x86_64 ; rend (dossier, texte du .jenga, cles)."""
    tmp = Path(tempfile.mkdtemp())
    plats = ["Android-arm64", "Android-x86_64"]
    libs, sys_, ext = {}, {}, {}
    for pf in plats:
        cle = cle_de(pf)
        dest = tmp / "lib" / ("Release-%s" % cle)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "libNoyau.a").write_text("x")
        libs[("Release", cle)] = {"Noyau": "libNoyau.a", "App": "libApp.a"}
        sys_[("Release", cle)] = []
        ext[("Release", cle)] = []
    fichier = tmp / "Faux.jenga"
    K._WriteKitConfig(fichier, "Faux", Ws, ["App", "Noyau"], ["App", "Noyau"], libs, sys_, ext, {}, {})
    return tmp, fichier.read_text(encoding="utf-8"), sorted({c for (_x, c) in libs}), sorted(p.name for p in (tmp / "lib").iterdir())

# --- la cle d'une cible
t(K._KeyOf("Android-arm64") == "Android-arm64", "la cle d'une cible porte l'architecture")
t(K._KeyOf("Windows") == "Windows", "sans architecture, la cle est le systeme (rien ne change pour Windows)")
t(K._OsOf("Android-arm64") == "Android" and K._ArchOfKey("Android-arm64") == "arm64", "le systeme et l'architecture se relisent dans la cle")
# --- le kit de deux ABI
tmp, texte, cles, dossiers = ecrire(K._KeyOf)
t(dossiers == ["Release-Android-arm64", "Release-Android-x86_64"], "DEUX dossiers de bibliotheques, un par ABI : %s" % dossiers)
t('filter("system:Android && architecture:arm64 && configurations:Release")' in texte, "le .jenga choisit arm64 par `architecture:`")
t('filter("system:Android && architecture:x86_64 && configurations:Release")' in texte, "le .jenga choisit x86_64 par `architecture:`")
t(texte.count('libdirs([KIT_ROOT + "/lib/Release-Android-arm64"])') == 1 and texte.count('libdirs([KIT_ROOT + "/lib/Release-Android-x86_64"])') == 1,
  "chaque bloc a ses propres libdirs (jamais l'autre ABI)")
t('"Android": ""' in texte and '"Android-arm64": ""' not in texte, "KIT_STDLIB / KIT_COMPILER restent par SYSTEME (kitrequire(system=...))")
try:
    py_compile.compile(str(tmp / "Faux.jenga"), cfile=str(tmp / "x.pyc"), doraise=True)
    t(True, "le .jenga ecrit est du Python valide")
except Exception as e:
    t(False, "le .jenga ecrit est du Python valide : %s" % e)
shutil.rmtree(tmp, ignore_errors=True)
# --- NEGATIF : l'ancienne cle (le systeme seul) confond les deux ABI
tmp2, texte2, cles2, dossiers2 = ecrire(lambda p: K._OsOf(p))
t(len(dossiers2) == 1, "NEGATIF : avec l'ancienne cle (le systeme seul) les deux ABI tombent dans UN dossier : %s" % dossiers2)
shutil.rmtree(tmp2, ignore_errors=True)
print('===== banc_kit_abi : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
