# Credit-Scoring Repo Research

> Survey of the top ~40 repos from `github.com/topics/credit-scoring?o=desc&s=updated` (June 2026), plus deep-dives on the most relevant for Cardre.

## Overview

380 public repos tagged `credit-scoring`. Language distribution: Jupyter Notebook (163), Python (120), HTML (23), R (15), TypeScript (13), JavaScript (7), CSS (3), Rust (3), C++ (2), Go (2).

---

## Top Repos — Detailed

### 1. toad (`amphibian-dev/toad`) — ★526

| Attribute | Value |
|-----------|-------|
| Language | Python (93%), Rust (5%), Makefile, Shell |
| License | MIT |
| Commits | 858 |
| Forks | 184 |
| Updated | Jun 16, 2026 |
| Docs | toad.readthedocs.io |

**Description:** ESC Team's credit scorecard tools. Covers the full scorecard development process: EDA, feature engineering and selection, binning, WOE transformation, model validation, scorecard transformation.

**Keywords:** `python3`, `data-analysis`, `financial-analysis`, `credit-scoring`, `scorecard`, `credit-risk`, `toad`

**Key features relevant to Cardre:**

- `toad.quality()` — one-call IV calculation for all features
- `toad.selection.select()` — preliminary variable selection (missingness, IV, correlation thresholds)
- `toad.selection.stepwise()` — stepwise feature selection (forward/backward/both, AIC/BIC)
- `toad.transform.Combiner()` — chi-squared fine binning with `bin_plot()` visualization
- `toad.metrics.KS_bucket()` — model validation with decile lift tables
- `toad.ScoreCard()` — scorecard transformation with `base_score`, `base_odds`, `pdo`, `rate` parameterization

**What Cardre could take:** chi-squared binning, stepwise selection, bin quality visualization, scorecard scaling parameterization.

---

### 2. Sakhi_finance (`DrustO9/Sakhi_finance`)

| Attribute | Value |
|-----------|-------|
| Language | JavaScript (61%), Python (34%), CSS (5%), HTML |
| License | — |
| Commits | 4 |
| Updated | Jun 14, 2026 |

**Description:** Alternative credit scoring for bureau-invisible borrowers. Uses UPI transaction patterns + a 10-question behavioral assessment. UCO Bank PSB Hackathon 2026 Finalist.

**Stack:** FastAPI, LightGBM, SHAP, DiCE, pdfplumber, React 18, Vite, eSpeak NG

**Key features relevant to Cardre:**

- **UPI Cash-Flow Parser** — extracts 8 financial-behavior features from PDF bank statements
- **Counterfactual Explanations (DiCE)** — every Tier C/D rejection comes with 3 actionable improvement paths
- **Vernacular Psychometric Test** — 10-item EN/HI test grounded in Klinger et al. (2013)
- **Admin dashboard** — SHAP visualization + model metrics
- **Fully offline** — no external services required

**What Cardre could take:** counterfactual explanations, transaction pattern scoring, psychometric assessment, approval roadmap generation.

---

### 3. credit-scoring-mlops (`mikhailvokhrameev/credit-scoring-mlops`)

| Attribute | Value |
|-----------|-------|
| Language | Jupyter Notebook (97%), Python (3%) |
| License | MIT |
| Commits | 77 |
| Updated | Jun 16, 2026 |

**Description:** End-to-end credit scoring ML pipeline for the Home Credit Default Risk dataset with MLflow tracking. Aggregates 7 relational tables, engineers 300 features, trains 4 model families with Bayesian HPO.

**Stack:** pandas, scikit-learn, LightGBM, XGBoost, CatBoost, Optuna, MLflow, SHAP, joblib

**Key features relevant to Cardre:**

- Modular feature engineering across 7+ relational tables with Ridge-based top-300 selection
- Unified OOP base class for all models (add a new algorithm = one subclass)
- Stratified Out-of-Fold cross-validation with MLflow tracking
- Bayesian hyperparameter optimization via Optuna (stored in SQLite, resumable)
- SHAP explanations: Summary Bar, Beeswarm, local Waterfall plots
- Nested MLflow runs: parent → child HPO + Final_Production with Model Registry
- 5 formal statistical hypotheses tested (age monotonicity, missingness as signal, EXT_SOURCE importance, auxiliary table value, HPO effectiveness)

**What Cardre could take:** Optuna integration, MLflow experiment tracking, hypothesis testing gates, unified model base class, relational feature engineering.

---

### 4. RWAkinss (`rupeshkumarvs/RWAkinss`)

| Attribute | Value |
|-----------|-------|
| Language | TypeScript (86%), Solidity (10%), CSS (3%), JS |
| License | MIT |
| Commits | 207 |
| Updated | Jun 14, 2026 |

**Description:** Autonomous AI CFO on Mantle blockchain. Soulbound Credit Passport (ERC-721, 300-900 score), on-chain lending against tokenized real-world assets.

**Stack:** Next.js 14, RainbowKit, Wagmi, Foundry, Solidity, Groq LLM, CoinGecko, Chainalysis

**Relevance to Cardre:** On-chain credit scoring with portable credit identity. The credit passport + lending loop is a potential future direction for Cardre's scoring output distribution.

---

### 5. hadhi (`ovalentine964/hadhi`)

| Attribute | Value |
|-----------|-------|
| Language | Kotlin |
| Updated | Jun 15, 2026 |

**Description:** Free AI CFO for 500 million informal workers in Africa. Voice-based, offline-first, multi-language (Swahili + others). Uses Whisper + Qwen.

**Relevance to Cardre:** Financial inclusion angle, alternative data for unbanked populations. Could inform Cardre's alternative data manifest and fairness use cases.

---

### 6. credit-scoring-mlflow (`moora291/credit-scoring-mlflow`)

**Description:** Builds and tracks credit risk models using MLflow. Includes FastAPI deployment, Grafana dashboards, dbt feature engineering, Optuna tuning.

**Keywords:** `python`, `heroku`, `api`, `finance`, `deployment`, `rest-api`, `grafana`, `xgboost`, `dbt`, `feature-engineering`, `credit-scoring`, `model-deployment`, `imbalanced-learning`, `credit-risk`, `mlflow`, `fastapi`, `optuna`, `risk-modeling`

---

### 7. fraud-detection-credit-mlops (`bintang3703/fraud-detection-credit-mlops`)

**Description:** Detect fraud in credit card transactions with an ML pipeline built for production. AWS Lambda, LightGBM, FastAPI, Streamlit, SHAP.

**Keywords:** `python`, `data-science`, `deep-learning`, `aws-lambda`, `fintech`, `lightgbm`, `data-pipelines`, `credit-scoring`, `fraud-detection`, `imbalanced-learning`, `mlops`, `mlflow`, `credit-card-fraud-detection`, `shap`, `fastapi`, `streamlit`, `mlops-workflow`, `mlops-project`

---

### 8. credit-risk-assessment (`jeremias32-max123/credit-risk-assessment`)

**Description:** Predict credit risk with Keras, genetic algorithms, transfer learning, and TrAdaBoost. Uses multiple Kaggle/Kesci datasets.

**Keywords:** `money`, `data-science`, `machine-learning`, `ai`, `keras`, `kaggle-competition`, `neural-networks`, `classification`, `logistic-regression`, `transfer-learning`, `genetic-algorithms`, `credit-scoring`, `banking-applications`, `scorecard`, `loan-default-prediction`, `tradaboost`, `credit-risk-assessment`, `kesci-competition`, `chain-of-thought-reasoning`

---

### 9. Loan-Default-Prediction-System (`Nkaduadjei/Loan-Default-Prediction-System`)

**Description:** Hybrid ensemble ML models for loan default prediction with Flask web app. XGBoost + ensemble learning.

**Keywords:** `machine-learning`, `xgboost`, `ensemble-learning`, `predictive-modeling`, `risk-assessment`, `credit-scoring`, `loan-data`, `loan-default-prediction`, `model-deployment`, `loan-prediction-analysis`, `flask-webapp`, `risk-score`, `loan-approval-prediction`, `banking-analytics`, `financial-predictions`, `credit-risk-modeling`, `web-based-ml`

---

### 10. credit-risk-prediction-xgboost (`zrldnl/credit-risk-prediction-xgboost`)

**Description:** XGBoost credit risk prediction with Streamlit interactive app for real-time loan applicant assessments.

**Keywords:** `python`, `finance`, `data-science`, `machine-learning`, `end-to-end`, `fintech`, `xgboost`, `classification`, `credit-scoring`, `loan-default-prediction`, `credit-risk`, `loan-default`, `streamlit`

---

### 11. Kontomatik API profile (`api-evangelist/kontomatik`)

**Description:** API Evangelist profile for Kontomatik — CEE open banking & bank data aggregation API.

**Keywords:** `credit-scoring`, `ais`, `kyc`, `pdf-parsing`, `open-banking`, `cee`, `psd2`, `bank-data-aggregation`, `transaction-labeling`

---

## Proposed Developments for Cardre

### From toad

1. **Chi-squared fine binning** — Add `method='chi'` option to `FineClassingNode` alongside existing tree-based splits. Chi-squared binning merges adjacent bins until significance is lost, producing coarser, more stable scorecard bins.

2. **Stepwise feature selection** — Add a `cardre.stepwise_selection` node doing forward/backward/bidirectional selection with AIC/BIC. Cardre has filter-based selection but not stepwise, which scorecard modellers routinely expect.

3. **Bin quality visualization** — Expose bin-plot-style diagnostics (event rate, WOE, IV per bin) as structured output artifacts that can be rendered in the frontend.

4. **Standard scorecard parameterization** — Cross-check Cardre's `ScoreScalingNode` against toad's `base_score`/`base_odds`/`pdo`/`rate` convention for completeness.

### From Sakhi_finance

5. **Counterfactual explanations (DiCE)** — Add a `CounterfactualExplanations` node that generates actionable "what to change" paths from fitted models, complementing the existing SHAP/LIME explainability.

6. **Transaction cash-flow parser** — Add a `TransactionProfileNode` that ingests raw transaction data (bank statement PDFs, CSV) and produces cash-flow behavioral features for thin-file scoring.

7. **Psychometric assessment module** — Add a `PsychometricScoreNode` for survey-based behavioral scoring, feeding into the alternative data manifest pipeline.

8. **Approval roadmap generator** — Combine SHAP drivers + counterfactual paths into a structured `ApprovalRoadmap` artifact for rejected applicants.

### From credit-scoring-mlops

9. **Bayesian hyperparameter optimization (Optuna)** — Add an `OptunaTuningNode` that wraps any model node and runs trial-based HPO with search spaces defined in params, persisting trials to SQLite.

10. **Statistical hypothesis testing gates** — Add a `HypothesisTestNode` allowing users to define formal statistical tests as pipeline gates (e.g., "fail if age-risk Spearman < -0.7"), strengthening the governance/audit narrative.

---

## Other Notable Repos (abbreviated)

| Repo | Stars | Description |
|------|-------|-------------|
| `credit-risk-scoring` (myrazd) | 0 | ML credit risk scoring with SHAP explainability, Streamlit dashboard |
| `toss` (api-evangelist) | 0 | Toss (Korean super-app) APIs.json profile — payments, credit scoring, identity |
| `ondeck` (api-evangelist) | 0 | OnDeck APIs.json — small business lending, credit scoring, loan origination |
| `kakaobank` (api-evangelist) | 0 | KakaoBank APIs.json — mobile banking, credit scoring, open banking |
| `credit-risk-scoring-ml` (Rosesharma13) | 0 | XGBoost + scikit-learn credit risk classification — EDA, model comparison |
