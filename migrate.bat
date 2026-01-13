@echo off
REM ================================================
REM Alembic Migration Helper Script for mnam-backend
REM ================================================
REM Usage: migrate.bat [command] [message]
REM
REM Commands:
REM   new [message]  - Create new migration with autogenerate
REM   up             - Apply all pending migrations
REM   down           - Rollback last migration
REM   current        - Show current revision
REM   history        - Show migration history
REM   heads          - Show current heads
REM ================================================

setlocal

if "%1"=="" goto help
if "%1"=="new" goto new
if "%1"=="up" goto up
if "%1"=="down" goto down
if "%1"=="current" goto current
if "%1"=="history" goto history
if "%1"=="heads" goto heads
goto help

:new
if "%2"=="" (
    echo Error: Please provide a migration message
    echo Usage: migrate.bat new "your_migration_message"
    exit /b 1
)
echo Creating new migration: %2
alembic revision --autogenerate -m "%~2"
goto end

:up
echo Applying all pending migrations...
alembic upgrade head
goto end

:down
echo Rolling back last migration...
alembic downgrade -1
goto end

:current
echo Current revision:
alembic current
goto end

:history
echo Migration history:
alembic history
goto end

:heads
echo Current heads:
alembic heads
goto end

:help
echo ================================================
echo Alembic Migration Helper
echo ================================================
echo Usage: migrate.bat [command] [message]
echo.
echo Commands:
echo   new "message"  - Create new migration with autogenerate
echo   up             - Apply all pending migrations
echo   down           - Rollback last migration
echo   current        - Show current revision
echo   history        - Show migration history
echo   heads          - Show current heads
echo.
echo Examples:
echo   migrate.bat new "add user phone field"
echo   migrate.bat up
echo ================================================

:end
endlocal
