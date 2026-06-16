# Credit Scoring Book — Cardre-Oriented Summary

> Based on: Anderson, *Credit Scoring and Decision Automation* (OCR text, ca. 2007).
> This is a product/spec extraction, not a neutral review. Every chapter is read for what it implies Cardre should build.

---

## Big Takeaways for Cardre

### 1. Cardre should model the full credit-scoring lifecycle, not just WOE + logistic regression
The book's useful path: define business decision → assemble data → define good/bad/indeterminate/exclude → set observation/performance windows → sample train/test/OOT → transform/class variables → select characteristics → handle rejects → segment → fit scorecard → calibrate/scale → validate → implement → monitor → document controls. That maps almost perfectly to Cardre's pathway-node concept.

### 2. Manual binning is not a workaround; it is core product functionality
Chapter 16 strongly supports Cardre's manual/assisted classing UI. The book treats fine classing, coarse classing, WOE/dummy transformations, pooling algorithms, IV/chi-square/rank-order checks, and human supervision as normal scorecard practice, not as optional polish.

### 3. Reject inference should be a separate, auditable scenario layer
The book describes rejects/NTUs/indeterminates as structurally different populations, and reject inference as assumption-heavy. Cardre should not silently "fix" rejects. It should let the user create named reject-inference branches with documented assumptions, method, affected sample, and sensitivity comparison.

### 4. Validation should be an artefact bundle, not a chart page
The validation chapter distinguishes conceptual soundness, predictive power, explanatory adequacy/calibration, stability, implementation testing, monitoring, and independent review. That is basically the outline for Cardre's validation pack.

### 5. Monitoring needs first-class support from day one
The book's monitoring chapter is very Cardre-relevant: score drift, PSI, score-shift reports, through-the-door mix, decision outcomes, override reasons, front-end/back-end reports, performance tracking, vintage/transition views, and chronology logs. Cardre's export should include monitoring definitions, not just development results.

### 6. Classic scorecards remain valuable because they are implementable
The book repeatedly links modelling choices to implementation systems, transparency, monitoring, and operational controls. This supports Cardre's positioning as an auditable scorecard builder rather than a generic AutoML tool.

---

## Chapter-by-Chapter Cardre Summary

| Ch. | Topic | What is useful for Cardre |
|-----|-------|---------------------------|
| 1 | Credit scoring and the business | Treat scorecards as business decision tools, not just statistical models. Cardre should require every project to state product, decision point, population, target decision, and intended use: application, behavioural, collections, fraud, marketing, pricing, or monitoring. |
| 2 | Credit micro-histories | Credit scoring depends on institutional memory: past applications, bureau records, account histories, collections outcomes. Cardre should capture data provenance and source lineage as model artefacts, because "what history was available?" is as important as the algorithm. |
| 3 | Mechanics | Useful grounding for Cardre's core object model: characteristics, attributes/bins, points, odds, cutoffs, decision rules, and score interpretation. Anderson describes scorecards as ranking applicants/accounts by expected future good/bad behaviour based on historical lender experience. Cardre should expose both the statistical model and the operational score table. |
| 4 | Theory of risk | The product should distinguish uncertainty, opacity, adverse selection, moral hazard, and decision risk. In Cardre terms: model-risk notes should be attached to the project, not hidden in analyst commentary. |
| 5 | Decision science | Scorecards support decisions; they do not replace strategy. Cardre should eventually support strategy layers: cutoff, refer, decline, pricing band, limit band, manual review, and champion/challenger policy branches. |
| 6 | Assessing enterprise risk | Less central to retail scorecards, but useful for extending Cardre beyond simple application scorecards. It suggests future templates for SME/commercial scorecards, ratios, migration, portfolio views, and expert overrides. |
| 7 | Predictive statistics | Supports Cardre's need to show assumptions and limitations of regression, trees, discriminant methods, neural nets, and expert models. The key product lesson: technique selection should consider data quality, target, sample size, implementation platform, transparency, and monitoring burden. |
| 8 | Measures of separation and divergence | Very useful. Cardre should implement IV, chi-square, Gini, KS/ROC, divergence, PSI, score-shift reports, calibration tests, and rank-order checks under one consistent metric framework. The book's IV and PSI traffic-light style thresholds are directly productisable, though they should be configurable rather than hard-coded. |
| 9 | Odds and ends | Useful for report generation and explainability. Cardre should include odds/PD translation, score scaling notes, matrix views, and simple forecasting/transition summaries where relevant. |
| 10 | Minds and machines | Very relevant to architecture. The book contrasts software strategies, decision engines, project teams, and steering committees. Cardre should position itself as the modelling-governance workbench that exports to decision engines, rather than pretending to be the whole decision platform. |
| 11 | Data considerations and design | Critical. Cardre should include a data-readiness gate: relevance, accuracy, completeness, missingness, process design, form capture, matching keys, source-system errors, and "lie factor"/self-reported data risks. Data quality should become a signed artefact before modelling begins. |
| 12 | Data sources | Cardre should record source type per variable: application form, internal account history, bureau, behavioural, collections, fraud, open banking, etc. This matters for implementation, leakage prevention, privacy, and monitoring. |
| 13 | Scoring structure | Useful for supporting more than one scorecard shape. Cardre should eventually allow application scorecards, behavioural scorecards, bureau-only scorecards, internal+bureau combined models, matrixed scores, and segmented scorecards. |
| 14 | Information sharing | Useful for bureau-data handling. The book explains positive/negative data sharing, asymmetry, privacy, poaching, and data-quality concerns. Cardre should force bureau variables to carry source, matching, permissible-use, and freshness metadata. |
| 15 | Data preparation | One of the most important chapters for Cardre. The book's GBIX framing — good, bad, indeterminate, exclude — should become a formal target-definition object. Cardre should separately track observation exclusions, policy rejects, NTUs, out-of-scope cases, and performance-window exclusions. |
| 16 | Transformation | Probably the most directly useful chapter. Cardre should support fine classing, coarse classing, WOE, dummy variables, risk measures, monotonicity checks, sparse-bin warnings, zero-cell handling, pooling algorithms, and manual override reasons. Human-supervised binning is a core workflow, not a niche feature. |
| 17 | Characteristic selection | Cardre should make selection explainable: IV, chi-square, Gini, correlation, business relevance, leakage risk, implementation availability, and redundancy. The book warns that high IV can signal leakage and that only information available at decision time should normally be used. |
| 18 | Segmentation | Cardre should treat segmentation as a branchable modelling decision. Every segment split should record rationale, sample size, bad count, scorecard performance, operational implementability, and whether a single scorecard plus interaction terms would be simpler. |
| 19 | Reject inference | Cardre should implement reject inference as optional challenger branches: augmentation, extrapolation, cohort, bivariate, parceling-style approaches, or "no reject inference." Each branch should produce sensitivity evidence and warnings about assumptions. |
| 20 | Scorecard calibration | Cardre needs a calibration workbench. The book distinguishes raw score ranking from calibrated meaning. Cardre should support score scaling, base odds, PDO, score bands, PD mapping, Basel/IFRS-style calibration targets, and explicit reference points. |
| 21 | Validation | This should drive Cardre's validation module. Required sections: conceptual soundness, data quality, target definition, sampling, predictive power, calibration, stability, fairness/adverse impact where relevant, implementation testing, and limitations. Validation should be reproducible from artefacts, not manually assembled screenshots. |
| 22 | Development management issues | Useful for Cardre's project-management layer. The book discusses redevelopment triggers and comparing new vs existing scorecards. Cardre should support challenger comparison against incumbent scorecards, reuse of previous binning/definitions, and rebuild-trigger logs: market shift, data change, policy change, economy, legislation, portfolio drift. |
| 23 | Implementation | Cardre should export implementation-ready artefacts: score tables, variable transformations, SQL/Python scoring code, reason-code logic, decision-engine parameter specs, test cases, and expected outputs. The book's emphasis on IT involvement and parameterised decision engines supports this. |
| 24 | Overrides, referrals and controls | Cardre should include override governance in monitoring exports. Override reasons, authority level, region/branch/user patterns, override rate, and override performance should be tracked. The book treats overrides as controllable and monitorable, not something that can simply be wished away. |
| 25 | Monitoring | Extremely useful. Cardre should generate a monitoring specification alongside the model: front-end population reports, score drift, PSI, variable drift, approval/reject mix, override analysis, bad-rate tracking, vintage views, backtesting, chronology log, and drilldowns by product/channel/segment. |
| 26 | Finance | Useful for future "strategy optimisation" features. Cardre should eventually let users evaluate cutoffs by expected loss, contribution, pricing, provisions, PD/EAD/LGD, recovery, cost, and marginal profitability — not just Gini or bad rate. |
| 27 | Marketing | Useful if Cardre expands into pre-screening or acquisition strategy. Product lesson: marketing scorecards and credit-risk scorecards optimise different outcomes. Cardre should make the target and use-case explicit so users do not accidentally validate a marketing model as a credit-risk model. |
| 28 | Application processing | Cardre should support decision-path simulation: input application → calculated variables → score → cutoffs → policy rules → refer/decline/accept → reason codes. This would make the exported model pack far more useful to implementation teams. |
| 29 | Account management | Useful for behavioural scorecard support. The book's account-management concepts imply future Cardre support for limit management, exposure management, shadow limits, target limits, utilisation, customer status, and behavioural risk strategies. |
| 30 | Collections and recoveries | Cardre could later support collections scorecards and strategy matrices: delinquency stage, roll-rate, cure probability, contact strategy, recovery expectation, and treatment path. This is a natural extension but probably not MVP. |
| 31 | Fraud | Fraud should be treated as a separate decision layer, not blended carelessly into credit risk. Cardre should allow fraud flags/rules as policy gates or exclusion criteria, while warning when fraud-labelled outcomes contaminate credit-risk target definitions. |
| 32 | Regulatory concepts | Cardre should have governance primitives: model owner, approver, validator, version, intended use, limitations, change reason, approval status, and audit trail. The specific regulatory environment has changed since 2007, but the product lesson is durable. |
| 33 | Data privacy and protection | Strong support for Cardre's local-first design. The book's privacy principles imply data minimisation, source documentation, access control, retention metadata, masking/anonymisation options, and export controls. |
| 34 | Anti-discrimination | Cardre should have protected/proxy variable controls: explicit exclusion, proxy detection notes, disparate impact testing, reason-code review, and documented business necessity where legally required. |
| 35 | Fair lending | Cardre should separate credit-risk ranking from responsible-lending/affordability overlays. A borrower can be low credit risk but still unsuitable under affordability or vulnerability rules. This should be a decision-policy layer, not hidden in the model. |
| 36 | Capital adequacy | Useful for future regulatory-capital export. Cardre could support calibrated PD mappings, long-run average notes, downturn considerations, rating grades, and capital-reporting outputs. The chapter is historically Basel-focused, so current implementation would need updated regulatory references. |
| 37 | Know your customer | KYC should be a policy/process gate, separate from the credit score. Cardre can model this as pre-score eligibility checks or post-score decision rules, with clear lineage that KYC failures are not model declines. |
| 38 | National differences | Cardre should not hard-code one regulatory interpretation. It should support jurisdiction-specific packs: UK, EU, US, Brazil, etc. The core workflow can be universal, but validation language, protected classes, data-sharing rules, and report templates should be configurable. |

---

## Concrete Cardre Features This Book Supports

### Near-term / core MVP

1. **Target-definition builder** — Good, bad, indeterminate, exclude, reject, NTU, policy decline, and out-of-scope should be explicit labelled populations.
2. **Observation/performance-window editor** — Cardre should record observation date, application date, account-open date, outcome window, maturity, censoring rules, and decay risk.
3. **Manual binning workbench** — Fine classing, coarse classing, WOE, event rate, goods/bads, missing/special bins, monotonicity, sparse-bin warnings, zero-cell warnings, IV contribution, and override reason.
4. **Variable-selection evidence panel** — IV, chi-square, Gini, correlation, missingness, leakage warning, implementation availability, business rationale, and exclusion reason.
5. **Reject-inference branches** — No inference vs augmentation vs extrapolation vs cohort/bivariate methods, with assumption notes and sensitivity comparison.
6. **Calibration and score-scaling module** — Base score, base odds, PDO, score bands, PD mapping, calibration plots, backtesting, and "score meaning" documentation.
7. **Validation bundle generator** — Conceptual soundness, data integrity, methodology challenge, performance, calibration, stability, limitations, implementation test cases, and approval status.
8. **Monitoring spec export** — PSI, score drift, variable drift, approval-rate drift, override monitoring, vintage tracking, bad-rate tracking, and chronology log.

### Later but very aligned

9. **Decision strategy simulator** — Score + policy rules + cutoffs + referrals + affordability + fraud/KYC gates.
10. **Champion/challenger comparison** — Existing scorecard vs redeveloped scorecard vs reject-inference branch vs segmentation branch.
11. **Profit/EL strategy layer** — Cutoff optimisation using expected loss, contribution, provision, EAD/LGD, pricing, and operating costs.
12. **Jurisdictional governance packs** — UK/EU/US/Brazil templates for privacy, discrimination/fair-lending, validation, and monitoring language.

---

## One Useful Framing for the Cardre Spec

The book's implicit workflow can be turned into a Cardre pathway like this:

```
Import snapshot
→ Data quality and source review
→ Population and exclusion definition
→ Good / bad / indeterminate / exclude labelling
→ Observation and performance-window definition
→ Train / test / OOT split
→ Fine classing
→ Coarse classing and WOE
→ Characteristic selection
→ Optional segmentation branch
→ Optional reject-inference branch
→ Logistic scorecard fit
→ Score scaling and calibration
→ Validation pack
→ Implementation export
→ Monitoring specification
→ Periodic monitoring run
```

That is probably the cleanest product lesson from the book: Cardre should be an evidence-generating scorecard lifecycle tool, not merely a modelling UI.
