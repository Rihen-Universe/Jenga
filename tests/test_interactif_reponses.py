# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
"""
(2.11.0) Ce que l'utilisateur repond en mode interactif arrive dans le .jenga.

Trois defauts constates le 18/11/2026 avec Jenga 2.10.3 (agent du cours, seances reelles) :

1. `jenga file <projet> -i` sur un projet range dans SON fichier (`jenga project X --separate`) :
   « Project block for 'Jeu' not found », code 1. Add._AppendToProjectBlock ne cherchait le bloc
   `with project("Jeu"):` que dans le fichier du workspace ; il vit dans Jeu/Jeu.jenga.
2. `jenga workspace -i` demande le compilateur prefere puis ne l'ecrit nulle part (la variable
   `compiler` n'etait passee a personne). 2.11.0 l'ecrit : prefercompiler("gcc"), lu par le builder.
3. Meme chose pour « Enable unit testing (Unitest)? » : la reponse oui laissait le bloc unitest en
   commentaire. 2.11.0 l'ecrit actif, en mode Compile (le mode Precompiled attend une
   Unitest/libs/Unitest.lib que le paquet ne fournit pas).

Les seances passent par les vraies commandes (Execute / _RunInteractive) ; input() est nourri par une
liste de reponses, exactement comme un terminal. Contre-epreuve : sur le code 2.10.3, chacun des cas
« defaut » tombe ; les temoins (projet inline, Auto-detect, tests non) passent des deux cotes.
"""
import argparse
import builtins
from pathlib import Path

import pytest

import Jenga.Core.Api as Api
from Jenga.Core.Api import CompilerFamily, TargetArch, TargetEnv, TargetOS, Toolchain, Workspace
from Jenga.Core.Loader import Loader


def _reset():
    Api._currentWorkspace = None
    Api._currentProject = None
    Api._currentToolchain = None
    Api._currentFilter = None


@pytest.fixture(autouse=True)
def _etat_propre():
    _reset()
    yield
    _reset()


def _reponses(monkeypatch, reponses):
    """input() rend les reponses une a une ; une question de trop fait echouer le test."""
    file = iter(reponses)
    lues = []

    def entree(question=""):
        try:
            r = next(file)
        except StopIteration:
            raise AssertionError(f"question imprevue : {question!r}")
        lues.append(r)
        return r

    monkeypatch.setattr(builtins, "input", entree)
    return lues


def _charger(entry: Path):
    _reset()
    return Loader(verbose=False).LoadWorkspace(str(entry))


def _workspace(tmp_path: Path, nom="W") -> Path:
    from Jenga.Commands.Init import InitCommand
    ns = argparse.Namespace(name=nom, path=str(tmp_path), configs="Debug,Release",
                            oses="Windows", archs="x86_64")
    assert InitCommand._RunDirect(ns) == 0
    return tmp_path / nom / f"{nom}.jenga"


def _projet(entry: Path, nom: str, separe: bool, location="."):
    from Jenga.Commands.Create import CreateCommand
    ns = argparse.Namespace(name=nom, kind="console", lang="C++", location=location,
                            dialect="C++17", separate=separe)
    assert CreateCommand._CreateProjectDirect(ns, entry) == 0


def _file(monkeypatch, entry: Path, args, reponses=()):
    from Jenga.Commands.Add import AddCommand
    monkeypatch.chdir(entry.parent)
    _reponses(monkeypatch, list(reponses))
    _reset()
    return AddCommand.Execute(args + ["--jenga-file", str(entry)])


# ---------------------------------------------------------------------------
# 1. jenga file sur un projet inclus
# ---------------------------------------------------------------------------

class TestFileProjetSepare:
    def test_file_interactif_ecrit_dans_le_fichier_du_projet(self, tmp_path, monkeypatch):
        entry = _workspace(tmp_path)
        _projet(entry, "Jeu", separe=True)
        ws_avant = entry.read_text(encoding="utf-8")
        code = _file(monkeypatch, entry, ["Jeu", "-i"], ["4", "MON_JEU=1", "0"])
        assert code == 0
        jeu = (entry.parent / "Jeu" / "Jeu.jenga").read_text(encoding="utf-8")
        assert 'defines(["MON_JEU=1"])' in jeu
        assert entry.read_text(encoding="utf-8") == ws_avant  # le workspace n'est pas touche
        wks = _charger(entry)
        assert "MON_JEU=1" in wks.projects["Jeu"].defines

    def test_file_direct_ecrit_dans_le_fichier_du_projet(self, tmp_path, monkeypatch):
        entry = _workspace(tmp_path)
        _projet(entry, "Jeu", separe=True)
        assert _file(monkeypatch, entry, ["Jeu", "--def", "AUTRE=2"]) == 0
        assert "AUTRE=2" in _charger(entry).projects["Jeu"].defines

    def test_file_inclus_dans_un_inclus(self, tmp_path, monkeypatch):
        # W.jenga inclut libs/libs.jenga, qui inclut Outils/Outils.jenga : le bloc vit dans le plus
        # profond. Le fichier retenu est celui qui DECLARE le projet, pas le premier inclus.
        entry = _workspace(tmp_path)
        libs = entry.parent / "libs"
        (libs / "Outils" / "src").mkdir(parents=True)
        (libs / "Outils" / "src" / "o.cpp").write_text("int o(){return 0;}\n", encoding="utf-8")
        (libs / "Outils" / "Outils.jenga").write_text(
            'from Jenga import *\n\nwith project("Outils"):\n    staticlib()\n    location(".")\n'
            '    files(["src/**.cpp"])\n', encoding="utf-8")
        (libs / "libs.jenga").write_text(
            'from Jenga import *\n\nwith include("Outils/Outils.jenga"):\n    pass\n', encoding="utf-8")
        with open(entry, "a", encoding="utf-8") as f:
            f.write('\n    with include("libs/libs.jenga"):\n        pass\n')
        assert _charger(entry).projects["Outils"]._externalFile.endswith("Outils.jenga")
        assert _file(monkeypatch, entry, ["Outils", "--def", "PROFOND=1"]) == 0
        assert "PROFOND=1" in (libs / "Outils" / "Outils.jenga").read_text(encoding="utf-8")
        assert "PROFOND=1" in _charger(entry).projects["Outils"].defines

    def test_temoin_projet_inline(self, tmp_path, monkeypatch):
        entry = _workspace(tmp_path)
        _projet(entry, "Jeu", separe=False)
        assert _file(monkeypatch, entry, ["Jeu", "-i"], ["4", "MON_JEU=1", "0"]) == 0
        assert 'defines(["MON_JEU=1"])' in entry.read_text(encoding="utf-8")
        assert "MON_JEU=1" in _charger(entry).projects["Jeu"].defines


# ---------------------------------------------------------------------------
# 2 et 3. jenga workspace -i : compilateur et tests
# ---------------------------------------------------------------------------

def _seance_workspace(tmp_path, monkeypatch, compilateur="", tests="", projet=True):
    """Seance `jenga workspace -i` : 12 ou 13 reponses, dans l'ordre des questions de Init."""
    from Jenga.Commands.Init import InitCommand
    monkeypatch.chdir(tmp_path)
    reponses = ["MonJeu", "", "", "", "", compilateur, ""]  # nom, parent, configs, OS, archs, compilo, std
    if projet:
        reponses += ["", "Jeu", "", "n"]                    # projet initial, nom, genre, fichier separe
    else:
        reponses += ["n"]
    reponses += [tests, ""]                                  # tests, confirmation
    lues = _reponses(monkeypatch, reponses)
    _reset()
    assert InitCommand._RunInteractive(argparse.Namespace()) == 0
    assert len(lues) == len(reponses)
    return tmp_path / "MonJeu" / "MonJeu.jenga"


class TestCompilateur:
    @pytest.mark.parametrize("choix,famille", [("2", "gcc"), ("3", "clang"), ("4", "msvc"), ("5", "zig")])
    def test_reponse_ecrite_et_lue(self, tmp_path, monkeypatch, choix, famille):
        entry = _seance_workspace(tmp_path, monkeypatch, compilateur=choix)
        assert f'prefercompiler("{famille}")' in entry.read_text(encoding="utf-8")
        assert getattr(_charger(entry), "preferredCompiler", None) == famille

    def test_temoin_auto_detect_n_ecrit_rien(self, tmp_path, monkeypatch):
        entry = _seance_workspace(tmp_path, monkeypatch, compilateur="")
        assert "prefercompiler(" not in entry.read_text(encoding="utf-8")
        assert not getattr(_charger(entry), "preferredCompiler", "")

    def test_famille_inconnue_refusee(self):
        with pytest.raises(ValueError):
            with Api.workspace("W"):
                Api.prefercompiler("borland")

    def test_hors_workspace_refuse(self):
        with pytest.raises(RuntimeError):
            Api.prefercompiler("gcc")


def _chaine(nom, fam, tenv=TargetEnv.MINGW):
    tc = Toolchain(name=nom, compilerFamily=fam, ccPath="cc", cxxPath="c++", arPath="ar",
                   targetOs=TargetOS.WINDOWS, targetArch=TargetArch.X86_64)
    tc.targetEnv = tenv
    return tc


def _builder_windows(preference, chaines):
    """Builder dont la detection rend `chaines` (aucun compilateur reel n'est sonde)."""
    from Jenga.Core.Builders.Windows import WindowsBuilder
    from Jenga.Core.Toolchains import ToolchainManager
    wks = Workspace(name="W", location=".")
    if preference:
        wks.preferredCompiler = preference
    mgr = ToolchainManager.__new__(ToolchainManager)
    mgr._detected = {tc.name: tc for tc in chaines}
    mgr._cache = {}
    mgr.DetectAll = lambda *a, **k: None
    b = WindowsBuilder.__new__(WindowsBuilder)
    b.workspace, b.options, b.toolchain, b.toolchainManager = wks, [], None, mgr
    b.targetOs, b.targetArch, b.targetEnv, b.verbose = TargetOS.WINDOWS, TargetArch.X86_64, None, False
    b._DetectCompilerCache = lambda: None
    return b


_CHAINES = [
    _chaine("clang-mingw", CompilerFamily.CLANG),
    _chaine("mingw", CompilerFamily.GCC),
    _chaine("msvc", CompilerFamily.MSVC, TargetEnv.MSVC),
    _chaine("zig-windows-x64", CompilerFamily.CLANG),
]


class TestPreferenceAuBuild:
    @pytest.mark.parametrize("famille,attendu", [("gcc", "mingw"), ("msvc", "msvc"), ("zig", "zig-windows-x64"),
                                                 ("clang", "clang-mingw")])
    def test_la_famille_preferee_l_emporte(self, famille, attendu):
        b = _builder_windows(famille, _CHAINES)
        b._ResolveToolchain()
        assert b.toolchain.name == attendu

    def test_temoin_sans_preference(self):
        b = _builder_windows("", _CHAINES)
        b._ResolveToolchain()
        assert b.toolchain.name == "clang-mingw"  # ordre automatique de Windows

    def test_famille_absente_repli_automatique(self):
        b = _builder_windows("gcc", [c for c in _CHAINES if c.name != "mingw"])
        b._ResolveToolchain()
        assert b.toolchain.name == "clang-mingw"

    def test_clang_ne_choisit_pas_zig(self):
        b = _builder_windows("clang", [c for c in _CHAINES if c.name != "clang-mingw"])
        b._ResolveToolchain()
        assert b.toolchain.name != "zig-windows-x64"


class TestTests:
    def test_reponse_oui_active_unitest(self, tmp_path, monkeypatch):
        entry = _seance_workspace(tmp_path, monkeypatch, tests="y")
        texte = entry.read_text(encoding="utf-8")
        assert "\n    with unitest() as u:\n        u.Compile()" in texte
        wks = _charger(entry)
        assert wks.unitestConfig is not None and wks.unitestConfig.isCompile()
        assert "__Unitest__" in wks.projects

    def test_reponse_oui_sans_projet_initial(self, tmp_path, monkeypatch):
        entry = _seance_workspace(tmp_path, monkeypatch, tests="y", projet=False)
        assert _charger(entry).unitestConfig is not None

    def test_temoin_reponse_non(self, tmp_path, monkeypatch):
        entry = _seance_workspace(tmp_path, monkeypatch, tests="")
        wks = _charger(entry)
        assert wks.unitestConfig is None and "__Unitest__" not in wks.projects


# ---------------------------------------------------------------------------
# jenga project -i : chaque reponse se retrouve dans le .jenga ou sur le disque
# ---------------------------------------------------------------------------

def _seance_projet(tmp_path, monkeypatch, fichiers_de_depart):
    from Jenga.Commands.Create import CreateCommand
    entry = _workspace(tmp_path)
    monkeypatch.chdir(entry.parent)
    # nom, genre (2 = windowed), langage, standard (2 = C++20), dossier, fichier separe, espace de noms,
    # dossiers src/include, fichiers de depart, confirmation
    reponses = ["Jeu", "2", "", "2", "apps", "y", "", "", fichiers_de_depart, ""]
    lues = _reponses(monkeypatch, reponses)
    _reset()
    assert CreateCommand.Execute(["-i", "--jenga-file", str(entry)]) == 0
    assert len(lues) == len(reponses)
    return entry


class TestProjetInteractif:
    def test_reponses_ecrites(self, tmp_path, monkeypatch):
        entry = _seance_projet(tmp_path, monkeypatch, "")
        jeu = entry.parent / "apps" / "Jeu" / "Jeu.jenga"
        assert 'with include("apps/Jeu/Jeu.jenga")' in entry.read_text(encoding="utf-8")
        texte = jeu.read_text(encoding="utf-8")
        assert "windowedapp()" in texte and 'cppdialect("C++20")' in texte
        p = _charger(entry).projects["Jeu"]
        assert p.kind == Api.ProjectKind.WINDOWED_APP and p.cppdialect == "C++20"
        assert (jeu.parent / "src" / "main.cpp").is_file()

    def test_fichiers_de_depart_non(self, tmp_path, monkeypatch):
        entry = _seance_projet(tmp_path, monkeypatch, "n")
        dossier = entry.parent / "apps" / "Jeu"
        assert (dossier / "src").is_dir() and (dossier / "include").is_dir()  # dossiers : oui
        assert not (dossier / "src" / "main.cpp").exists()                      # fichiers : non
        assert "Jeu" in _charger(entry).projects
