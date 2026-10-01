PY=.venv/bin/python
.PHONY: venv install ingest ingest-live serve test eval stats reindex
venv:
	python3.11 -m venv .venv || python3 -m venv .venv
install: venv
	.venv/bin/pip install -e ".[dev]"
ingest:
	$(PY) -m taxrag.cli ingest all
ingest-live:
	$(PY) -m taxrag.cli ingest all --live
serve:
	$(PY) -m taxrag.cli serve --port 8000
test:
	$(PY) -m pytest -q
eval:
	$(PY) -m taxrag.cli evaluate --report eval_report.json
stats:
	$(PY) -m taxrag.cli stats
reindex:
	$(PY) -m taxrag.cli reindex --reparse
