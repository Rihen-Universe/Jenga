# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_secret_harmony.py : `harmonykeypwd("env:NOM")` et `harmonykeypwd("file:chemin")` marchent (07/11, 2.10.3), comme androidkeystorepass.
# Le mot de passe ne figure donc ni dans le .jenga ni dans le depot ; il est lu a l'instant de signer. UNE CLE JETABLE : la valeur ci-dessous
# n'a jamais protege rien. Aucun java, aucun vrai outil : subprocess.run est remplace pour capter la commande de signature.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.3-secret-harmony/banc_secret_harmony.py
# CONTRE-EPREUVE : le code de HarmonyOs.py rejoue SANS la resolution : la commande recoit « env:... » tel quel (le defaut d'avant) : le banc ROUGIT.
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import importlib
H = importlib.import_module('Jenga.Core.Builders.HarmonyOs')

SECRET = 'jetable-Zx9-pas-un-vrai-mot-de-passe'
rouge = 0


def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1


def classe(mod):
    for nom in dir(mod):
        c = getattr(mod, nom)
        if isinstance(c, type) and hasattr(c, '_SignHAP'):
            return c
    raise SystemExit('classe de signature introuvable')


def signer(mod, pwd):
    """Appelle _SignHAP avec un projet dont harmonyKeyPwd = pwd ; rend (resultat, commande captee)."""
    cls = classe(mod)
    b = object.__new__(cls)
    b._FindHapSignTool = lambda: Path('hap-sign-tool.jar')
    vus = []

    def faux_run(cmd, **kw):
        vus.append(cmd)
        return SimpleNamespace(returncode=1, stderr='faux outil', stdout='')
    ancien = mod.subprocess.run
    mod.subprocess.run = faux_run
    try:
        p = SimpleNamespace(harmonyCertFile='c.cer', harmonyProfile='p.p7b', harmonyKeystore='k.p12', harmonyKeyAlias='cle', harmonyKeyPwd=pwd)
        res = b._SignHAP(p, Path('x.hap'))
    finally:
        mod.subprocess.run = ancien
    return res, (vus[0] if vus else None), p


def valeur(cmd):
    return cmd[cmd.index('-keyPwd') + 1] if cmd else None


os.environ['NK_BANC_MOT_DE_PASSE'] = SECRET
res, cmd, p = signer(H, 'env:NK_BANC_MOT_DE_PASSE')
t(valeur(cmd) == SECRET, "env:NOM : la commande de signature recoit la valeur de la variable")
t(p.harmonyKeyPwd == 'env:NK_BANC_MOT_DE_PASSE', "env:NOM : le projet (donc le .jenga) ne garde que la REFERENCE, jamais la valeur")

with tempfile.TemporaryDirectory() as d:
    f = Path(d) / 'mdp.txt'
    f.write_text(SECRET + '\n', encoding='utf-8')
    res, cmd, p = signer(H, 'file:' + f.as_posix())
    t(valeur(cmd) == SECRET, "file:chemin : la premiere ligne du fichier (sans fin de ligne)")
    vide = Path(d) / 'vide.txt'
    vide.write_text('\n', encoding='utf-8')
    res, cmd, _ = signer(H, 'file:' + str(vide))
    t(res is False and cmd is None, "file: vide : refus, aucune signature lancee")
    res, cmd, _ = signer(H, 'file:' + str(Path(d) / 'absent.txt'))
    t(res is False and cmd is None, "file: absent : refus, aucune signature lancee")
os.environ.pop('NK_BANC_MOT_DE_PASSE')
res, cmd, _ = signer(H, 'env:NK_BANC_MOT_DE_PASSE')
t(res is False and cmd is None, "env: non definie : refus (jamais un mot de passe vide par erreur)")
res, cmd, _ = signer(H, 'en-clair')
t(valeur(cmd) == 'en-clair', "sans prefixe : inchange (compatibilite)")

# CONTRE-EPREUVE : HarmonyOs.py sans la resolution
src = Path(H.__file__).read_text(encoding='utf-8')
ancre = 'key_pwd = self._ResolveSecret(key_pwd)'
t(ancre in src, "l'ancre de la mutation est dans HarmonyOs.py (sinon la contre-epreuve ne mesure rien)")
mute = types.ModuleType('Jenga.Core.Builders._HarmonyOs_sans_secret')
mute.__package__ = 'Jenga.Core.Builders'
mute.__file__ = 'HarmonyOs_mute.py'
exec(compile(src.replace(ancre, 'pass'), 'HarmonyOs_mute.py', 'exec'), mute.__dict__)
os.environ['NK_BANC_MOT_DE_PASSE'] = SECRET
res, cmd, _ = signer(mute, 'env:NK_BANC_MOT_DE_PASSE')
t(valeur(cmd) != SECRET, "CONTRE-EPREUVE : sans la resolution, la commande recoit « env:... » tel quel (l'ancien defaut : le banc ROUGIT)")
print('===== banc_secret_harmony : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
