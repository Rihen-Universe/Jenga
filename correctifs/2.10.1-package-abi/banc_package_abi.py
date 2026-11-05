# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_package_abi.py : `jenga package` (05/11, lot multi-ABI) : « --platform android-arm64 » et « --abi » sont lus, l'ABI se dit,
# un projet console est signale. Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.1-package-abi/banc_package_abi.py
# Le NEGATIF est dans le meme binaire : l'ancienne regle (refuser tout nom qui n'est pas un systeme nu) est rejouee et refuse bien
# « android-arm64 » ; les contradictions et les ABI inconnues sont refusees, jamais devinees.
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from Jenga.Commands.Package import PackageCommand as P

rouge = 0
def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi)
    if not ok:
        rouge += 1

sp = P.SplitPlatform
t(sp('android', None) == ('android', 'android', None), "android seul : aucune architecture imposee")
t(sp('Android-ARM64', None) == ('android', 'android-arm64', None), "android-arm64 (casse ignoree) est accepte et transmis")
t(sp('android', 'arm64-v8a') == ('android', 'android-arm64', None), "--abi arm64-v8a = android-arm64")
t(sp('android', 'armeabi-v7a') == ('android', 'android-arm', None), "--abi armeabi-v7a = android-arm")
t(sp('android', 'x86_64') == ('android', 'android-x86_64', None), "--abi x86_64")
t(sp('android', 'x86') == ('android', 'android-x86', None), "--abi x86")
t(sp('android-arm64', 'arm64-v8a') == ('android', 'android-arm64', None), "android-arm64 + --abi arm64-v8a : d'accord")
t(sp('android', 'arm64-v8a,x86_64') == ('android', 'android', None), "plusieurs ABI : le paquet universel (le projet declare androidabis)")
t(sp('android', 'all') == ('android', 'android', None), "--abi all : universel")
t(sp('android-arm64', 'x86_64')[2] is not None, "android-arm64 + --abi x86_64 : refuse (contradiction), pas devine")
t(sp('android', 'mips')[2] is not None, "une ABI inconnue est refusee")
t(sp('windows', 'x86_64')[2] is not None, "--abi sur windows est refuse")
t(sp('plan9', None)[2] is not None, "un systeme inconnu est refuse, avec la liste")
t(sp('harmonyos', 'arm64-v8a') == ('harmonyos', 'harmonyos-arm64', None), "harmonyos : --abi aussi")
# NEGATIF : l'ancienne regle d'argparse (choices = les systemes nus) refuse « android-arm64 »
ancien = ('android-arm64' in P.SUPPORTED_PLATFORMS)
t(not ancien, "NEGATIF : l'ancienne regle (choix = systemes nus) refusait android-arm64 ; la nouvelle l'accepte")
print('===== banc_package_abi : %s =====' % ('VERT' if rouge == 0 else 'ROUGE (%d)' % rouge))
sys.exit(1 if rouge else 0)
