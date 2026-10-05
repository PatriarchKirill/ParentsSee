@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title ParentsSee - сборка EXE

set "PY=py -3"
where py >nul 2>nul || set "PY=python"

echo === Устанавливаю инструменты сборки ===
%PY% -m pip install --upgrade pyinstaller pystray Pillow
if errorlevel 1 (
  echo Не удалось установить PyInstaller. Проверьте интернет.
  pause
  exit /b 1
)

echo.
echo === Собираю один файл ParentsSee.exe ===
%PY% -m PyInstaller --noconfirm --onefile --windowed --name ParentsSee ^
  --icon "assets\icon.ico" ^
  --collect-submodules pystray --hidden-import PIL._tkinter_finder ^
  --version-file "version_info.txt" "ParentsSee.pyw"
if errorlevel 1 (
  echo Сборка завершилась с ошибкой.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   Готово: dist\ParentsSee.exe
echo   Этот файл можно копировать на любой ПК —
echo   Python и библиотеки уже внутри.
echo ============================================
pause
