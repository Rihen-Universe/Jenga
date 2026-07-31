@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM gitpush.bat - add + commit + push du SEUL superprojet Jenga.
REM               Le sous-module Nkentseu n'est JAMAIS pousse ici : il se gere
REM               a part, dans son propre depot Rihen-Universe/Nkentseu.
REM
REM Deux declencheurs cote GitHub Actions :
REM   - Push de la BRANCHE   -> sync-wiki.yml  -> met a jour le WIKI.
REM   - Push d'un TAG vX.Y.Z -> release.yml    -> publie la RELEASE.
REM
REM USAGE
REM   gitpush.bat ^<branche^> "^<message^>"
REM       Commit + push de la branche.  => le WIKI se met a jour.
REM
REM   gitpush.bat ^<branche^> "^<message^>" --release
REM       Idem, PUIS cree le tag v^<version^> (lu dans Jenga\_version.py) et le
REM       pousse.  => la RELEASE GitHub est publiee.
REM
REM   gitpush.bat ^<branche^> "^<message^>" --release v2.0.3
REM       Version de tag explicite.
REM
REM   Options : --dry-run (simulation)   ^|   --help
REM
REM EXEMPLES
REM   gitpush.bat main "docs: maj wiki"
REM   gitpush.bat main "release 2.0.2" --release
REM   gitpush.bat main "test" --dry-run
REM ============================================================================

set "DRYRUN=0"
set "RELEASE=0"
set "TAGVER="
set "BRANCH="
set "MSG="

REM ---- Parsing des arguments (positionnels + options) ----
:parse
if "%~1"=="" goto after_parse
set "ARG=%~1"
if /i "%ARG%"=="--help"    goto help
if /i "%ARG%"=="-h"        goto help
if /i "%ARG%"=="--dry-run" ( set "DRYRUN=1" & shift & goto parse )
if /i "%ARG%"=="-d"        ( set "DRYRUN=1" & shift & goto parse )
if /i "%ARG%"=="--release" ( set "RELEASE=1" & call :maybe_tagver "%~2" & shift & goto parse )
if /i "%ARG%"=="-r"        ( set "RELEASE=1" & call :maybe_tagver "%~2" & shift & goto parse )
if not defined BRANCH ( set "BRANCH=%ARG%" & shift & goto parse )
if not defined MSG    ( set "MSG=%ARG%" & shift & goto parse )
shift
goto parse

:maybe_tagver
REM Si l'argument suivant n'est pas une option et n'est pas vide, c'est la version.
set "NEXT=%~1"
if "%NEXT%"=="" goto :eof
set "FIRST=%NEXT:~0,1%"
if "%FIRST%"=="-" goto :eof
set "TAGVER=%NEXT%"
goto :eof

:after_parse
if not defined BRANCH goto usage_err
if not defined MSG    goto usage_err

REM ---- Racine = dossier du script ----
set "ROOT=%~dp0"
pushd "%ROOT%" >nul 2>&1
set "SUBMODULE_PATH=Jenga/Exemples/Nkentseu"

echo ============================================================
echo  gitpush (Jenga)  ^|  branche : %BRANCH%
echo    message : "%MSG%"
if "%RELEASE%"=="1" (echo    release : OUI) else (echo    release : non)
if "%DRYRUN%"=="1"  echo    *** DRY-RUN : aucune commande ne sera executee ***
echo ============================================================

REM ---- 1) Se placer sur la bonne branche ----
set "CUR="
for /f "delims=" %%b in ('git symbolic-ref --short -q HEAD 2^>nul') do set "CUR=%%b"
if not "%CUR%"=="%BRANCH%" (
  echo    branche courante : %CUR% -^> bascule sur '%BRANCH%'
  call :run git checkout "%BRANCH%" || goto fail_checkout
)

REM ---- 2) Indexer Jenga, jamais le pointeur du sous-module Nkentseu ----
call :run git add -A || goto fail_add
git diff --cached --quiet -- "%SUBMODULE_PATH%" >nul 2>&1
if errorlevel 1 (
  echo    [ATTN] changement de pointeur Nkentseu detecte -^> EXCLU ^(se pousse a part^).
  call :run git reset -q -- "%SUBMODULE_PATH%"
)

REM ---- 3) Committer s'il y a quelque chose d'indexe ----
git diff --cached --quiet >nul 2>&1
if errorlevel 1 (
  call :run git commit -m "%MSG%" || goto fail_commit
  echo [OK] commit cree : "%MSG%"
) else (
  echo    rien de nouveau a committer
)

REM ---- 4) Pousser la branche ^(=^> WIKI^) ----
call :run git push --no-recurse-submodules origin "%BRANCH%" || goto fail_push
echo [OK] branche '%BRANCH%' poussee -^> le wiki se met a jour ^(si Docs/wiki a change^).

REM ---- 5) Optionnel : tag de version ^(=^> RELEASE^) ----
if "%RELEASE%"=="1" (
  if not defined TAGVER call :read_version
  if not defined TAGVER goto fail_version
  set "VER=!TAGVER!"
  if "!VER:~0,1!"=="v" set "VER=!VER:~1!"
  set "TAG=v!VER!"
  echo ==^> Release : tag !TAG!
  git rev-parse -q --verify "refs/tags/!TAG!" >nul 2>&1
  if errorlevel 1 (
    call :run git tag -a "!TAG!" -m "Release !TAG!" || goto fail_tag
    echo [OK] tag !TAG! cree.
  ) else (
    echo    [ATTN] le tag !TAG! existe deja en local - non recree.
    echo    [ATTN] Bumpe __version__ dans Jenga\_version.py pour une nouvelle release.
  )
  call :run git push origin "!TAG!" || goto fail_pushtag
  echo [OK] tag !TAG! pousse -^> la release GitHub se construit automatiquement.
)

echo.
echo [OK] Termine.
if "%DRYRUN%"=="1" echo [ATTN] DRY-RUN : rien n'a ete reellement modifie.
popd >nul 2>&1
endlocal
exit /b 0

REM ============================================================================
REM Helpers
REM ============================================================================
:run
echo    $ %*
if "%DRYRUN%"=="1" (ver >nul & goto :eof)
%*
goto :eof

:read_version
REM Lit __version__ = "x.y.z" dans Jenga\_version.py
set "RAW="
for /f "tokens=2 delims==" %%v in ('findstr /b "__version__" "%ROOT%Jenga\_version.py" 2^>nul') do set "RAW=%%v"
if not defined RAW goto :eof
set "RAW=%RAW: =%"
set "RAW=%RAW:"=%"
set "TAGVER=%RAW%"
goto :eof

:help
findstr /b "REM" "%~f0"
endlocal
exit /b 0

:usage_err
echo [ERREUR] Il faut : ^<branche^> et un "^<message^>".
echo Exemple : gitpush.bat main "mon message" [--release [vX.Y.Z]]
endlocal
exit /b 1

:fail_checkout
echo [ERREUR] checkout '%BRANCH%' impossible (conflits ?).
popd >nul 2>&1 & endlocal & exit /b 1
:fail_add
echo [ERREUR] git add a echoue.
popd >nul 2>&1 & endlocal & exit /b 1
:fail_commit
echo [ERREUR] git commit a echoue.
popd >nul 2>&1 & endlocal & exit /b 1
:fail_push
echo [ERREUR] push de la branche '%BRANCH%' echoue.
popd >nul 2>&1 & endlocal & exit /b 1
:fail_version
echo [ERREUR] version introuvable dans Jenga\_version.py.
popd >nul 2>&1 & endlocal & exit /b 1
:fail_tag
echo [ERREUR] creation du tag echouee.
popd >nul 2>&1 & endlocal & exit /b 1
:fail_pushtag
echo [ERREUR] push du tag echoue (deja pousse ? remote en avance ?).
popd >nul 2>&1 & endlocal & exit /b 1
