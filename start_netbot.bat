@echo off
cd /d "F:\NetBot\NetBot"
set SQLINSTANCE=LAPTOP-PJ7CL5BK\HOANGSON
set PYTHONW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe
echo [INFO] Checking SQL Server...
:CHECK_SQL
sqlcmd -S %SQLINSTANCE% -Q "SELECT 1" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Hold on SQL Server ready...
    timeout /t 5 /nobreak >nul
    goto CHECK_SQL
)

echo [OK] SQL Server already. Running NetBot...
tasklist /fi "imagename eq pythonw.exe" | find /i "pythonw.exe" >nul
if %errorlevel%==0 (
    echo [INFO] NetBot Already...
    exit
)
start "" pythonw NetBot.py
echo [INFO] NetBot is running...
exit
