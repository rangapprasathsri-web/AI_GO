.PHONY: setup test demo eval clean config-check adaptability

# Setup
setup:
	pip install -r requirements.txt

# Run all tests
test:
	python -m pytest backend/tests/ -v --tb=short

# Run demo: three seed requests showing different strategies
demo:
	python cli.py demo

# Run evaluation: baseline vs optimized
eval:
	python cli.py eval --seed 42 --size 50

# Check config
config-check:
	python cli.py config-check backend/domains/education_images.yaml
	python cli.py config-check backend/domains/text_summarization.yaml

# Adaptability demonstration
adaptability:
	python cli.py adaptability

# Run the FastAPI server
serve:
	uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# Clean
clean:
	rm -rf data/ eval_reports/ __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Full pipeline
all: setup test demo eval
