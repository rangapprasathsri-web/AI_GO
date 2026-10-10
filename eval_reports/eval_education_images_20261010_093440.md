# Evaluation Report: education_images

> **Disclaimer**: All costs, latencies, and quality metrics in this report are SIMULATED. The category mix is an assumption (the audit says 'most', not a specific number). Savings are computed from runs of the same workload under both policies.

### Labelled Evaluation Assumptions
- **Category Mix (Assumption)**: 70% colouring sheets, 15% flashcards, 10% classroom illustrations, 5% banners
- **Repeat Rate (Assumption)**: 30% repeated subject requests eligible for library reuse
- **Pricing (Assumption)**: All prices sourced from placeholder, simulated
- **Seed**: 42
- **Workload size**: 45
- **Timestamp**: 20261010_093440

## Baseline (always_premium)

| Metric | Value |
|--------|-------|
| Total Requests | 45 |
| Completed | 32 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $2.1200 |
| Cost per Success (simulated) | $0.0650 |
| Mean Latency (simulated) | 7.188s |
| P95 Latency (simulated) | 12.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 2.22% |
| Routing Accuracy | 96.97% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 0, "Standard": 23, "Print-quality": 10} |
| Strategy Distribution | {"standard": 23, "premium": 10} |

## Policy: cheapest_meeting_quality

| Metric | Value |
|--------|-------|
| Total Requests | 45 |
| Completed | 32 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $0.5100 |
| Cost per Success (simulated) | $0.0156 |
| Mean Latency (simulated) | 2.562s |
| P95 Latency (simulated) | 5.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 2.22% |
| Routing Accuracy | 96.97% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 27, "Standard": 6, "Print-quality": 0} |
| Strategy Distribution | {"draft": 27, "standard": 6} |

## Policy: rule_based

| Metric | Value |
|--------|-------|
| Total Requests | 45 |
| Completed | 32 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $1.1100 |
| Cost per Success (simulated) | $0.0344 |
| Mean Latency (simulated) | 4.250s |
| P95 Latency (simulated) | 12.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 2.22% |
| Routing Accuracy | 96.97% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 23, "Standard": 4, "Print-quality": 6} |
| Strategy Distribution | {"draft": 23, "standard": 4, "premium": 6} |

## Policy: weighted

| Metric | Value |
|--------|-------|
| Total Requests | 45 |
| Completed | 32 |
| Failed | 1 |
| Moderation Blocked | 3 |
| Awaiting Clarification | 9 |
| Total Cost (simulated) | $0.5100 |
| Cost per Success (simulated) | $0.0156 |
| Mean Latency (simulated) | 2.562s |
| P95 Latency (simulated) | 5.000s |
| Quality Pass Rate | 100.00% |
| Failure Rate | 2.22% |
| Routing Accuracy | 96.97% |
| Reuse Hit Rate | 0.00% |
| Effort Level Mix | {"Reuse": 0, "Quick": 27, "Standard": 6, "Print-quality": 0} |
| Strategy Distribution | {"draft": 27, "standard": 6} |

## Comparisons vs Baseline

| Policy | Cost Saving | Saving % | Quality Δ | Latency Δ | Label |
|--------|-------------|----------|-----------|-----------|-------|
| cheapest_meeting_quality | $1.6100 | 75.9% | +0.0000 | -4.626s | simulated — same workload, same seed |
| rule_based | $1.0100 | 47.6% | +0.0000 | -2.938s | simulated — same workload, same seed |
| weighted | $1.6100 | 75.9% | +0.0000 | -4.626s | simulated — same workload, same seed |

---
*All values are simulated. Savings computed from same workload under both policies.*