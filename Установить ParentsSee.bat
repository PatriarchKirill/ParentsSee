@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title ParentsSee - установка

echo ============================================
echo   ParentsSee - проверка и установка
echo ============================================
echo.

rem ---- 1. Ищем Python ----
echo [1/3] Проверяю Python...
set "PYEXE="
where py    >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"

if not defined PYEXE (
  echo     Python не найден. Пробую установить через winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo.
    echo     winget недоступен. Установите Python 3 вручную:
    echo       https://www.python.org/downloads/
    echo     ВАЖНО: при установке отметьте "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo     Python установлен. Закройте это окно и запустите файл ещё раз.
  pause
  exit /b 0
)

for /f "delims=" %%v in ('%PYEXE% --version 2^>^&1') do echo     Найден: %%v

rem ---- 2. Проверяем pip ----
echo [2/3] Проверяю pip...
%PYEXE% -m pip --version >nul 2>nul
if errorlevel 1 (
  echo     Ставлю pip...
  %PYEXE% -m ensurepip --default-pip
)

rem ---- 3. Проверяем библиотеки ----
echo [3/3] Проверяю библиотеки pystray и Pillow...
%PYEXE% -c "import pystray, PIL" >nul 2>nul
if errorlevel 1 (
  echo     Устанавливаю pystray и Pillow...
  %PYEXE% -m pip install --user pystray Pillow
  if errorlevel 1 %PYEXE% -m pip install pystray Pillow
) else (
  echo     Уже установлены.
)

echo.
echo ============================================
echo   Готово. Запускаю ParentsSee...
echo ============================================

rem ---- Запуск без окна консоли ----
set "PYW="
where pythonw >nul 2>nul && set "PYW=pythonw"
if not defined PYW where pyw >nul 2>nul && set "PYW=pyw -3"
if not defined PYW set "PYW=%PYEXE%"

start "" %PYW% "%~dp0ParentsSee.pyw" open
exit /b 0
