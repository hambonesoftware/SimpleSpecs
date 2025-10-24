@echo off
setlocal
if exist .env (
  for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if not "%%a"=="" if not "%%a"=="#" set %%a=%%b
  )
)
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
