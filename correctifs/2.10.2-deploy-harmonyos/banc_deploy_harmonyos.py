# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_deploy_harmonyos.py : `jenga deploy --platform harmonyos --target 127.0.0.1:5555 --run` (06/11, 2.10.2).
#   - `hdc tconn <adresse>` d'abord (sans lui `list targets` rend [Empty]) ;
#   - l'ABI se CHOISIT d'apres l'appareil (`param get const.product.cpu.abilist`) au lieu de `harmonyos-arm64` en dur ;
#   - `hdc install <nom.hap>` depuis LE DOSSIER du .hap (hdc prefixe le dossier courant a un chemin absolu Windows) ;
#   - `aa start -a EntryAbility -b <bundle> -m entry`, et le RESULTAT de aa start se lit (hdc rend 0 meme si l'ability ne demarre pas).
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.2-deploy-harmonyos/banc_deploy_harmonyos.py
# Des FAUX hdc et constructeur. CONTRE-EPREUVES : le code de Deploy.py rejoue MUTE (plateforme en dur ; `-m entry` retire).
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


C = D.ChooseHarmonyAbi
EMU = ['x86_64']
t(C([], EMU)[:2] == ('harmonyos-x86_64', 'x86_64'), "emulateur x86_64, rien de declare : on construit x86_64 (pas arm64 en dur)")
t(C([], ['arm64-v8a'])[:2] == ('harmonyos-arm64', 'arm64-v8a'), "telephone arm64, rien de declare : arm64")
t(C(['arm64-v8a'], EMU)[2] is not None and 'arm64-v8a' in C(['arm64-v8a'], EMU)[2] and 'x86_64' in C(['arm64-v8a'], EMU)[2],
  "emulateur x86_64 + projet arm64 seul : erreur qui nomme les deux listes (pas de traduction sur HarmonyOS)")
t(C(['arm64-v8a', 'x86_64'], EMU)[:2] == ('harmonyos', 'x86_64'), "plusieurs ABI declarees : universel")
t(C(['x86_64'], EMU)[:2] == ('harmonyos-x86_64', 'x86_64'), "projet x86_64 sur emulateur x86_64 : x86_64")
t(C(['arm64-v8a'], [])[0] == 'harmonyos-arm64' and C(['arm64-v8a'], [])[2] is None, "abilist illisible : comportement d'avant")


def deployer(declarees, abilist, aa_sortie='start ability successfully.', deploy=D):
    j = {'plateformes': [], 'cmds': [], 'cwd': None}

    def execute(cmd, **kw):
        j['cmds'].append(list(cmd))
        if 'install' in cmd:
            j['cwd'] = kw.get('cwd')
        if 'abilist' in ' '.join(cmd):
            return SimpleNamespace(returnCode=0, stdout=','.join(abilist), stderr='')
        if 'aa' in cmd:
            return SimpleNamespace(returnCode=0, stdout=aa_sortie, stderr='')
        return SimpleNamespace(returnCode=0, stdout='', stderr='')

    def build(args):
        j['plateformes'].append(args[args.index('--platform') + 1])
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'Foo.hap').write_text('hap')
        faux = SimpleNamespace(GetTargetDir=lambda p: Path(tmp))
        parsed = SimpleNamespace(config='Release', jenga_file=None, verbose=False, no_daemon=True, target='127.0.0.1:5555',
                                 bundle='com.exemple.foo', ability=None, run=True, uninstall=False)
        with mock.patch.object(deploy, '_ResolveHdc', staticmethod(lambda ws: Path('hdc'))), \
                mock.patch('Jenga.Commands.Build.BuildCommand.Execute', staticmethod(build)), \
                mock.patch('Jenga.Commands.Build.BuildCommand.CreateBuilder', staticmethod(lambda *a, **k: faux)), \
                mock.patch('Jenga.Commands.Build.BuildCommand.CollectFilterOptions', staticmethod(lambda **k: [])), \
                mock.patch.object(DP, 'ExecuteCommand', staticmethod(execute)):
            code = deploy._DeployHarmonyOS(SimpleNamespace(), SimpleNamespace(name='Foo', targetName='Foo', harmonyAbis=declarees), parsed)
        j['dossier_hap'] = tmp
    return code, j


code, j = deployer([], EMU)
t(code == 0 and j['plateformes'] == ['harmonyos-x86_64'], "deploy : construit harmonyos-x86_64 (l'ABI de l'emulateur) : %s" % j['plateformes'])
t(j['cmds'][0][:2] == ['hdc', 'tconn'] and j['cmds'][0][2] == '127.0.0.1:5555', "deploy : `hdc tconn 127.0.0.1:5555` est la PREMIERE commande")
inst = [c for c in j['cmds'] if 'install' in c]
t(len(inst) == 1 and inst[0][-1] == 'Foo.hap' and str(j['cwd']) == j['dossier_hap'], "deploy : `hdc install Foo.hap` depuis le dossier du .hap (nom relatif)")
aa = [c for c in j['cmds'] if 'aa' in c]
t(len(aa) == 1 and aa[0][-2:] == ['-m', 'entry'] and '-b' in aa[0] and 'com.exemple.foo' in aa[0], "deploy : `aa start -a EntryAbility -b <bundle> -m entry`")
code, j = deployer([], EMU, aa_sortie='error: failed to start ability.')
t(code == 1, "deploy : un `aa start` qui affiche « error » est un ECHEC (hdc rend 0 pourtant)")
code, j = deployer(['arm64-v8a'], EMU)
t(code == 1 and j['plateformes'] == [] and not [c for c in j['cmds'] if 'install' in c], "deploy, sans ABI commune : aucune construction, rien d'installe")

# CONTRE-EPREUVES : le code de Deploy.py rejoue MUTE
src = Path(sys.modules[D.__module__].__file__).read_text(encoding='utf-8')


def muter(ancien, nouveau, nom):
    t(ancien in src, "l'ancre de la mutation « %s » est dans Deploy.py (sinon la contre-epreuve ne mesure rien)" % nom)
    m = types.ModuleType('Jenga.Commands._Deploy_mute_' + nom)
    m.__package__ = 'Jenga.Commands'
    m.__file__ = 'Deploy_mute.py'
    exec(compile(src.replace(ancien, nouveau), 'Deploy_mute.py', 'exec'), m.__dict__)
    return m.DeployCommand


mute1 = muter("plateforme, abi, erreur = DeployCommand.ChooseHarmonyAbi(",
              "plateforme, abi, erreur = (lambda d, a: ('harmonyos-arm64', None, None))(", 'abi_en_dur')
code, j = deployer([], EMU, deploy=mute1)
t(j['plateformes'] == ['harmonyos-arm64'], "CONTRE-EPREUVE : sans le choix, deploy construit harmonyos-arm64 pour un emulateur x86_64 (le defaut) : %s" % j['plateformes'])
mute2 = muter('"-m", "entry",', '', 'sans_module')
code, j = deployer([], EMU, deploy=mute2)
aa = [c for c in j['cmds'] if 'aa' in c]
t(aa and aa[0][-2:] != ['-m', 'entry'], "CONTRE-EPREUVE : sans `-m entry`, la commande aa start n'est plus celle qui a marche (le controle ROUGIT)")
print('===== banc_deploy_harmonyos : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
