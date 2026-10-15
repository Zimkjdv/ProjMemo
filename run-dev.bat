@echo off
setlocal EnableExtensions DisableDelayedExpansion
call "%~dp0run-local.bat" --dev %*
exit /b %ERRORLEVEL%
