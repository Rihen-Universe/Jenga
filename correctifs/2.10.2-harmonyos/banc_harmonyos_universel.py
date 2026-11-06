# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_harmonyos_universel.py : HarmonyOS (05/11, 2.10.2, defauts f et g).
#   (f) `jenga package --platform harmonyos` passe par Build() du constructeur (le chemin de `jenga build`), plus de libs/arm64-v8a
#       en dur ni de hvigor sans projet ;
#   (g) le HAP universel existe SANS --target quand le workspace a une cible de demarrage ou une seule application graphique ;
#       sinon (plusieurs applications multi-ABI, pas de demarrage) un message clair.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.2-harmonyos/banc_harmonyos_universel.py
# Des FAUX constructeurs : ni hvigor ni SDK. La VRAIE preuve (HAP universel, ABI lues dans le .hap) est dans ETAT_emulateurs-reels.md.
# CONTRE-EPREUVES : le code de Package.py et de HarmonyOs.py est rejoue MUTE (l'ancien comportement) dans le meme binaire.
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from Jenga.Commands.Package import PackageCommand as P
from Jenga.Core.Builders import HarmonyOs as H
from Jenga.Core.Api import ProjectKind

rouge = 0


def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1


# ---------------------------------------------------------------- (g)
def faux_builder(apps, depart=None, classe=H.HarmonyOsBuilder):
    """apps : {nom: [abis]} ; un HarmonyOsBuilder sans __init__ (aucun SDK)."""
    b = object.__new__(classe)
    projets = {n: SimpleNamespace(name=n, kind=ProjectKind.WINDOWED_APP, harmonyAbis=a, dependsOn=[]) for n, a in apps.items()}
    b.workspace = SimpleNamespace(projects=projets, startProject=depart)
    b.universels = []
    b._BuildUniversalHAP = lambda proj, abis: b.universels.append((proj.name, list(abis))) or True
    return b


ABIS = ['arm64-v8a', 'x86_64']
b = faux_builder({'Jeu': ABIS})
t(b.InferUniversalTarget() == ('Jeu', None), "(g) une seule application multi-ABI : elle est la cible, sans --target")
b = faux_builder({'Jeu': ABIS, 'Outil': []}, depart='Jeu')
t(b.InferUniversalTarget() == ('Jeu', None), "(g) plusieurs applications : la cible de demarrage")
b = faux_builder({'Jeu': ABIS, 'Autre': ABIS})
cible, erreur = b.InferUniversalTarget()
t(cible is None and erreur and 'Jeu' in erreur and 'Autre' in erreur and '--target' in erreur,
  "(g) plusieurs applications multi-ABI, pas de demarrage : message clair qui les nomme et dit quoi faire")
b = faux_builder({'Jeu': ['arm64-v8a']})
t(b.InferUniversalTarget() == (None, None), "(g) une seule ABI declaree : comportement d'avant (pas d'universel)")
b = faux_builder({'Jeu': ABIS})
code = b.Build(None)
t(b.universels == [('Jeu', ABIS)], "(g) Build() SANS cible construit le HAP universel : %s" % b.universels)

# CONTRE-EPREUVE (g) : le source de HarmonyOs.py sans l'inference rend l'ancien comportement
src = Path(H.__file__).read_text(encoding='utf-8')
fragment = "            cible, erreur = self.InferUniversalTarget()"
t(fragment in src, "(g) la ligne d'inference a retirer est bien dans HarmonyOs.py")
mute = types.ModuleType('Jenga.Core.Builders._HarmonyOs_sans_inference')
mute.__package__ = 'Jenga.Core.Builders'
mute.__file__ = 'HarmonyOs_mute.py'
exec(compile(src.replace(fragment, "            cible, erreur = None, None"), 'HarmonyOs_mute.py', 'exec'), mute.__dict__)
bm = faux_builder({'Jeu': ABIS}, classe=mute.HarmonyOsBuilder)
try:
    bm.Build(None)
except Exception:
    pass  # la suite (super().Build) a besoin d'un vrai workspace : seul compte le fait que l'universel n'ait PAS ete lance
t(bm.universels == [], "CONTRE-EPREUVE (g) : sans l'inference, Build() sans cible NE construit PAS le HAP universel (l'ancien defaut)")

# ---------------------------------------------------------------- (f)


class FauxConstructeur:
    def __init__(self, dossier):
        self.d = Path(dossier)
        self.appels = []

    def GetTargetDir(self, projet):
        return self.d

    def Build(self, nom):
        self.appels.append('Build:' + nom)
        (self.d / 'Foo.hap').write_text('hap')
        return 0

    def BuildProject(self, projet):
        self.appels.append('BuildProject')
        return True


def paqueter(fonction, abis):
    appels_hvigor = []
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as sortie:
        c = FauxConstructeur(tmp)
        projet = SimpleNamespace(name='Foo', targetName='Foo', harmonyAbis=abis, location=tmp)
        with mock.patch('subprocess.run', lambda *a, **k: appels_hvigor.append(a) or SimpleNamespace(returncode=1)):
            try:
                code = fonction(projet, c, 'hap', Path(sortie))
            except Exception as e:  # l'ancien chemin cherche les .so
                code = 'exception %s' % type(e).__name__
        return code, c.appels, appels_hvigor, (Path(sortie) / 'Foo.hap').exists(), (Path(tmp) / 'libs').exists()


code, appels, hvigor, copie, libs = paqueter(P._PackageHarmonyOS, ABIS)
t(code == 0 and appels == ['Build:Foo'] and copie and not hvigor and not libs,
  "(f) package harmonyos : Build() du constructeur (le chemin de `jenga build`), .hap copie, ni libs/arm64-v8a ni hvigor direct : %s" % appels)
code, appels, hvigor, copie, libs = paqueter(P._PackageHarmonyOS, [])
t(code == 0 and appels == ['Build:Foo'], "(f) une ABI : meme chemin")
code, appels, hvigor, copie, libs = paqueter(P._PackageHarmonyOSAncien, ABIS)
t(appels == ['BuildProject'] and (hvigor or libs or code != 0),
  "CONTRE-EPREUVE (f) : l'ANCIEN corps compile sans projet hvigor et lance hvigor dans le dossier du projet (%s) : le defaut est bien celui-la" % code)
print('===== banc_harmonyos_universel : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
