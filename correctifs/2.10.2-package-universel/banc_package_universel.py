# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_package_universel.py : `jenga package` Android et `jenga deploy --run` (05/11, lot multi-ABI, 2.10.2).
#   (c) `--abi a,b` DONNE la liste des ABI et le paquet universel passe par Build() (une construction par ABI) ;
#   (d) une seule ABI : libc++_shared.so est ajoutee AVANT BuildAPK ;
#   (e) `deploy --run` en mode workspace LANCE l'application apres l'installation.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.2-package-universel/banc_package_universel.py
# Des FAUX constructeur, adb et processus : le banc n'a besoin ni du NDK ni d'un appareil. La VRAIE preuve est sur emulateur
# (voir ETAT_emulateurs-reels.md). CONTRE-EPREUVES : chaque defaut est rejoue en remettant l'ancien comportement dans le meme
# binaire ; le banc doit alors ROUGIR.
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from Jenga.Commands.Package import PackageCommand as P
from Jenga.Commands.Deploy import DeployCommand as D, Process as DP

rouge = 0


def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1


# ---- (c) la liste donnee
t(P.AbisDemandees('arm64-v8a,x86_64') == ['arm64-v8a', 'x86_64'], "(c) --abi arm64-v8a,x86_64 : la liste est lue, dans l'ordre donne")
t(P.AbisDemandees('x86_64, arm64') == ['x86_64', 'arm64-v8a'], "(c) les espaces et les alias (arm64) sont acceptes")
t(P.AbisDemandees('x86_64,x86_64') == ['x86_64'], "(c) pas de doublon")
t(P.AbisDemandees('all') == [] and P.AbisDemandees(None) == [], "(c) `all` ou rien : le projet declare ses ABI")


class FauxConstructeur:
    ndk_abi = 'arm64-v8a'

    def __init__(self, dossier):
        self.d = Path(dossier)
        self.appels = []
        (self.d / 'libFoo.so').write_text('so')

    def GetTargetDir(self, projet):
        return self.d

    def BuildAAB(self, projet, libs):  # _PackageAndroid exige les deux methodes
        return True

    def Build(self, nom):
        self.appels.append('Build')
        (self.d / 'Foo.apk').write_text('apk universel')
        return 0

    def BuildProject(self, projet):
        self.appels.append('BuildProject')
        return True

    def _AppendSharedStl(self, projet, abi, libs):
        self.appels.append('Stl:' + abi)
        return True

    def BuildAPK(self, projet, libs):
        self.appels.append('BuildAPK')
        (self.d / 'Foo.apk').write_text('apk')
        return True


def paqueter(abis, constructeur_cls=FauxConstructeur):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as sortie:
        c = constructeur_cls(tmp)
        projet = SimpleNamespace(name='Foo', targetName='Foo', androidAbis=abis)
        code = P._PackageAndroid(projet, c, 'apk', Path(sortie))
        return code, c.appels, (Path(sortie) / 'Foo.apk').exists()


code, appels, copie = paqueter(['arm64-v8a', 'x86_64'])
t(code == 0 and appels == ['Build'] and copie, "(c) deux ABI : Build() (l'universel), ni BuildProject ni BuildAPK, l'APK est copie : %s" % appels)
code, appels, copie = paqueter(['arm64-v8a'])
t(code == 0 and appels == ['BuildProject', 'Stl:arm64-v8a', 'BuildAPK'] and copie,
  "(d) une ABI : libc++_shared.so est ajoutee AVANT BuildAPK : %s" % appels)
code, appels, copie = paqueter([])
t(code == 0 and appels[:2] == ['BuildProject', 'Stl:arm64-v8a'], "(d) aucune ABI declaree : meme chemin, meme libc++_shared")


class SansLibcxx(FauxConstructeur):
    def _AppendSharedStl(self, projet, abi, libs):
        self.appels.append('Stl-refuse')
        return False


code, appels, copie = paqueter(['arm64-v8a'], SansLibcxx)
t(code == 1 and 'BuildAPK' not in appels and not copie, "(d) libc++_shared.so introuvable : l'APK n'est PAS fabrique (il mourrait au lancement)")

# ---- CONTRE-EPREUVE (c) : l'ancien comportement (la liste jetee) rejoue dans le meme binaire
with mock.patch.object(P, 'AbisDemandees', staticmethod(lambda abi: [])):
    projet = SimpleNamespace(androidAbis=['arm64-v8a'])
    demandees = P.AbisDemandees('arm64-v8a,x86_64')
    if len(demandees) > 1:
        projet.androidAbis = demandees
    t(projet.androidAbis == ['arm64-v8a'], "CONTRE-EPREUVE (c) : sans la lecture de la liste, le paquet reste a UNE ABI (l'ancien defaut)")
# CONTRE-EPREUVE (d), POUR DE VRAI : on RETIRE du code de Package.py l'appel qui ajoute libc++_shared.so, on recharge ce
# code muté dans le même binaire, et le MEME controle (« libc++_shared.so est ajoutee AVANT BuildAPK ») doit ROUGIR.
import importlib
import types
src = Path(sys.modules[P.__module__].__file__).read_text(encoding='utf-8')
appel = ("if hasattr(builder, '_AppendSharedStl') and not builder._AppendSharedStl(project, builder.ndk_abi, libs):"
         + chr(10) + "            return 1")
t(appel in src, "(d) l'appel a retirer est bien dans Package.py (sinon la contre-epreuve ne mesure rien)")
mute = types.ModuleType('Jenga.Commands._Package_sans_libcxx')
mute.__package__ = 'Jenga.Commands'
mute.__file__ = 'Package_mute.py'
exec(compile(src.replace(appel, 'pass'), 'Package_mute.py', 'exec'), mute.__dict__)
with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as sortie:
    c = FauxConstructeur(tmp)
    mute.PackageCommand._PackageAndroid(SimpleNamespace(name='Foo', targetName='Foo', androidAbis=['arm64-v8a']), c, 'apk', Path(sortie))
    sans = c.appels
t(sans == ['BuildProject', 'BuildAPK'], "CONTRE-EPREUVE (d) : sans l'appel retire, le controle voit BuildAPK SANS libc++_shared.so : %s (le banc ROUGIT)" % sans)
t(sans != ['BuildProject', 'Stl:arm64-v8a', 'BuildAPK'], "CONTRE-EPREUVE (d) : la sequence attendue par le controle (d) n'est PAS celle du code mute")


# ---- (e) deploy --run en mode workspace
def deployer(run):
    journal = []
    parsed = SimpleNamespace(config='Release', jenga_file=None, verbose=False, no_daemon=True, target='emulator-5580',
                             bundle=None, run=run)

    def execute(cmd, **kw):
        journal.append(cmd)
        return SimpleNamespace(returnCode=0, stdout='x86_64,arm64-v8a')
    with tempfile.TemporaryDirectory() as tmp:
        apk = Path(tmp) / 'Foo.apk'
        apk.write_text('apk')
        faux = SimpleNamespace(GetTargetDir=lambda p: Path(tmp))
        with mock.patch.object(D, '_ResolveAdb', staticmethod(lambda ws: Path('adb'))), \
                mock.patch('Jenga.Commands.Build.BuildCommand.Execute', staticmethod(lambda a: 0)), \
                mock.patch('Jenga.Commands.Build.BuildCommand.CreateBuilder', staticmethod(lambda *a, **k: faux)), \
                mock.patch('Jenga.Commands.Build.BuildCommand.CollectFilterOptions', staticmethod(lambda **k: [])), \
                mock.patch.object(D, '_AndroidInstall', staticmethod(lambda adb, apk, target: journal.append('install') or 0)), \
                mock.patch.object(D, '_GetApkPackageId', staticmethod(lambda adb, apk: 'com.exemple.app')), \
                mock.patch.object(DP, 'ExecuteCommand', staticmethod(execute)):
            code = D._DeployAndroid(SimpleNamespace(), SimpleNamespace(name='Foo', targetName='Foo'), parsed)
    return code, journal


code, j = deployer(True)
lance = any(isinstance(x, list) and 'monkey' in x and 'com.exemple.app' in x and '-s' in x and 'emulator-5580' in x for x in j)
t(code == 0 and [x for x in j if x == 'install'] and j.index('install') < min(i for i, x in enumerate(j) if isinstance(x, list) and 'monkey' in x) and lance, "(e) --run : installe PUIS lance (adb -s emulator-5580 shell monkey -p com.exemple.app)")
code, j = deployer(False)
t(code == 0 and 'install' in j and not any(isinstance(x, list) and 'monkey' in x for x in j), "(e) sans --run : installe seulement, ne lance pas")
print('===== banc_package_universel : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
