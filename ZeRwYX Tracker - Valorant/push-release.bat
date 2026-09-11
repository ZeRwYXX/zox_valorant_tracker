@echo off
setlocal EnableExtensions EnableDelayedExpansion

title ZeRwYX Tracker - Push Release
cd /d "%~dp0"

where git >nul 2>&1 || (
    echo Git est introuvable. Installe Git puis relance ce fichier.
    pause
    exit /b 1
)
where powershell >nul 2>&1 || (
    echo PowerShell est introuvable.
    pause
    exit /b 1
)

set "VERSION="
set /p VERSION=<VERSION
if not defined VERSION (
    echo VERSION est vide ou introuvable.
    pause
    exit /b 1
)

for /f "delims=" %%R in ('git remote get-url origin 2^>nul') do set "REMOTE=%%R"
if not defined REMOTE (
    echo Aucun remote Git nomme origin n'est configure.
    echo Configure-le avec: git remote add origin URL_DU_DEPOT
    pause
    exit /b 1
)

if not exist "runtime.json" (
    echo runtime.json est introuvable.
    pause
    exit /b 1
)

powershell -NoProfile -Command "$m = Get-Content -Raw -Encoding UTF8 'runtime.json' | ConvertFrom-Json; if ([string]$m.app.version -ne '%VERSION%') { throw ('runtime.json indique ' + $m.app.version + ' au lieu de %VERSION%') }"
if errorlevel 1 (
    echo runtime.json et VERSION ne correspondent pas.
    pause
    exit /b 1
)

echo.
echo ========================================
echo ZeRwYX Tracker release v%VERSION%
echo ========================================
echo Remote: %REMOTE%
echo.
echo Changements actuels:
git status --short
echo.

set /p CONFIRM=Continuer avec ce contenu et creer v%VERSION% ? (O/N):
if /i not "%CONFIRM%"=="O" if /i not "%CONFIRM%"=="Y" (
    echo Operation annulee.
    exit /b 0
)

git add -A
if errorlevel 1 goto :failed

if exist ".git\MERGE_HEAD" (
    echo Merge en attente detecte; finalisation du merge...
    git commit -m "Merge remote main and resolve release version"
    if errorlevel 1 (
        echo Le merge contient encore des conflits non resolus.
        echo Ouvre VS Code, resous les fichiers marques en conflit, puis relance ce batch.
        goto :failed
    )
)

git diff --cached --quiet
if not errorlevel 1 (
    echo Aucun changement a committer.
) else (
    git commit -m "Release v%VERSION%"
    if errorlevel 1 goto :failed
)

if not exist "dist" mkdir dist
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build-release.ps1" -Version "%VERSION%" -Output "%CD%\dist"
if errorlevel 1 goto :failed

if not exist "dist\valorant-scout-v%VERSION%.zip" (
    echo L'archive de release est introuvable.
    goto :failed
)

git rev-parse "v%VERSION%" >nul 2>&1
if not errorlevel 1 (
    echo Le tag v%VERSION% existe deja localement; conservation du tag existant.
) else (
    git tag -a "v%VERSION%" -m "Release v%VERSION%"
    if errorlevel 1 goto :failed
)

git push origin HEAD:main --follow-tags
if errorlevel 1 (
    echo La branche distante contient des commits supplementaires.
    echo Recuperation et fusion du travail distant...
    git fetch origin
    if errorlevel 1 goto :failed
    git pull --no-edit --no-rebase origin main
    if errorlevel 1 (
        echo Conflit de fusion. Resous-le dans Git, puis relance ce batch.
        goto :failed
    )
    git push origin HEAD:main --follow-tags
    if errorlevel 1 goto :failed
)

echo.
echo Commit, archive et tag v%VERSION% pousses avec succes.
echo Archive: dist\valorant-scout-v%VERSION%.zip

where gh >nul 2>&1
if errorlevel 1 (
    echo GitHub CLI gh n'est pas installe.
    echo Cree la release GitHub manuellement avec l'archive ci-dessus.
    pause
    exit /b 0
)

set /p CREATE_RELEASE=Creer aussi la release GitHub maintenant ? (O/N):
if /i "%CREATE_RELEASE%"=="O" if not exist "release-notes-%VERSION%.md" (
    >"release-notes-%VERSION%.md" echo Release v%VERSION%
    >>"release-notes-%VERSION%.md" echo.
    >>"release-notes-%VERSION%.md" echo Correctifs de mise a jour et validation du backend.
)
if /i "%CREATE_RELEASE%"=="O" (
    gh release create "v%VERSION%" "dist\valorant-scout-v%VERSION%.zip" --title "ZeRwYX Tracker %VERSION%" --notes-file "release-notes-%VERSION%.md"
    if errorlevel 1 goto :failed
    echo Release GitHub creee.
)

pause
exit /b 0

:failed
echo.
echo ECHEC. Aucun rollback automatique n'est effectue.
echo Verifie le message ci-dessus et les logs Git/PowerShell.
pause
exit /b 1
