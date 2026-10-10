# Multi-Prompt Policy Benchmark Report

**Generated At**: 2026-10-10 16:40:12 UTC  
**Evaluation Mode**: Level 0: Simulated Proxy (Demo Mode) (mock)  
**Reproducibility Seed**: `42`  
**Baseline Execution**: Maximum tier was **actually run** for every prompt to establish measured comparison.

> **Disclaimer**: We wrote these prompts for comparative evaluation; they are not a representative sample of real-world usage.

---

## 1. Overall Policy Comparison

| Policy | Prompts | Units Spent | Fit Pass Rate | Units / Fit Result | Units Saved | Savings % | Origin |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Always Maximum** | 20 | 2359.2 | 100.0% | 117.96 | 0.0 | 0.0% | simulated |
| **Adaptive (Optimizer)** | 20 | 672.44 | 100.0% | 33.62 | **+1686.76** | **71.5%** | simulated |
| **Cascade (Escalation)** | 20 | 672.44 | 100.0% | 33.62 | +1686.76 | 71.5% | simulated |

*Note: Savings are claimed strictly on results that met automated purpose-fit criteria.*

---

## 2. Per-Purpose Breakdown (Adaptive vs Maximum)

| Purpose Category | N | Adaptive Units | Maximum Units | Saved Units | Reduction % | Fit Pass Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `coloring_sheet` | 6 | 70.8 | 707.76 | +636.96 | 90.0% | 100.0% |
| `educational_illustration` | 4 | 86.52 | 471.84 | +385.32 | 81.7% | 100.0% |
| `presentation_graphic` | 4 | 125.84 | 471.84 | +346.0 | 73.3% | 100.0% |
| `social_media_artwork` | 3 | 35.4 | 353.88 | +318.48 | 90.0% | 100.0% |
| `professional_print_artwork` | 3 | 353.88 | 353.88 | +0.0 | 0.0% | 100.0% |

---

## 3. Hardware & Measurement Disclosure
- **Environment Level**: 0 (Level 0: Simulated Proxy (Demo Mode))
- **Details**: Mock provider; compute units are a relative mathematical proxy; latency & energy not measured.
- **Latency**: Not measured in demo mode
- **Energy (Wh) / Carbon**: Not measured (returns `null` under strict policy).
