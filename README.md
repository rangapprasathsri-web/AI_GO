# AI Image Resource Optimizer

> "AI image generation uses the same computing power regardless of what the image is for, and the energy cost is invisible to the user. Build a generation system that matches computational effort to the purpose of the image and shows the user what was saved by not generating at maximum quality."

The **Adaptive AI Image Resource Optimizer** is a production-grade, configurable decision layer that matches computational effort to the specific purpose of an image and makes the invisible resource cost and counterfactual savings visible to the requester.

---

## 🎯 What Success Looks Like

1. **Purpose Intake**: The user provides a prompt and selects the purpose (Coloring sheet, Educational illustration, Presentation graphic, Social media artwork, Professional/print artwork, Custom).
2. **Adaptive Recommendation**: The decision engine recommends the lowest quality tier (`Economy`, `Standard`, `Maximum`) that satisfies the purpose's quality requirements, explaining why in plain language with observable factors.
3. **User Override with Guardrails**: The requester can override the tier within hard budget limits. Overriding below the purpose floor triggers an explicit confirmation warning dialog and is logged. Overriding above budget is blocked.
4. **Transparent Compute Savings**: The system shows what was saved compared with generating at Maximum quality, in units and percent, with explicit origin labels (`simulated`, `provider-reported`, or `measured`).
5. **Rigorous Honesty Disclosures**:
   - Compute units are a relative proxy: `steps * megapixels * model_factor`. Real consumption depends on hardware, batching, and kernel efficiency.
   - The counterfactual Maximum tier was **not run**; savings are estimated avoided compute.
   - Demo images are clearly stamped with a visible `DEMO PLACEHOLDER` watermark and genuinely differ in resolution. They are never presented as real model outputs.
   - Physical energy (Wh) and carbon (CO2) return `null` (not zero) unless an authoritative, cited energy model source is enabled in config.

---

## 🚀 Quick Start (3 Commands)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run all tests
python -m pytest backend/tests -q

# 3. Serve the application
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

### Detailed Commands & Testing

### 2. Run the 7-Step Demo Script
Reproduces the complete 7-step evaluation from Section 11 of the official problem statement:
```bash
make demo
# or
python cli.py demo
```

The demo executes:
1. **Coloring sheet**: Recommends Economy tier; shows 11.8 units vs 118.0 Maximum baseline (~90% savings).
2. **Large print size (A1 Poster)**: Floor dynamically rises to Standard; explanation explicitly names the factor.
3. **Professional/print artwork**: Maximum tier recommended; savings shown as 0%, which is the honest answer.
4. **Override flow**: Below-floor override requires confirmation and is logged; over-budget override is blocked.
5. **History & running total**: Cumulative savings summary with successes-only count and origin split.
6. **Config-only change**: Changes recommendation dynamically without touching any engine code.
7. **Honesty disclosures**: Transparently states relative proxy status, non-run baseline, and energy disclaimer.

### 3. Run the Web Application
```bash
make serve
# or
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser:
- **Optimizer View**: Interactive purpose cards, prompt input, dynamic print flags, real-time recommendation, tier selector with override confirmation, and image generation.
- **Resource Comparison Centerpiece**: Selected effort vs Maximum baseline, avoided savings in units and %, origin badge, and side-by-side placeholder preview.
- **Generation History**: Filterable run log with CSV export (`/history/export.csv`).
- **Config Studio**: Live YAML/JSON configuration editor with validation and version rollback.

---

## 🏛️ Architecture & Separation of Concerns

```
[ Web UI / Client ]
       │
       ▼
[ FastAPI Endpoints ]  (/recommend, /generate, /history, /summary, /config)
       │
       ▼
[ Resource Optimizer Service ] ──► [ Configuration Engine ]
       │                               (tiers, purposes, budgets, energy_model)
       ▼
[ Resource Estimator Module ]
       (units proxy formula, counterfactual savings, energy null policy)
       │
       ▼
[ Generation Adapters ] (MockImageAdapter with DEMO PLACEHOLDER stamps)
       │
       ▼
[ SQLite Storage ] (data/optimizer.db: generations, history, versioning)
```

- **Strict Engine Boundary**: The core decision engine and estimation modules never import adapter, domain, or API code (enforced by AST tests).
- **Domain Decoupling**: All tier definitions, quality floors, budgets, and formulas live in `backend/domains/image_resource_optimizer.yaml`.

---

## 📊 Quality Tiers & Compute Units

Under formula `steps * megapixels * model_factor`:
| Quality Tier | Resolution | Steps | Model Factor | Compute Units | Savings vs Maximum |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Economy** | 768 × 768 | 20 | 1.0 | **11.80** | **~90.0%** avoided compute |
| **Standard** | 1024 × 1024 | 30 | 1.0 | **31.46** | **~73.3%** avoided compute |
| **Maximum** | 1536 × 1536 | 50 | 1.0 | **117.96** | **0.0%** (Baseline) |

---

## 📋 API Endpoints

- `POST /recommend`: Evaluates prompt, purpose, print size, detail, and resolution; returns recommended tier, deciding factor, plain-language explanation, estimates, and alternatives.
- `POST /generate`: Validates override choices and hard budgets, invokes generation adapter, generates image with placeholder mark, calculates counterfactual savings, and records to history.
- `GET /history`: Returns generation history filtered by purpose, tier, or status.
- `GET /history/{id}`: Returns record for a specific generation.
- `GET /history/export.csv`: Exports generation history as CSV.
- `GET /summary`: Cumulative savings across successful generations with data origin breakdown and running total string.
- `GET /config`: Sanitized configuration (no secrets).
- `PUT /config`: Validates and hot-reloads configuration with version tracking.
- `GET /health`: Health status and domain verification.

---

## ⚠️ Assumptions & Limitations

See [ASSUMPTIONS.md](file:///home/srirangapprasath/Documents/Sakthi/ASSUMPTIONS.md) for full records. Key notes:
1. **Compute Units Formula**: Relative first-order proxy (`steps * megapixels * model_factor`). Not measured electrical energy.
2. **Counterfactual Baseline**: The Maximum tier was not run; savings represent estimated avoided compute.
3. **Physical Energy & Carbon**: Default to `null` (not zero) unless `energy_model.enabled` is true with an authoritative source.
4. **Hard Budgets**: Budget violations are blocked or require adjustment; never silently exceeded.
5. **Demo Placeholders**: Synthetic assets stamped with visible DEMO PLACEHOLDER banners, differing in resolution. Never presented as real model outputs.
