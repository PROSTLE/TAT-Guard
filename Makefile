# TAT Guard development tasks

.PHONY: test lint generate load recon verify verify-v5 ui clean

test:
	pytest -v tests/

lint:
	python nonhalluc/claim_scan.py README.md
	python -m py_compile recon/rules.py
	python -m py_compile recon/penalty.py
	python -m py_compile recon/pipeline.py

generate:
	python generator/generate.py

load:
	python recon/pipeline.py load

recon:
	python recon/pipeline.py recon

verify: verify-v0 verify-v1 verify-v2 verify-v4 verify-v5

verify-v0:
	python verify/v0_connect.py

verify-v1:
	python verify/v1_load.py

verify-v2:
	python verify/v2_accuracy.py

verify-v4:
	python verify/v4_agent.py

verify-v5:
	python verify/v5_edge_cases.py

ui:
	python ui/server.py

clean:
	rm -rf data/ __pycache__ */__pycache__
