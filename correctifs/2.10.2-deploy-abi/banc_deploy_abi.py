# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_deploy_abi.py : `jenga deploy --platform android --target <serial>` CHOISIT l'ABI d'apres l'appareil (05/11, 2.10.2, defaut h).
# Avant : `--platform Android` sans architecture = celle de l'HOTE (x86_64). Sur l'emulateur x86_64 (abilist « x86_64,arm64-v8a »)
# et un projet qui ne fournit que arm64-v8a (le kit publie), l'edition de liens echouait (« is incompatible with elf_x86_64 »).
# Maintenant : une ABI declaree que l'appareil accepte est construite (arm64 traduit sur l'image x86_64) et DITE ; sans ABI commune,
# on s'arrete AVANT toute construction, avec un message qui nomme les deux listes.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.2-deploy-abi/banc_deploy_abi.py
# CONTRE-EPREUVES : (1) le code de Deploy.py est rejoue SANS le choix (muté dans le meme binaire) : le banc voit la plateforme
# « Android » (l'hote) au lieu de « Android-arm64 » ; (2) un appareil sans ABI commune : pas de construction du tout.
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from Jenga.Commands.Deploy import DeployCommand as D, Process as DP

rouge = 0


def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1


C = D.ChooseAndroidAbi
EMU = ['x86_64', 'arm64-v8a']
t(C(['arm64-v8a'], EMU)[:2] == ('Android-arm64', 'arm64-v8a'), "emulateur x86_64 + projet arm64 seul : on construit arm64 (traduit)")
t(C(['x86_64'], EMU)[:2] == ('Android-x86_64', 'x86_64'), "emulateur x86_64 + projet x86_64 : x86_64")
t(C(['arm64-v8a', 'x86_64'], EMU)[:2] == ('Android', 'x86_64'), "plusieurs ABI declarees : paquet universel (plateforme sans architecture)")
t(C(['armeabi-v7a'], EMU)[2] is not None and 'armeabi-v7a' in C(['armeabi-v7a'], EMU)[2] and 'x86_64' in C(['armeabi-v7a'], EMU)[2],
  "aucune ABI commune : erreur qui NOMME l'ABI du projet et celles de l'appareil")
t(C([], EMU) == ('Android', None, None), "projet sans androidabis() : comportement d'avant")
t(C(['arm64-v8a'], []) == ('Android', None, None), "abilist illisible : comportement d'avant")
t(C(['arm64-v8a'], ['arm64-v8a'])[0] == 'Android-arm64', "telephone arm64 : arm64")


def deployer(declarees, abilist, deploy=D):
    journal = {'plateformes': [], 'install': 0, 'erreurs': []}
    parsed = SimpleNamespace(config='Release', jenga_file=None, verbose=False, no_daemon=True, target='emulator-5580',
                             bundle=None, run=False)

    def execute(cmd, **kw):
        return SimpleNamespace(returnCode=0, stdout=','.join(abilist))

    def build(args):
        journal['plateformes'].append(args[args.index('--platform') + 1])
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'Foo.apk').write_text('apk')
        faux = SimpleNamespace(GetTargetDir=lambda p: Path(tmp))
        with mock.patch.object(deploy, '_ResolveAdb', staticmethod(lambda ws: Path('adb'))), \
                mock.patch('Jenga.Commands.Build.BuildCommand.Execute', staticmethod(build)), \
                mock.patch('Jenga.Commands.Build.BuildCommand.CreateBuilder', staticmethod(lambda *a, **k: faux)), \
                mock.patch('Jenga.Commands.Build.BuildCommand.CollectFilterOptions', staticmethod(lambda **k: [])), \
                mock.patch.object(deploy, '_AndroidInstall', staticmethod(lambda adb, apk, target: journal.__setitem__('install', 1) or 0)), \
                mock.patch.object(DP, 'ExecuteCommand', staticmethod(execute)):
            code = deploy._DeployAndroid(SimpleNamespace(), SimpleNamespace(name='Foo', targetName='Foo', androidAbis=declarees), parsed)
    return code, journal


code, j = deployer(['arm64-v8a'], EMU)
t(code == 0 and j['plateformes'] == ['Android-arm64'] and j['install'] == 1, "deploy : construit Android-arm64 (et non l'hote) puis installe : %s" % j['plateformes'])
code, j = deployer(['armeabi-v7a'], EMU)
t(code == 1 and j['plateformes'] == [] and j['install'] == 0, "deploy, appareil sans ABI commune : AUCUNE construction, rien d'installe, code 1")

# CONTRE-EPREUVE : le meme code, SANS le choix (la ligne qui fixe la plateforme remise a « Android »), rejoue dans le meme binaire
src = Path(sys.modules[D.__module__].__file__).read_text(encoding='utf-8')
choix = "plateforme, abi, erreur = DeployCommand.ChooseAndroidAbi("
t(choix in src, "l'appel a retirer est bien dans Deploy.py (sinon la contre-epreuve ne mesure rien)")
mute = types.ModuleType('Jenga.Commands._Deploy_sans_choix')
mute.__package__ = 'Jenga.Commands'
mute.__file__ = 'Deploy_mute.py'
exec(compile(src.replace(choix, "plateforme, abi, erreur = (lambda declarees, appareil: ('Android', None, None))("), 'Deploy_mute.py', 'exec'), mute.__dict__)
code, j = deployer(['arm64-v8a'], EMU, mute.DeployCommand)
t(j['plateformes'] == ['Android'], "CONTRE-EPREUVE : sans le choix, deploy construit « Android » (l'hote, x86_64) : %s (le controle ROUGIT)" % j['plateformes'])
code, j = deployer(['armeabi-v7a'], EMU, mute.DeployCommand)
t(j['plateformes'] == ['Android'] and code == 0, "CONTRE-EPREUVE : sans le choix, un appareil sans ABI commune LANCE quand meme la construction (le lien rate)")
print('===== banc_deploy_abi : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
