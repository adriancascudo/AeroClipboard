@echo off

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv || goto :error
)
call ".venv\Scripts\activate.bat" || goto :error

python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt pyinstaller || goto :error

rem --- Tesseract-OCR: se copia SOLO lo necesario (exe, DLL, idiomas) a vendor\tesseract.
rem     Instalarlo antes con el instalador de UB-Mannheim (marca "Spanish" en idiomas)
rem     o indicar su carpeta:  set TESSERACT_DIR=D:\Tesseract-OCR
if defined TESSERACT_DIR goto :tess_found
for %%D in ("%ProgramFiles%\Tesseract-OCR" "%ProgramFiles(x86)%\Tesseract-OCR" "%LOCALAPPDATA%\Programs\Tesseract-OCR" "%LOCALAPPDATA%\Tesseract-OCR") do if exist "%%~D\tesseract.exe" set "TESSERACT_DIR=%%~D"
if defined TESSERACT_DIR goto :tess_found
for /f "delims=" %%I in ('where tesseract 2^>nul') do set "TESSERACT_DIR=%%~dpI"
:tess_found
if not defined TESSERACT_DIR set "TESSERACT_DIR=C:\Program Files\Tesseract-OCR"
echo Tesseract: "%TESSERACT_DIR%"
if not exist "%TESSERACT_DIR%\tesseract.exe" (
    echo ERROR: no se encuentra "%TESSERACT_DIR%\tesseract.exe".
    echo Instala Tesseract-OCR o define TESSERACT_DIR.
    goto :error
)
if not exist "%TESSERACT_DIR%\tessdata\spa.traineddata" (
    echo ERROR: falta spa.traineddata en "%TESSERACT_DIR%\tessdata". Reinstala Tesseract marcando Spanish.
    goto :error
)
if exist vendor\tesseract rmdir /s /q vendor\tesseract
mkdir vendor\tesseract\tessdata || goto :error
copy /y "%TESSERACT_DIR%\tesseract.exe" vendor\tesseract\ >nul || goto :error
copy /y "%TESSERACT_DIR%\*.dll" vendor\tesseract\ >nul || goto :error
copy /y "%TESSERACT_DIR%\tessdata\eng.traineddata" vendor\tesseract\tessdata\ >nul || goto :error
copy /y "%TESSERACT_DIR%\tessdata\spa.traineddata" vendor\tesseract\tessdata\ >nul || goto :error
if exist "%TESSERACT_DIR%\tessdata\configs" xcopy /e /i /y /q "%TESSERACT_DIR%\tessdata\configs" vendor\tesseract\tessdata\configs >nul
if exist "%TESSERACT_DIR%\tessdata\tessconfigs" xcopy /e /i /y /q "%TESSERACT_DIR%\tessdata\tessconfigs" vendor\tesseract\tessdata\tessconfigs >nul
if exist "%TESSERACT_DIR%\LICENSE" copy /y "%TESSERACT_DIR%\LICENSE" vendor\tesseract\LICENSE.tesseract >nul

rem --onedir (NO --onefile): no extrae nada a %%TEMP%%, que es lo que suelen bloquear AppLocker/ASR.
rem --noupx: los ejecutables comprimidos con UPX disparan falsos positivos de antivirus.
pyinstaller --noconfirm --clean --windowed --noupx ^
    --name SnippetBaul ^
    --icon assets\icon.ico ^
    --version-file version_info.txt ^
    --add-data "vendor\tesseract;tesseract" ^
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 ^
    --exclude-module matplotlib --exclude-module scipy --exclude-module pandas ^
    snippet_manager.pyw || goto :error

if defined SIGN_THUMBPRINT (
    echo Firmando ejecutable...
    signtool sign /sha1 %SIGN_THUMBPRINT% /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
        dist\SnippetBaul\SnippetBaul.exe || goto :error
)

tar -a -c -f dist\SnippetBaul.zip -C dist SnippetBaul || goto :error

echo.
echo SHA-256 del ejecutable (util para que TI lo incluya en la lista de permitidos):
certutil -hashfile dist\SnippetBaul\SnippetBaul.exe SHA256
echo.
echo Listo: dist\SnippetBaul\SnippetBaul.exe
exit /b 0

:error
echo.
echo La compilacion ha fallado. Revisa los mensajes anteriores.
exit /b 1