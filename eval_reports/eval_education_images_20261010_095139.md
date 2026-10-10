# Evaluation Report: education_images

> **Disclaimer**: All costs, latencies, and quality metrics in this report are SIMULATED. The category mix is an assumption (the audit says 'most', not a specific number). Savings are computed from runs of the same workload under both policies.

### Labelled Evaluation Assumptions
- **Category Mix (Assumption)**: 70% colouring sheets, 15% flashcards, 10% classroom illustrations, 5% banners
- **Repeat Rate (Assumption)**: 30% repeated subject requests eligible for library reuse
- **Pricing (Assumption)**: All prices sourced from placeholder, simulated
- **Seed**: 42
- **Workload size**: 65
- **Timestamp**: 20261010_095139

## Baseline (always_premium)

| Metric | Value |
|--------|-------|
| Total Requests | 65 |
| Completed | 36 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $1.4800 |
| Cost per Success (simulated) | $0.0400 |
| Mean Latency (simulated) | 5.000s |
| P95 Latency (simulated) | 5.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 1.54% |
| Routing Accuracy | 94.34% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 0, "Standard": 37, "Print-quality": 16} |
| Strategy Distribution | {"standard": 37, "premium": 16} |

## Policy: cheapest_meeting_quality

| Metric | Value |
|--------|-------|
| Total Requests | 65 |
| Completed | 51 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $0.7600 |
| Cost per Success (simulated) | $0.0147 |
| Mean Latency (simulated) | 2.471s |
| P95 Latency (simulated) | 5.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 1.54% |
| Routing Accuracy | 94.34% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 44, "Standard": 8, "Print-quality": 1} |
| Strategy Distribution | {"draft": 44, "standard": 8, "premium": 1} |

## Policy: rule_based

| Metric | Value |
|--------|-------|
| Total Requests | 65 |
| Completed | 43 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $0.6500 |
| Cost per Success (simulated) | $0.0149 |
| Mean Latency (simulated) | 2.488s |
| P95 Latency (simulated) | 5.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 1.54% |
| Routing Accuracy | 94.34% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 37, "Standard": 7, "Print-quality": 9} |
| Strategy Distribution | {"draft": 37, "standard": 7, "premium": 9} |

## Policy: weighted

| Metric | Value |
|--------|-------|
| Total Requests | 65 |
| Completed | 51 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $0.7600 |
| Cost per Success (simulated) | $0.0147 |
| Mean Latency (simulated) | 2.471s |
| P95 Latency (simulated) | 5.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 1.54% |
| Routing Accuracy | 94.34% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 44, "Standard": 8, "Print-quality": 1} |
| Strategy Distribution | {"draft": 44, "standard": 8, "premium": 1} |

## Comparisons vs Baseline

| Policy | Cost Saving | Saving % | Quality Δ | Latency Δ | Label |
|--------|-------------|----------|-----------|-----------|-------|
| cheapest_meeting_quality | $0.7200 | 48.6% | +0.0000 | -2.529s | simulated — same workload, same seed |
| rule_based | $0.8300 | 56.1% | +0.0000 | -2.512s | simulated — same workload, same seed |
| weighted | $0.7200 | 48.6% | +0.0000 | -2.529s | simulated — same workload, same seed |

---
*All values are simulated. Savings computed from same workload under both policies.*