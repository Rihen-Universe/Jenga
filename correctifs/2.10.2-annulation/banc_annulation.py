# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
# banc_annulation.py : L'ANNULATION COOPERATIVE D'UNE CONSTRUCTION (06/11, 2.10.2) -- Jenga.Core.Cancel, Utils/Process.py, Core/Builder.py,
# Core/Embed.py. NKCode embarque Jenga : son bouton « Arreter » pose un drapeau, Jenga le lit entre deux unites de compilation et
# entre deux projets, termine les compilateurs / editeurs de liens QU'IL A LANCES (jamais d'autres processus) et rend « Construction
# arretee » avec le code 130 (distinct de l'echec, 1).
#
# S1 (VRAI compilateur) : six sources lourdes (~5 s chacune, <regex>), deux en parallele ; la sonde de l'hote se leve 1,5 s apres
#   le debut de la compilation. (a) le resultat est « arretee », code 130 ; (b) la ligne « Construction arretee » est dite ; (c) la
#   construction rend la main en moins de 3 s ; (d) AUCUN compilateur enfant ne reste (lu par numero de processus, dans le dossier
#   du banc) ; (e) aucune erreur de compilation comptee ; (f) aucun .obj sans sa signature (« a moitie ecrit ») ; (g) aucun fichier
#   n'est rendu « compile » apres la demande ; (h) la construction SUIVANTE repart et reussit, et le programme tourne.
# S2 (injecte) : la compilation d'un fichier est interrompue en plein ecriture de l'objet (un fichier de 7 octets est ecrit, puis
#   BuildCancelled -- ce que fait Process.ExecuteCommand quand l'enfant est termine) : l'objet a moitie ecrit est RETIRE.
# Lancer depuis la racine de Jenga-abi :  py -3 -I correctifs/2.10.2-annulation/banc_annulation.py [--contre-epreuve]
# S3 (SOUS-PROCESSUS) : NKCode lance parfois `jenga` en sous-processus (python -m Jenga) : l'hote demande l'arret en CREANT le fichier
#   nomme par JENGA_CANCEL_FILE ; la CLI rend 130 avec « Construction arretee », sans compilateur restant (par numero), puis la
#   construction suivante reussit.
# S4 (DEMON) : un demon tourne (sous-processus) et construit a la place du client ; le client relaie l'annulation (commande « cancel »)
#   au demon, qui termine SES compilateurs ; le client rend 130. Le demon NKCode n'est pas utilise par NKCode (--no-daemon en
#   embarque) : c'est la CLI `jenga build` d'un terminal qui y passe.
# CONTRE-EPREUVES (mutées dans le meme binaire) : sans-arret-enfants (Request ne termine pas les enfants), drapeau-ignore (Request ne
# fait rien), sans-nettoyage (l'objet a moitie ecrit reste), fichier-drapeau-ignore (S3/S4 : la variable n'est pas donnee, comme un
# Jenga qui ne la lirait pas), demon-sans-relais (S4 : le demon ignore « cancel ») : chacune doit faire ROUGIR le banc.
# CODES : 0 vert (ou contre-epreuve reussie), 1 rouge, 2 instrument casse.
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from Jenga.Core import Cancel, Embed  # noqa: E402
from Jenga.Core.Builder import Builder  # noqa: E402
from Jenga.Utils.Process import Process  # noqa: E402

rouge = 0
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:  # noqa: BLE001
    pass


def t(ok, quoi):
    global rouge
    print(('[ OK ] ' if ok else '[FAIL] ') + quoi, flush=True)
    if not ok:
        rouge += 1


MUTATION = ''
for a in sys.argv[1:]:
    if a.startswith('--mutation='):
        MUTATION = a.split('=', 1)[1]
if MUTATION == 'sans-arret-enfants':
    Cancel._KillTree = lambda proc: None
elif MUTATION == 'drapeau-ignore':
    Cancel.Request = lambda: None
elif MUTATION == 'sans-nettoyage':
    Builder._RetirerSortiesPartielles = lambda self, sortie: None

LOURD = '''#include <regex>
#include <map>
#include <functional>
#include <iostream>
#include <sstream>
#include <algorithm>
int f%d(const std::string &s) { std::regex r("a+b*"); std::smatch m; std::map<std::string, std::function<int(int)>> t; t["x"] = [](int v){return v+%d;};
	std::ostringstream o; o << s; return std::regex_search(s, m, r) ? t["x"](1) : (int)o.str().size(); }
'''


def espace(dossier, n, lourd):
    """Un workspace jetable : une application console de `n` sources."""
    W = Path(dossier)
    (W / 'App' / 'src').mkdir(parents=True, exist_ok=True)
    (W / 'Annul.jenga').write_text(
        'from Jenga import *\nfrom Jenga.GlobalToolchains import RegisterJengaGlobalToolchains\n\n'
        'with workspace("Annul"):\n    RegisterJengaGlobalToolchains()\n    configurations(["Debug"])\n'
        '    targetoses([TargetOS.WINDOWS])\n    targetarchs([TargetArch.X86_64])\n    startproject("App")\n\n'
        '    with project("App"):\n        consoleapp()\n        language("C++")\n        cppdialect("C++17")\n'
        '        location("App/")\n        files(["src/**.cpp"])\n', encoding='utf-8')
    decl = ''
    for i in range(n):
        (W / 'App' / 'src' / ('f%d.cpp' % i)).write_text(LOURD % (i, i) if lourd else 'int f%d() { return %d; }\n' % (i, i), encoding='utf-8')
        decl += ('int f%d(const std::string &);\n' % i) if lourd else ''
    if lourd:
        appels = ' + '.join('f%d(std::string("ab"))' % i for i in range(n))
        (W / 'App' / 'src' / 'main.cpp').write_text('#include <cstdio>\n#include <string>\n' + decl +
                                                    'int main() { std::printf("annul ok %%d\\n", %s); return 0; }\n' % appels, encoding='utf-8')
    else:
        decl2 = ''.join('int f%d();\n' % i for i in range(n))
        (W / 'App' / 'src' / 'main.cpp').write_text(decl2 + '#include <cstdio>\nint main() { std::printf("annul ok\\n"); return 0; }\n', encoding='utf-8')
    return W / 'Annul.jenga'


def processus_du_dossier(dossier):
    """Les numeros de processus dont la ligne de commande nomme le dossier du banc (lu par PowerShell : Get-Process est aveugle)."""
    motif = str(dossier).replace('\\', '/').lower()
    cmd = ("Get-CimInstance Win32_Process | ForEach-Object { if ($_.CommandLine) { $_.ProcessId.ToString() + '|' + $_.CommandLine } }")
    r = subprocess.run(['powershell.exe', '-NoProfile', '-Command', cmd], capture_output=True, text=True, creationflags=0x08000000)
    pids = []
    for ligne in r.stdout.splitlines():
        if '|' in ligne and motif in ligne.split('|', 1)[1].replace('\\', '/').lower() and 'powershell' not in ligne.lower():
            pids.append(ligne.split('|', 1)[0])
    return pids


class Puits:
    """Le sink de l'hote : compte les fichiers finis, garde les lignes, note l'instant du debut de compilation."""
    def __init__(self):
        self.lignes = []
        self.finis = []
        self.t_debut = None
        self.t_demande = None
        self.compiles_apres = 0
        self.erreurs = 0
        self.vus = []

    def OnFileTotal(self, p, n):
        if self.t_debut is None:
            self.t_debut = time.time()

    def OnFileDone(self, p, i, n, f, ok, warned):
        self.finis.append(f)
        if self.t_demande is not None and ok:
            self.compiles_apres += 1

    def OnCompileError(self, p, f, m):
        self.erreurs += 1

    def OnLogLine(self, ligne):
        self.lignes.append(ligne)

    def OnProjectTotal(self, n): pass
    def OnProjectDone(self, ok): pass
    def OnProjectSkipped(self, p, b): pass
    def OnCompileWarning(self, p, f, m): pass
    def OnLinkError(self, p, f, m): self.erreurs += 1


def scenario1():
    D = Path(tempfile.mkdtemp(prefix='annul_s1_'))
    try:
        entree = espace(D, 5, lourd=True)
        puits = Puits()
        drapeau = {'leve': False}
        Embed.SetCancelProbe(lambda: drapeau['leve'])

        def leve_plus_tard():
            while puits.t_debut is None:
                time.sleep(0.05)
            time.sleep(1.0)
            puits.vus = processus_du_dossier(D)  # les compilateurs VIVANTS au moment de la demande (preuve que l'instrument les voit)
            puits.t_demande = time.time()
            drapeau['leve'] = True
        th = threading.Thread(target=leve_plus_tard, daemon=True)
        th.start()
        res = Embed.Build(jenga_file=str(entree), target='App', config='Debug', jobs=2, sink=puits)
        t_rendu = time.time()
        th.join(timeout=1)
        latence = (t_rendu - puits.t_demande) if puits.t_demande else 999.0
        restes = processus_du_dossier(D)
        print('[banc]   exit %s annulee %s latence %.2f s, compiles apres la demande %d, processus restants %s, erreurs %d' %
              (res.exitCode, res.cancelled, latence, puits.compiles_apres, restes, puits.erreurs), flush=True)
        t(res.cancelled and res.exitCode == Embed.CANCEL_EXIT_CODE == 130, "(a) la construction est ARRETEE : cancelled, code 130 (distinct de l'echec 1)")
        t(any('Construction arretee' in l for l in puits.lignes), "(b) « Construction arretee » est dit dans la sortie")
        t(latence < 3.0, "(c) la construction rend la main moins de 3 s apres la demande (les unites en vol sont terminees, pas attendues)")
        t(len(puits.vus) > 0, "(d0) l'instrument VOIT des compilateurs vivants au moment de la demande (%d)" % len(puits.vus))
        t(not restes and Cancel.ChildCount() == 0, "(d) aucun compilateur enfant ne reste (lu par numero de processus dans le dossier du banc)")
        t(puits.erreurs == 0 and not res.errorFiles and not res.hadLinkFailure, "(e) aucune erreur de compilation ni de lien n'est comptee")
        objets = [p for p in D.rglob('src_*') if p.suffix in ('.obj', '.o')]
        sans_sig = [p.name for p in objets if not Path(str(p) + '.jenga_sig').exists()]
        t(not sans_sig, "(f) aucun objet sans sa signature (a moitie ecrit) : %s" % (sans_sig or 'aucun'))
        t(puits.compiles_apres == 0, "(g) aucun fichier n'est rendu « compile » apres la demande (les unites en vol ont ete terminees)")
        # (h) la construction suivante repart et reussit
        drapeau['leve'] = False
        Embed.SetCancelProbe(None)
        puits2 = Puits()
        res2 = Embed.Build(jenga_file=str(entree), target='App', config='Debug', jobs=4, sink=puits2)
        exe = next(iter(D.rglob('App.exe')), None)
        sortie = ''
        if exe:
            sortie = subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip()
        t(res2.exitCode == 0 and not res2.cancelled and exe is not None and sortie.startswith('annul ok'),
          "(h) la construction SUIVANTE repart et reussit (code %s) : le programme dit « %s »" % (res2.exitCode, sortie))
    finally:
        Embed.SetCancelProbe(None)
        time.sleep(0.3)
        shutil.rmtree(D, ignore_errors=True)


def scenario2():
    D = Path(tempfile.mkdtemp(prefix='annul_s2_'))
    reel = Process.ExecuteCommand
    try:
        entree = espace(D, 3, lourd=False)
        cible = {'obj': None}

        def interrompu(args, *a, **k):
            if isinstance(args, list) and '-c' in [str(x) for x in args] and any(str(x).endswith('f1.cpp') for x in args):
                sortie = [str(x) for x in args]
                if '-o' in sortie:
                    cible['obj'] = Path(sortie[sortie.index('-o') + 1])
                    cible['obj'].parent.mkdir(parents=True, exist_ok=True)
                    cible['obj'].write_bytes(b'PARTIEL')  # l'objet a moitie ecrit quand l'enfant est termine
                    raise Cancel.BuildCancelled()
            return reel(args, *a, **k)
        Process.ExecuteCommand = staticmethod(interrompu)
        res = Embed.Build(jenga_file=str(entree), target='App', config='Debug', jobs=1, sink=Puits())
        Process.ExecuteCommand = reel
        t(cible['obj'] is not None, "(s2.0) l'instrument a bien interrompu la compilation de f1.cpp en plein ecriture")
        t(res.cancelled, "(s2.1) la construction est dite arretee")
        t(cible['obj'] is not None and not cible['obj'].exists(), "(s2.2) l'objet a moitie ecrit est RETIRE (il ne sera jamais pris pour bon)")
        res2 = Embed.Build(jenga_file=str(entree), target='App', config='Debug', jobs=1, sink=Puits())
        t(res2.exitCode == 0, "(s2.3) la construction suivante recompile ce fichier et reussit (code %s)" % res2.exitCode)
    finally:
        Process.ExecuteCommand = reel
        shutil.rmtree(D, ignore_errors=True)


RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
CMD_BUILD = ['build', '--config', 'Debug', '--platform', 'Windows-x86_64']


def attendre_compilateurs(D, delai):
    """Attend qu'au moins un compilateur du dossier D vive ; rend la liste (ou [])."""
    fin = time.time() + delai
    while time.time() < fin:
        v = processus_du_dossier(D)
        if v:
            return v
        time.sleep(0.2)
    return []


def scenario3():
    D = Path(tempfile.mkdtemp(prefix='annul_s3_'))
    try:
        entree = espace(D, 5, lourd=True)
        drapeau = D / 'stop.flag'
        env = dict(os.environ)
        if MUTATION != 'fichier-drapeau-ignore':
            env['JENGA_CANCEL_FILE'] = str(drapeau)
        p = subprocess.Popen([sys.executable, '-m', 'Jenga'] + CMD_BUILD + ['--jenga-file', str(entree), '--no-daemon'], cwd=RACINE, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        vus = attendre_compilateurs(D, 40)
        time.sleep(0.5)
        t0 = time.time()
        drapeau.write_text('stop')
        try:
            sortie, _ = p.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            p.kill()
            sortie, _ = p.communicate()
        latence = time.time() - t0
        restes = processus_du_dossier(D)
        print('[banc]   S3 : exit %s latence %.2f s, compilateurs vus %d, restants %s' % (p.returncode, latence, len(vus), restes), flush=True)
        t(len(vus) > 0, "(s3.0) l'instrument VOIT des compilateurs vivants avant la demande (%d)" % len(vus))
        t(p.returncode == 130 and 'Construction arretee' in sortie, "(s3.1) la CLI sous-processus rend 130 et dit « Construction arretee » (code %s)" % p.returncode)
        t(latence < 4.0, "(s3.2) elle rend la main moins de 4 s apres la creation du fichier (%.2f s)" % latence)
        t(not restes, "(s3.3) aucun compilateur ne reste (lu par numero) : %s" % (restes or 'aucun'))
        objets = [q for q in D.rglob('src_*') if q.suffix in ('.obj', '.o')]
        sans_sig = [q.name for q in objets if not Path(str(q) + '.jenga_sig').exists()]
        t(not sans_sig, "(s3.4) aucun objet a moitie ecrit : %s" % (sans_sig or 'aucun'))
        drapeau.unlink()
        env2 = dict(os.environ)
        env2.pop('JENGA_CANCEL_FILE', None)
        r2 = subprocess.run([sys.executable, '-m', 'Jenga'] + CMD_BUILD + ['--jenga-file', str(entree), '--no-daemon'], cwd=RACINE, env=env2,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
        t(r2.returncode == 0, "(s3.5) la construction SUIVANTE reussit (code %s)" % r2.returncode)
    finally:
        time.sleep(0.3)
        shutil.rmtree(D, ignore_errors=True)


DEMON = """
import sys, time
from pathlib import Path
from Jenga.Core.Daemon import Daemon
if %r == 'demon-sans-relais':
    _orig = Daemon._ExecuteCommand
    def _sans(self, request):
        if request.get('command') == 'cancel':
            return {'status': 'ok', 'message': 'ignored (mutation)'}
        return _orig(self, request)
    Daemon._ExecuteCommand = _sans
d = Daemon(Path(%r), Path(%r))
sys.exit(1) if not d.Start() else None
while True:
    time.sleep(0.5)
"""


def scenario4():
    D = Path(tempfile.mkdtemp(prefix='annul_s4_'))
    demon = None
    try:
        entree = espace(D, 5, lourd=True)
        demon = subprocess.Popen([sys.executable, '-c', DEMON % (MUTATION, str(D), str(entree))], cwd=RACINE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        info = D / '.jenga' / 'daemon' / 'daemon.json'
        for _ in range(100):
            if info.exists():
                break
            time.sleep(0.2)
        t(info.exists(), "(s4.0) le demon tourne (daemon.json ecrit)")
        drapeau = D / 'stop.flag'
        env = dict(os.environ)
        if MUTATION != 'fichier-drapeau-ignore':
            env['JENGA_CANCEL_FILE'] = str(drapeau)
        # SANS --no-daemon : le client passe par le demon
        p = subprocess.Popen([sys.executable, '-m', 'Jenga'] + CMD_BUILD + ['--jenga-file', str(entree)], cwd=str(D), env=dict(env, PYTHONPATH=RACINE),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        vus = attendre_compilateurs(D, 40)
        time.sleep(0.5)
        t0 = time.time()
        drapeau.write_text('stop')
        try:
            sortie, _ = p.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            p.kill()
            sortie, _ = p.communicate()
        latence = time.time() - t0
        time.sleep(0.5)
        restes = processus_du_dossier(D)
        restes = [x for x in restes if demon is None or str(x) != str(demon.pid)]
        print('[banc]   S4 : exit %s latence %.2f s, compilateurs vus %d, restants %s' % (p.returncode, latence, len(vus), restes), flush=True)
        t('Using build daemon' in sortie, "(s4.1) le client est PASSE par le demon (« Using build daemon »)")
        t(p.returncode == 130 and 'Construction arretee' in sortie, "(s4.2) le client rend 130 et dit « Construction arretee » (code %s)" % p.returncode)
        t(not restes, "(s4.3) aucun compilateur du demon ne reste (lu par numero) : %s" % (restes or 'aucun'))
    finally:
        if demon is not None:
            demon.kill()  # NOTRE demon (Popen), par son numero
        time.sleep(0.3)
        shutil.rmtree(D, ignore_errors=True)


if '--contre-epreuve' in sys.argv:
    ok = True
    for m in ('sans-arret-enfants', 'drapeau-ignore', 'sans-nettoyage', 'fichier-drapeau-ignore', 'demon-sans-relais'):
        r = subprocess.run([sys.executable, '-I', os.path.abspath(__file__), '--mutation=' + m], capture_output=True, text=True, encoding='utf-8')
        vus = [l for l in r.stdout.splitlines() if l.startswith('[FAIL]')]
        print('=== contre-epreuve « %s » : %s (%d temoin(s) rouge(s))' % (m, 'a rougi -- REUSSI' if r.returncode == 1 and vus else 'N\'A PAS ROUGI -- ECHEC', len(vus)), flush=True)
        for l in vus:
            print('      ' + l[:150])
        ok = ok and r.returncode == 1 and bool(vus)
    sys.exit(0 if ok else 1)

if MUTATION in ('', 'sans-arret-enfants', 'drapeau-ignore'):
    scenario1()
if MUTATION in ('', 'sans-nettoyage'):
    scenario2()
if MUTATION in ('', 'fichier-drapeau-ignore'):
    scenario3()
if MUTATION in ('', 'fichier-drapeau-ignore', 'demon-sans-relais'):
    scenario4()
print('[banc-annulation] VERDICT : %s%s' % ('VERT' if rouge == 0 else 'ROUGE', (' (mutation %s)' % MUTATION) if MUTATION else ''))
sys.exit(0 if rouge == 0 else 1)
