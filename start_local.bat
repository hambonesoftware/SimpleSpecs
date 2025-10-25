@echo off
setlocal
if exist .env (
  for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if not "%%a"=="" if not "%%a"=="#" set %%a=%%b
  )
)

set "HOST_VALUE=%HOST%"
if "%HOST_VALUE%"=="" set "HOST_VALUE=0.0.0.0"

set "PORT_VALUE=%PORT%"
if "%PORT_VALUE%"=="" set "PORT_VALUE=8000"

set "LOG_LEVEL_VALUE=%LOG_LEVEL%"
if "%LOG_LEVEL_VALUE%"=="" set "LOG_LEVEL_VALUE=info"

uvicorn backend.main:app --host %HOST_VALUE% --port %PORT_VALUE% --reload --log-level %LOG_LEVEL_VALUE%
