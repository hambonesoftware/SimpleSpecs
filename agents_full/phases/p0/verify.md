# VERIFY — P0: Bootstrap & Governance
Mark PASS/FAIL for: required files present, CI gates, health route, CORS env, no API break.
Run:
```
pre-commit run --all-files
pytest -q --maxfail=1 --disable-warnings --cov=backend --cov-report=term-missing
```
Use the template in `_common/verify_report_template.md` for the report.
