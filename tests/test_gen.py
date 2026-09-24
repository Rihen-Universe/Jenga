# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
#
# `jenga gen` : ce que les fichiers generes doivent contenir (2.8.4).
#
# Chaque assertion correspond a un defaut MESURE en construisant avec l'outil
# cible (CMake 4.4, MSBuild de VS 2026, ndk-build r27) :
#   - CMake : « Invalid character escape '\U' » (chemins Windows en « \ ») ;
#     OBJC/OBJCXX demandes pour un projet C++ ;
#   - VS : PlatformToolset v143 ecrit en dur -> MSB8020 sous VS 2026 ;
#     GUID du .vcxproj different de celui de la solution ;
#   - Android.mk : pas de -llog ni de colle NativeActivity -> lien refuse ;
#     APP_PLATFORM = min(21, ...) -> androidminsdk() ignore.
# La construction reelle reste le vrai juge ; ces tests gardent le contrat.
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RACINE_JENGA = Path(__file__).resolve().parents[1]

WORKSPACE = '''
from Jenga import *
with workspace("GenTest"):
    configurations(["Debug", "Release"])
    with project("Engine"):
        staticlib()
        language("C++")
        cppdialect("C++20")
        location("engine")
        files(["src/**.cpp"])
        includedirs(["include"])
    with project("Game"):
        consoleapp()
        language("C++")
        cppdialect("C++17")
        location("game")
        files(["src/**.cpp"])
        dependson(["Engine"])
    with project("Droid"):
        windowedapp()
        language("C++")
        location("droid")
        files(["src/**.cpp"])
        androidnativeactivity(True)
        androidminsdk(26)
'''


@pytest.fixture(scope="module")
def sortie(tmp_path_factory):
    ws = tmp_path_factory.mktemp("gen_ws")
    (ws / "gen.jenga").write_text(WORKSPACE, encoding="utf-8")
    for d, contenu in (("engine/src/engine.cpp", "int engine() { return 1; }\n"),
                       ("engine/include/engine.h", "int engine();\n"),
                       ("game/src/main.cpp", "int main() { return 0; }\n"),
                       ("droid/src/main.cpp", "extern \"C\" void android_main(void*) {}\n")):
        p = ws / d
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenu, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(RACINE_JENGA), PYTHONIOENCODING="utf-8")
    for args in (["gen", "--cmake", "--vs", "--makefile", "-o", "out", "--no-cache"],
                 ["gen", "--android-mk", "--platform", "Android-arm64", "-o", "out_android", "--no-cache"]):
        r = subprocess.run([sys.executable, "-m", "Jenga"] + args, cwd=ws, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return ws


def test_cmake_sans_antislash_ni_chemin_de_machine(sortie):
    texte = (sortie / "out" / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "\\" not in texte
    assert str(sortie).replace("\\", "/") not in texte  # relatif, deplacable
    assert "${CMAKE_CURRENT_SOURCE_DIR}/../engine/src/engine.cpp" in texte


def test_cmake_ne_demande_que_les_langages_utilises(sortie):
    texte = (sortie / "out" / "CMakeLists.txt").read_text(encoding="utf-8")
    ligne = re.search(r"^project\(GenTest LANGUAGES (.*)\)$", texte, re.M).group(1).split()
    assert ligne == ["C", "CXX"]


def test_cmake_lie_les_dependances_comme_jenga(sortie):
    texte = (sortie / "out" / "CMakeLists.txt").read_text(encoding="utf-8")
    bloc = texte.split("# Project: Game", 1)[1]
    assert re.search(r"target_link_libraries\(Game PRIVATE\s+Engine\s*\)", bloc)


def test_cmake_application_fenetree_en_win32(sortie):
    texte = (sortie / "out" / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "add_executable(Droid WIN32" in texte


def test_vs_ensemble_d_outils_non_fige(sortie):
    texte = (sortie / "out" / "Game.vcxproj").read_text(encoding="utf-8")
    assert "<PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>" in texte
    assert "v143" not in texte


def test_vs_meme_guid_dans_la_solution_et_le_projet(sortie):
    sln = (sortie / "out" / "GenTest.sln").read_text(encoding="utf-8")
    guid_sln = re.search(r'"Game", "Game\.vcxproj", "(\{[0-9A-F-]+\})"', sln).group(1)
    vcx = (sortie / "out" / "Game.vcxproj").read_text(encoding="utf-8")
    assert f"<ProjectGuid>{guid_sln}</ProjectGuid>" in vcx


def test_vs_sous_systeme(sortie):
    assert "<SubSystem>Console</SubSystem>" in (sortie / "out" / "Game.vcxproj").read_text(encoding="utf-8")
    assert "<SubSystem>Windows</SubSystem>" in (sortie / "out" / "Droid.vcxproj").read_text(encoding="utf-8")


def test_makefile_chemin_entre_guillemets_et_en_slash(sortie):
    texte = (sortie / "out" / "Makefile").read_text(encoding="utf-8")
    ligne = next(l for l in texte.splitlines() if l.startswith("JENGA_FILE"))
    assert ligne.count('"') == 2 and "\\" not in ligne


def test_android_native_activity_complete(sortie):
    mk = (sortie / "out_android" / "Android.mk").read_text(encoding="utf-8")
    bloc = mk.split("LOCAL_MODULE := Droid", 1)[1].split("include $(BUILD_SHARED_LIBRARY)", 1)[0]
    assert "android_native_app_glue" in bloc
    assert "-llog" in bloc and "-landroid" in bloc
    assert "-u ANativeActivity_onCreate" in bloc
    assert "$(call import-module,android/native_app_glue)" in mk
    assert "\\\n" in mk or "LOCAL_SRC_FILES" in mk
    assert "C:" not in mk and "\\src" not in mk


def test_android_min_sdk_le_plus_eleve_et_std_par_module(sortie):
    app = (sortie / "out_android" / "Application.mk").read_text(encoding="utf-8")
    assert "APP_PLATFORM := android-26" in app
    assert "APP_CPPFLAGS" not in app
    mk = (sortie / "out_android" / "Android.mk").read_text(encoding="utf-8")
    assert "-std=c++20" in mk.split("LOCAL_MODULE := Engine", 1)[1].split("include $(", 1)[0]
    assert "-std=c++17" in mk.split("LOCAL_MODULE := Game", 1)[1].split("include $(", 1)[0]
