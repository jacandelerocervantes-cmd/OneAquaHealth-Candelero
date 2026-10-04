# Mathematical registry

Each added formula must record its identifier, method version, primary source, input domain, theoretical bounds, units, and property tests.

| Formula | Source | Bounds | Version |
| --- | --- | --- | --- |
| Component statistical ordering | OAH QC rule | min <= median <= max; min <= average <= max | 1.0 |
| Component statistical bounds | OAH QC rule | min <= max | 1.0 |
| Majority vote classification | Baseline rule | Discrete class label | 1.0 |
| Dawid-Skene EM observer reliability | Dawid & Skene (1979) | $T_{i,k} \in [0, 1], \sum_k T_{i,k} = 1$; $\pi^{(j)}_{k,l} \in [0, 1], \sum_l \pi^{(j)}_{k,l} = 1$ | 1.0 |
| Split Conformal Classification | Vovk et al. (2005), Angelopoulos & Bates (2023) | Set $\mathcal{C}(x) \subseteq \mathcal{Y}$, Coverage $\ge 1 - \alpha$ | 1.0 |
| Human-Review Queue & Audit Trail | OAH Conformal Abstention Specification | Append-only SQLite store, finite-sample guarantee preserved | 1.0 |
| BMWP / IBMWP Score | Alba-Tercedor & Sánchez-Ortega (1988) | $\text{BMWP} \ge 0$, integer | 1.0 |
| ASPT Score | Alba-Tercedor & Sánchez-Ortega (1988) | $\text{ASPT} \in [1, 10]$ | 1.0 |
| EPT Abundance Ratio | Standard Macroinvertebrate Index | $\text{EPT} \in [0.0, 1.0]$ | 1.0 |
| Shannon Diversity ($H'$) | Shannon (1948) | $H' \ge 0.0$ | 1.0 |
| Simpson Diversity ($1-D$) | Simpson (1949) | $1-D \in [0.0, 1.0)$ | 1.0 |
| Pielou Evenness ($J'$) | Pielou (1966) | $J' \in (0.0, 1.0]$ | 1.0 |
| Chao1 Richness Estimator | Chao & Jost (2012) | $S_{\text{Chao1}} \ge S_{\text{obs}}$ | 1.0 |
| CCME Water Quality Index | CCME (2001) | $\text{WQI} \in [0.0, 100.0]$ | 1.0 |
| Ecological Quality Ratio (EQR) | EU WFD Directive 2000/60/EC | Ratio $\ge 0.0$, Class $\in \{\text{High}, \text{Good}, \text{Moderate}, \text{Poor}, \text{Bad}\}$ | 1.0 |
| $k$-Anonymity Equivalence Class | Sweeney (2002) | Group count $|D_g| \ge k$ | 1.0 |
| Spatial Coordinate Generalization | Standard GIS Grid Generalization | Error margin $\approx \pm \frac{p_{\text{km}}}{2}$; known boundary limitation, see note below | 1.1 |
| Data Subject Consent Validation | OAH Privacy Specification | Active status boolean | 1.0 |
| River-Network Risk Propagation | Precautionary-principle max-over-paths rule (project-defined; not a published hydrology model) | $\text{risk} \in [0.0, \text{initial\_risk}]$, non-increasing downstream along any single path | 1.0 |

### Spatial Coordinate Generalization — boundary limitation (v1.1, corrected by audit)

The original implementation (v1.0) derived the longitude grid step from each point's raw
input latitude. This meant two real points only ~200 m apart (well inside a 5 km cell) could
generalize to different longitudes whenever their latitudes fell on opposite sides of a
floating-point rounding threshold, undermining the module's purpose. Reproduced with
`generalize_coordinates(35.33399, 25.04834, 5.0)` vs `generalize_coordinates(35.33580, 25.04900, 5.0)`:
before the fix these returned different longitudes; after, they match.

Fix (v1.1): the longitude step is now derived from the *generalized* (already-snapped)
latitude, not the raw input latitude, so any two points sharing a latitude cell always share
a longitude grid. A narrower, inherent limitation remains: two points that straddle a
**latitude cell boundary** can still fall into different latitude cells and therefore use
different longitude grids, even if very close together. This is a fencepost effect common to
all fixed-grid spatial generalization methods (not unique to this implementation) and is not
resolved here. See `tests/unit/test_privacy.py::test_known_limitation_points_straddling_a_latitude_cell_boundary_can_diverge`.

## River-Network Risk Propagation

Given a directed acyclic graph of sites with `distance_km` edge weights and a source site with
`initial_risk`, risk decays exponentially with travel distance along a path:

$$\text{risk}(\text{path}) = \text{initial\_risk} \cdot e^{-\text{decay\_per\_km} \cdot d_{\text{km}}}$$

When a node is reachable by more than one path, the reported risk is the **maximum** over all
paths (not the average or sum) — a documented precautionary-principle choice: averaging would
let a low-risk path dilute a genuine risk from another path. A node not reachable from the
source has risk 0.0. The graph itself is never invented by this module: the caller must supply
an explicit edge list; no real hydrology is looked up or assumed. See
`src/oah/risk/river_graph.py` and `scripts/eval_risk.py` (illustrative synthetic topology only).

### Validation of the risk proxy against the advection-dispersion equation (2026-09-25)

`oah.risk.analytical` states exactly what `exp(-decay_per_km * d_km)` approximates. Model (textbook 1D
advection-dispersion-decay, no source claimed beyond the standard equation): $C_t + u C_x = D C_{xx} - k C$
with velocity $u$ (m/s), longitudinal dispersion $D$ (m$^2$/s) and first-order decay $k$ (1/s). "Risk" is read as
the normalised concentration $C/C_0$; that reading is an interpretation, not a physical identity.

**Steady continuous release** at $x = 0$ into a semi-infinite reach, $C(0) = C_0$. The bounded solution is
$C(x) = C_0 e^{-\lambda x}$ with
$$\lambda = \frac{\sqrt{u^2 + 4kD} - u}{2D} = \frac{2k}{u + \sqrt{u^2 + 4kD}} \to \frac{k}{u} \text{ as } D \to 0.$$
So the proxy is **exact** when `decay_per_km` $= 1000\,k/u$ and dispersion is negligible (tested to 1e-12 on a chain).
With dispersion the true decay is slower, so the proxy **underestimates** downstream risk (anti-conservative). With
$\varepsilon = kD/u^2$ the ratio of exponents is $\lambda/(k/u) = (\sqrt{1 + 4\varepsilon} - 1)/(2\varepsilon)$:

| $\varepsilon = kD/u^2$ | 0.01 | 0.1 | 1 |
| --- | --- | --- | --- |
| exponent ratio (true / proxy) | 0.990 | 0.916 | 0.618 |
| proxy error after 3 proxy e-folds | -2.9 % | -22.3 % | -68.2 % |

The closed form was checked against an independent central-difference solver of the steady equation (three parameter
sets, relative error below 2e-3). The pulse solution
$C(x, t) = \frac{M/A}{\sqrt{4\pi D t}} \exp\left(-\frac{(x - ut)^2}{4Dt} - kt\right)$ was checked by the residual of the PDE.

**Instantaneous release (pulse).** Along the cloud centre ($x = ut$) the concentration falls as
$t^{-1/2} e^{-kt}$, so the ratio between distance $x$ and reference $x_0$ is $\sqrt{x_0/x}\,e^{-k(x - x_0)/u}$; $D$ and the
mass cancel. The proxy has only the exponential factor, so for a pulse it **overestimates** the downstream centre
concentration by $\sqrt{x/x_0}$ (conservative).

**What the proxy does not model** (documented, not fixed): dilution at confluences with clean tributaries (proxy
conservative); superposition of several sources, which is exact for the linear equation while the proxy handles one
source (anti-conservative if two sources feed the same site); time dependence, storage zones and lateral inflow.

**Implied physical rate of the demo setting.** `DECAY_PER_KM = 0.15` in `oah.risk.demo_topology` corresponds, at an
assumed 0.3 m/s, to $k \approx 3.9$ per day (`implied_decay_rate_per_day`). Whether that is a plausible decay rate for a
given pathogen or contaminant was **not** checked against literature; the value stays illustrative and synthetic.

QC reports record profile, finding, site, UCUM-code, and capped-example counts without changing observations.
| Configured physical range | OAH QC rule | indicator-specific lower/upper bounds | 1.0 |

## Synthetic citizen-science campaign simulator

The synthetic campaign generator is version 1.0 and uses `numpy.random.default_rng(seed)`. It
accepts existing real Location identifiers as labels only; it neither retrieves nor models any
real Location data.

For $K$ taxa families and $N$ observers, it models specimens per site with ground-truth true families.
Each specimen is assigned `annotators_per_specimen` ($\ge 2$, default 3) distinct observers drawn without replacement.
Observer skills follow a mixture model:
- Weak observers ($j < \lfloor N/4 \rfloor$): skill $s_j \sim U(0.30, 0.55)$ with standard diagonal confusion matrix.
- Adversarial observer (when $N \ge 4$): skill $s_j \sim U(0.70, 0.90)$ with a confusion matrix that systematically swaps family 0 and family 1 (row 0 reports family 1 with probability $s_j$, row 1 reports family 0 with probability $s_j$).
- Standard observers: skill $s_j \sim U(0.55, 0.95)$ with standard diagonal confusion matrix.

Each observation is generated as $(specimen\_id, site\_id, observer\_id, reported\_family, timestamp)$.
The stored true family per specimen is simulator ground truth. All metrics, reliability estimates, prediction
intervals, and review outcomes computed on this data measure the simulator only and must never be
presented as real ecological performance.

## Dawid-Skene Observer Reliability Model

**Primary Source**: Dawid, A. P., & Skene, A. M. (1979). Maximum Likelihood Estimation of Observer Error-Rates Using the EM Algorithm. *Applied Statistics*, 28(1), 20-28.

Given $M$ specimens, $J$ observers, $K$ classes, and an observed annotation table where observer $j$ reports label $y_{i, j} \in \{0, \dots, K-1\}$ for specimen $i$:

### Baseline Majority Vote
$$\hat{Z}_i = \arg\max_{k \in \{0, \dots, K-1\}} \sum_{j \in \text{Obs}(i)} \mathbb{I}(y_{i, j} = k)$$
Ties are broken deterministically by picking the class with the smallest index in canonical `classes`.

### Dawid-Skene EM Algorithm
- **Initialization**: Posteriors $T_{i, k} = P(Z_i = k)$ are initialized from normalized majority vote counts:
  $$T_{i, k}^{(0)} = \frac{\sum_{j \in \text{Obs}(i)} \mathbb{I}(y_{i, j} = k)}{|\text{Obs}(i)|}$$
- **M-step (with Dirichlet prior $\text{Dir}(\alpha+1)$ smoothing)**:
  - Class priors:
    $$\pi_k = \frac{\sum_{i=1}^M T_{i, k} + \alpha}{M + K \cdot \alpha}$$
  - Observer confusion matrices ($\pi^{(j)}_{k, l} = P(Y_{i, j} = l \mid Z_i = k)$):
    $$\pi^{(j)}_{k, l} = \frac{\alpha + \sum_{i \in \text{Obs}(j), y_{i, j} = l} T_{i, k}}{K \alpha + \sum_{i \in \text{Obs}(j)} T_{i, k}}$$
- **E-step**:
  $$\ln w_{i, k} = \ln \pi_k + \sum_{j \in \text{Obs}(i)} \ln \pi^{(j)}_{k, y_{i, j}}$$
  $$T_{i, k} = \frac{\exp(\ln w_{i, k} - \max_m \ln w_{i, m})}{\sum_{l=0}^{K-1} \exp(\ln w_{i, l} - \max_m \ln w_{i, m})}$$
- **Un-smoothed Marginal Log-Likelihood**:
  $$L = \sum_{i=1}^M \ln \left( \sum_{k=0}^{K-1} \pi_k \prod_{j \in \text{Obs}(i)} \pi^{(j)}_{k, y_{i, j}} \right)$$
- **Penalized MAP Objective**:
  $$Q_{\text{MAP}} = L + \alpha \sum_{k=0}^{K-1} \ln \pi_k + \alpha \sum_{j=0}^{J-1} \sum_{k=0}^{K-1} \sum_{l=0}^{K-1} \ln \pi^{(j)}_{k, l}$$
  *Note on Monotonicity*: With the Dirichlet prior M-step update for priors $\pi_k$, the MAP objective $Q_{\text{MAP}}$ is strictly non-decreasing at every iteration for any dataset. The un-smoothed log-likelihood $L$ is monotonic non-decreasing when $\alpha = 0$.

### Method Recommendation Function & Threshold Selection

The function `recommend_method(annotations, threshold=50.0)` evaluates the mean number of annotations per observer:
$$\bar{a} = \frac{|\text{annotations}|}{|\text{observers}|}$$
- If $\bar{a} \ge 50.0$: returns `"dawid-skene"`
- If $\bar{a} < 50.0$: returns `"one-coin"` (see the one-coin section below; not `"majority-vote"`,
  which the function never returns)

#### Held-Out Grid Derivation (Seeds 100–109) & Multi-Seed Evaluation

| Regime | Spec/Site | Ann/Spec | Mean Ann/Obs | Held-Out Win Rate (100-109) | Eval Win Rate (42-51) | Eval Win Rate (200-229) | Recommended Method |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **15x3** | 15 | 3 | ~16.9 | 10% | 0% | 13% | `one-coin` |
| **15x5** | 15 | 5 | ~28.1 | 50% | 90% | 73% | `one-coin` |
| **70x3** | 70 | 3 | ~78.8 | 90% | 90% | 100% | `dawid-skene` |
| **70x5** | 70 | 5 | ~131.2 | 100% | 100% | 100% | `dawid-skene` |

Among these four measured regimes, the lowest with a held-out win rate of at least $80\%$ is **70x3** (~78.8 ann/obs), not 50. No regime was measured between ~28.1 and ~78.8 ann/obs, so $50.0$ sits inside that unmeasured gap: it is a project choice, not a measured minimum. `scripts/eval_reliability.py` prints this same qualification from a fresh run of the grid, so this table and that script cannot drift apart silently.

### One-coin Dawid-Skene for the sparse regime (added 2026-09-25)

`oah.reliability.run_one_coin`. Each annotator $j$ has one accuracy $a_j$: $P(\text{label}=l \mid \text{true}=k) = a_j$ if
$l = k$, else $(1 - a_j)/(K - 1)$. EM with MAP priors: Dirichlet$(\alpha + 1)$ on class frequencies (as in the full model)
and Beta$(2, 2)$ on every $a_j$, so the M-step is $a_j = (c_j + 1)/(n_j + 2)$ with $c_j = \sum_i T_{i,l_{ij}}$ the expected
number of correct labels; the MAP objective is non-decreasing. Parameters per annotator: 1, against $K(K-1)$ for the full
model. Cannot represent systematic confusion between specific classes. The one-coin model is the special case of
Dawid-Skene (1979) with a symmetric confusion matrix; no other source is claimed. An empirical-Bayes variant (shrinking
each $a_j$ toward the pooled accuracy) was prototyped and gave no measurable gain, so it was not kept.

**Evidence** (synthetic simulator, 8 observers, 4 families; fresh seeds 300-339 for accuracy, 400-409/500-519 for
calibration and workload; `tests/unit/test_one_coin.py` re-checks the direction with smaller seed sets):

| Regime (spec/site x ann/spec) | MV acc | full DS acc | one-coin acc | one-coin vs MV (paired, 40 seeds) |
| --- | --- | --- | --- | --- |
| 15 x 3 | 0.775 | 0.629 | 0.783 | +0.008; better in 52 %, tie or better in 70 % (no evidence of a difference) |
| 30 x 3 | 0.764 | 0.769 | 0.788 | +0.024 |
| 30 x 5 | 0.871 | 0.914 | 0.909 | +0.038 |
| 70 x 5 | 0.866 | 0.929 | 0.914 | +0.048; full DS still better than one-coin in 75 % of seeds |

Accuracy alone therefore does **not** justify one-coin over majority vote in the poorest regime; it does avoid the large
loss of full DS there. Its main value is calibration and reviewer workload (conformal at target coverage 0.90, single
calibration pool, 10 calibration and 20 test campaigns; posteriors used as scores):

| Regime | Posterior source | ECE | Coverage | Singleton (auto-resolved) | Ambiguous (to review) |
| --- | --- | --- | --- | --- | --- |
| 15 x 3 | majority vote, add-one smoothed | 0.327 | 0.962 | 22.7 % | 77.3 % |
| 15 x 3 | full DS | 0.243 | 0.922 | 15.3 % | 84.7 % |
| 15 x 3 | **one-coin** | **0.115** | 0.887 | **64.3 %** | 35.7 % |
| 30 x 3 | majority vote / DS / **one-coin** | 0.330 / 0.099 / **0.073** | 0.958 / 0.893 / 0.878 | 23.3 % / 51.4 % / **73.9 %** | |
| 70 x 5 | majority vote / DS / one-coin | 0.376 / 0.030 / 0.032 | 0.938 / 0.885 / 0.889 | 71.3 % / 94.7 % / 96.9 % | |

Coverage of the one-coin and DS sets sits slightly below the 0.90 target (0.877-0.889): calibration used only 10
campaigns whose specimens share annotators, so the effective calibration size is smaller than the specimen count. The
majority-vote figures over-cover (0.94-0.96) and therefore waste reviewer time.

**Misspecification check (one-off run, not in the test suite; 16 seeds, 8 observers, 4 classes).** The simulator's
observers are symmetric, which is exactly the one-coin model, so a second synthetic generator was used in which every
annotator sends 70 % of its errors to a fixed "partner" class (A<->B, C<->D), i.e. structured confusion that one coin
cannot represent. Accuracy: sparse regime (45 specimens, 3 annotators each) majority vote 0.824, full DS 0.583,
one-coin 0.828; abundant regime (210 specimens, 5 annotators) 0.913 / 0.920 / 0.925. One-coin was not hurt in this
family of misspecification. This is one family of violations only; systematic errors that are shared by all annotators
and correlated across specimens (for example a look-alike taxon pair that everybody confuses) were not tested.

### Limitations & Assumptions
1. **Sample Complexity / Threshold Rule**: When annotations per observer fall below the configured $50.0$ threshold (e.g. regime 15x3 with ~16.9 ann/obs), MAP-EM overfits observer parameters ($4 \times 4 = 16$ per observer) and performs below Majority Vote in the measured regimes; the threshold itself is a project choice inside an unmeasured gap (see above), not a proven boundary.
2. **Identifiability & Label Switching**: The EM algorithm is unsupervised. If all observers exhibit accuracy worse than random guessing or if labels are symmetrically permuted, EM can converge to a permuted/flipped mode unless initialized near plausible class distributions (e.g. via majority vote).
3. **Synthetic Data Boundary**: All reliability estimations and evaluation metrics calculated on synthetic campaign data evaluate simulator consistency and model mechanics, NOT real-world ecological performance.

## Split Conformal Prediction & Conformal Abstention

**Primary Sources**:
- Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning in a Random World*. Springer.
- Angelopoulos, A. N., & Bates, S. (2023). A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification. *Foundations and Trends® in Machine Learning*, 16(4), 494-591.

Given posterior class probability estimates $\hat{P}(Y = y \mid X = x)$ derived via either Majority Vote or Dawid-Skene EM (selected dynamically by `recommend_method`), split conformal prediction constructs prediction sets with guaranteed finite-sample coverage $1 - \alpha$.

### Nonconformity Score & Finite-Sample Quantile

1. **Nonconformity Score**: For each specimen $i$ in a calibration set of size $n$, with true class $y_i^{\text{true}}$:
   $$s_i = 1 - \hat{P}(Y_i = y_i^{\text{true}} \mid X_i)$$

2. **Calibration Quantile (Finite-Sample Correction)**: For target misclassification rate $\alpha \in (0, 1)$, the calibration cutoff $q$ is computed as the $k$-th order statistic:
   $$k = \lceil (n + 1)(1 - \alpha) \rceil$$
   $$q = s_{(k)} \quad \text{where } s_{(1)} \le s_{(2)} \le \dots \le s_{(n)}$$
   The quantile selection uses method `"higher"` so that $q = s_{(k)}$.
   If $n < \lceil 1/\alpha \rceil$, the calibration set is insufficient and a `ValueError` is raised.

3. **Prediction Set Construction**: For a test specimen $x$:
   $$\mathcal{C}(x) = \{y \in \mathcal{Y} : 1 - \hat{P}(Y = y \mid x) \le q\}$$

### Theoretical Coverage Property

Under exchangeability of calibration and test examples, the prediction sets satisfy:
$$P(Y_{n+1} \in \mathcal{C}(X_{n+1})) \ge 1 - \alpha$$

### Expected Calibration Error (ECE)

To assess posterior probability quality across 10 equal-width bins $B_m \subset (0, 1]$:
$$\text{ECE} = \sum_{m=1}^B \frac{|B_m|}{N} |\text{acc}(B_m) - \text{conf}(B_m)|$$
where $\text{conf}(B_m)$ is the average confidence of predictions in bin $B_m$ and $\text{acc}(B_m)$ is their empirical accuracy.

### Human-Review Queue & Immutable Audit Trail

- **Autonomous Resolution**: Prediction sets with $|\mathcal{C}(x)| = 1$ (singletons) are resolved autonomously.
- **Human Abstention Queue**: Prediction sets with $|\mathcal{C}(x)| \ne 1$ (empty sets $|\mathcal{C}(x)| = 0$ or ambiguous sets $|\mathcal{C}(x)| \ge 2$) are submitted to the human review queue.
- **Append-Only Immutability**: All submission and review actions record `AuditEvent` entries. SQLite triggers `prevent_audit_update` and `prevent_audit_delete` prohibit `UPDATE` or `DELETE` operations on `audit_events`, raising `sqlite3.IntegrityError` / `sqlite3.OperationalError`.

### Assumptions & Limitations

1. **Exchangeability Assumption**: Calibration and test specimens must be independent and identically distributed (exchangeable). Calibration and test sets are sampled using disjoint seed ranges (e.g. seeds 1000–1029 vs 2000–2029) to prevent data leakage.
2. **Finite-Sample Size Bound**: Calibration sets must satisfy $n \ge \lceil 1/\alpha \rceil$ (minimum 20 specimens for $\alpha=0.05$).
3. **Synthetic Data Tagging**: All conformal prediction sets, evaluation scores, and review queue records generated from synthetic campaign data measure the simulator only and carry `tag = "synthetic"`.

### Class-conditional (Mondrian) conformal prediction

`oah.uncertainty.conformal.calibrate_class_conditional` / `predict_class_conditional_set`. For each true
class $c$ the calibration scores are $s_i = 1 - \hat P(Y_i = c \mid X_i)$ over calibration specimens whose
**true** class is $c$, with the same finite-sample quantile as above, giving a cutoff $q_c$. The set is
$$\mathcal{C}(x) = \{y : 1 - \hat P(Y = y \mid x) \le q_y\}$$
and, under exchangeability *within each class*, $P(Y \in \mathcal{C}(X) \mid Y = c) \ge 1 - \alpha$ for every class
(Vovk et al. 2005, class-conditional/Mondrian conformal predictors), not only on average. Source for the
marginal version is the reference above; this per-class construction is the standard Mondrian taxonomy applied
to the same score.

- **Insufficient classes.** A class with fewer than $\lceil 1/\alpha \rceil$ calibration examples is rejected
  (`on_insufficient="raise"`, default). With `"include"` its cutoff is 1.0: the guarantee holds trivially but that
  class enters every set, so almost no set is a singleton (all such specimens go to human review).
- **Calibration labels must be expert-verified.** Noisy calibration labels break the guarantee. In this repository
  the synthetic ground truth plays that role, so all numbers are simulator results.
- **Workload.** `set_size_summary` reports empty/singleton/ambiguous rates: only singletons are resolved
  autonomously (see the review queue rules above), so every extra label costs reviewer time.
- **Evidence** (`tests/unit/test_conformal_class_conditional.py`, seeded, synthetic):
  - Constructed scenario (class B is 20 % of the data and the model is unsure on it; class A is easy),
    $\alpha = 0.1$: marginal conformal covers A at 100 % but B at only **54 %**; class-conditional covers
    A at 90.6 % and B at 88.4 % (single calibration draw; the guarantee is in expectation, tests use tolerance 0.86).
  - On the project's own simulator with Dawid-Skene posteriors (balanced classes, symmetric confusion) the marginal
    method already covered every class at 0.90-0.92, so the class-conditional variant showed **no measurable gain
    there**; it is a safeguard against heterogeneous class difficulty, not a demonstrated improvement on this simulator.
  - Same run with a rare class (15 % of Perlidae): class-conditional coverage of that class was 0.88 against 0.92
    marginal at n = 501 test specimens, i.e. within sampling noise but not above target; rare classes need more
    calibration data.

## Ecological & Water Quality Indices

### Biotic Indices (BMWP, ASPT, EPT Ratio)

**Primary Sources**:
- Alba-Tercedor, J., & Sánchez-Ortega, A. (1988). Un método rápido y simple para evaluar la calidad biológica de las aguas corrientes. *Limnetica*, 4, 51-56.

1. **Biological Monitoring Working Party (BMWP / IBMWP)**:
   $$\text{BMWP} = \sum_{i=1}^{S} s_i$$
   where $s_i$ is the regional family tolerance score passed as explicit input mapping.

2. **Average Score Per Taxon (ASPT)**:
   $$\text{ASPT} = \frac{\text{BMWP}}{S} \quad (S > 0)$$
   bounded by $\min(s_i) \le \text{ASPT} \le \max(s_i)$.

3. **EPT Abundance Ratio**:
   $$\text{EPT} = \frac{N_{\text{Ephemeroptera}} + N_{\text{Plecoptera}} + N_{\text{Trichoptera}}}{N_{\text{total}}}$$

### Diversity & Richness Estimators (Shannon, Simpson, Pielou, Chao1)

**Primary Sources**:
- Chao, A., & Jost, L. (2012). Coverage-based rarefaction and extrapolation. *Ecology*, 93(12), 2533-2547.

1. **Shannon Diversity**:
   $$H' = -\sum_{i=1}^{S} p_i \ln p_i$$

2. **Simpson Diversity**:
   $$1 - D = 1 - \sum_{i=1}^{S} p_i^2$$

3. **Pielou Evenness**:
   $$J' = \frac{H'}{\ln S} \quad (S \ge 2)$$

4. **Chao1 Bias-Corrected Richness Estimator**:
   $$S_{\text{Chao1}} = S_{\text{obs}} + \frac{f_1(f_1 - 1)}{2(f_2 + 1)}$$

### Water Quality Index (CCME WQI 1.0) & EQR

**Primary Sources**:
- Canadian Council of Ministers of the Environment (CCME). (2001). *Canadian Water Quality Index 1.0: Technical Report*. CCME, Winnipeg.

1. **CCME WQI 1.0**:
   - $F_1 = (u_v / M_v) \times 100$ (Scope: % of failed parameters)
   - $F_2 = (u_t / M_t) \times 100$ (Frequency: % of failed tests)
   - $\text{excursion}_j = (v_j / \text{limit}_j) - 1$ (upper bounds) or $(\text{limit}_j / v_j) - 1$ (lower bounds)
   - $nse = \frac{\sum \text{excursion}_j}{M_t}$ (normalized by total tests $M_t$)
   - $F_3 = \frac{nse}{0.01 \cdot nse + 0.01}$ (Amplitude)
   $$\text{CCME WQI} = 100 - \frac{\sqrt{F_1^2 + F_2^2 + F_3^2}}{1.732}$$
   - CCME 2001 Table 3 classification (`classify_ccme_wqi`): Excellent $[95, 100]$, Good $[80, 95)$,
     Fair $[65, 80)$, Marginal $[45, 65)$, Poor $[0, 45)$. Used by `GET /sites` to color-bucket
     each location for a map view (`ui_status`: Excellent/Good $\to$ good, Fair/Marginal $\to$
     moderate, Poor $\to$ poor); the underlying score and CCME class are always reported too.

2. **Ecological Quality Ratio (EQR)**:
   $$\text{EQR} = \frac{\text{Observed}}{\text{Reference}}$$
   - WFD status classes: High ($\ge 0.8$), Good ($[0.6, 0.8)$), Moderate ($[0.4, 0.6)$), Poor ($[0.2, 0.4)$), Bad ($[0.0, 0.2)$).

### Privacy Controls & Geographic Generalization

**Primary Sources**:
- Sweeney, L. (2002). k-Anonymity: A model for protecting privacy. *International Journal of Uncertainty, Fuzziness and Knowledge-Based Systems*, 10(05), 557-570.

1. **k-Anonymity Group Equivalence**:
   For quasi-identifier set $Q = \{q_1, \dots, q_m\}$, dataset $D$ satisfies $k$-anonymity if for every equivalence class key $g = (rec[q_1], \dots, rec[q_m])$:
   $$|D_g| \ge k$$
   If any group has $|D_g| < k$ for $k > 1$, a `ValueError` is raised listing all violating groups with key values and counts.

2. **Geographic Coordinate Generalization**:
   For target spatial resolution $p_{\text{km}} > 0.0$:
   $$\Delta \text{lat} = \frac{p_{\text{km}}}{111.32} \quad (\text{degrees})$$
   $$\Delta \text{lon} = \frac{p_{\text{km}}}{111.32 \cdot \max(\cos(\text{radians}(\text{lat})), \cos(\text{radians}(89.9^\circ)))} \quad (\text{degrees})$$
   $$\text{lat}_{\text{gen}} = \text{round}\left(\frac{\text{lat}}{\Delta \text{lat}}\right) \times \Delta \text{lat}, \quad \text{lon}_{\text{gen}} = \text{round}\left(\frac{\text{lon}}{\Delta \text{lon}}\right) \times \Delta \text{lon}$$
   *Error Bounds & Limitation*: Maximum spatial displacement error margin is $\approx \pm \frac{p_{\text{km}}}{2}$ along each dimension under mid-latitude conditions. Spatial coordinate grid snapping reduces location precision but does **NOT** guarantee $k$-anonymity in sparse areas without quasi-identifier density enforcement (`enforce_k_anonymity`).

3. **Data Subject Consent Lifecycle**:
   Consent record is active at time $t$ if:
   $$t \ge t_{\text{granted}} \quad \text{and} \quad (t_{\text{revoked}} = \text{None} \lor t < t_{\text{revoked}})$$





## Censored quantities and sandbox data freshness

**CCME WQI rule (project decision, not taken from CCME 2001).** A FHIR `Quantity` with a
`comparator` (`<`, `<=`, `>=`, `>`) states a bound, not a measurement (FHIR R4 `Quantity`). CCME F1
and F2 need only pass/fail and F3 needs the excursion, which is 0 for a pass. So a comparator whose
bound alone proves compliance is scored exactly, without estimation: for an upper-limit parameter
`< b` / `<= b` with `b <= limit`; for a lower-limit parameter (e.g. dissolved oxygen) `> b` / `>= b`
with `b >= limit`. Such values enter the index with `value = b` (identical F1-F3) and are counted in
`censored_quantities_counted_as_pass`. Every other comparator (detection limit above the objective, or
a bound on the failing side) is **indeterminate**: excluded and counted in `skipped_censored_quantities`,
never replaced by zero, the limit, or half the limit. `oah.indices.apply_to_sandbox.classify_quantity`
implements this; `oah.qc.statistics.censored_quantities` warns on every comparator-bearing quantity.
As of 2026-09-23 the public sandbox has none (1,256 quantities inspected), so results are unchanged.

## Left-censored summary statistics (`oah.indices.censored`)

For descriptive statistics of non-detect data (not used by the WQI, which needs no estimation):

- **Kaplan-Meier (KM), `kaplan_meier_left_censored`.** Data are flipped, `y = M - x` with `M = max(x)`,
  turning `x < DL` into right-censored `y`; the KM survival curve gives the mean (area under S) and
  median (smallest `t` with `S <= 0.5`, midpoint when `S = 0.5` exactly, so uncensored data reproduce the
  sample mean and median). Convention: if the smallest observation is censored, it is treated as detected
  at its limit so the curve reaches zero. Assumption-free; handles multiple limits natively.
- **Regression on order statistics (ROS), `ros_left_censored`.** Log-normal model: `ln(x) = a + b*z(pp)`
  fitted on detects; non-detects get model values from the fitted line and are pooled with detects.
  Plotting positions use the Helsel-Cohn exceedance construction: `pe_j = pe_{j+1} + A_j/(A_j+B_j) *
  (1 - pe_{j+1})` (A_j detects in `[DL_j, DL_{j+1})`, B_j observations known to lie below `DL_j`);
  detects in interval j: `pp = (1-pe_j) + (pe_j - pe_{j+1}) * r/(A_j+1)`; non-detects at `DL_j`:
  `pp = (1-pe_j) * r/(C_j+1)`. Needs >= 3 positive detects with >= 2 distinct values.
- **Recommended report, `summarize_censored`:** median by KM, mean by ROS (KM mean as fallback), `km_mean`
  always shown, explicit warnings (`high-censoring` above 50 %, `small-sample` below n = 20, etc.; both
  thresholds are project conventions taken from the simulations, not from a cited source).

**Evidence (seeded simulations vs known truth; `tests/unit/test_censored_stats.py`; synthetic data, so
this measures the estimators, not real ecology).** Log-normal(0,1), n = 300, bias of the estimate:

| Scenario | KM median | ROS mean | KM mean | Substitution DL/2 median |
| --- | --- | --- | --- | --- |
| One limit, ~50 % censored | +0.03 | -0.00 | **+0.24** | -0.22 |
| Mixed limits 0.2/0.8/1.6 | +0.01 | -0.01 | -0.00 | **-0.16** |

Outside the test suite (one-off runs, same method) with non-log-normal truth the KM median stayed
unbiased (<= 0.005 for gamma and bimodal mixtures); ROS degraded modestly (mean bias up to about -0.08,
median bias up to +0.09 with mixed limits on the bimodal mixture). At n = 20 every method had RMSE about
0.5 for the mean, so no method rescues tiny samples. **Provenance caveat:** the ROS plotting positions
were implemented from the Helsel-Cohn construction as recalled by the project, and are validated by
simulation against known truth only, not against a published worked example or reference software;
confirm against a primary source before citing the formulas externally.

**Freshness policy:** `fetch_sandbox_*` use a snapshot only if it is younger than
`SNAPSHOT_MAX_AGE_SECONDS` (24 h); otherwise they read the live sandbox, and fall back to a stale
snapshot only when the live read fails (logged with its age). If neither is available they raise
`SandboxDataUnavailableError` instead of returning an empty list labeled real-sandbox. This was added
after the CLI was found analysing a 2-day-old snapshot (390 Observations) while the live sandbox had 414.


## CCME WQI input rules and non-compensatory veto (2026-09-25 corrections)

Three defects in how sandbox data reached `ccme_wqi` were found and fixed; results computed before
2026-09-25 (for example the Loc-Almyros score 19.928 quoted in earlier ledger entries) are **invalid**.
On the same 390-Observation snapshot the corrected score is 100.0 with low confidence (see below).

1. **Direction.** Minimum-limit parameters (dissolved oxygen) were scored as maximum-limit ones because the
   direction was guessed from the name and the caller's own `is_lower` flag was dropped. `ccme_wqi` now takes
   `(parameter, observed, limit, is_lower)` and `oah.indices.water_quality.excursion` implements CCME 2001:
   `observed/limit - 1` above a maximum, `limit/observed - 1` below a minimum, 0 when met, 999 sentinel for a
   non-positive divisor.
2. **One test per summary Observation.** Sandbox Observations carry period statistics as components
   (`average`, `median`, `minimum`, `maximum`, `std-dev`). Previously every component was scored as a separate
   test, including the standard deviation. Now the **median** is the single representative value (average as
   fallback); dispersion and extremes are never scored. Project decision: CCME 2001 assumes individual tests, so a
   period median is a proxy.
3. **Do not score untrustworthy data.** An Observation whose statistics violate `min <= median <= max` or
   `min <= average <= max` (`check_statistics`) is excluded (`skipped_qc_inconsistent_observations`); a value that
   is physically impossible by definition (pH outside 0-14, negative concentration) is excluded
   (`skipped_physically_impossible_observations`). No ecological range is invented. In the public sandbox the
   averages and extremes of many Observations are stored about 10^4 times too large (for example pH 76 800 next to a
   median of 7.68); this is an upstream data-quality problem, reported here, not corrected.

**Units (added 2026-09-26).** Each limit has an explicit unit (`PARAMETER_UNITS`); the observed value is converted to it
(`convert_to_unit`) before comparison, and an unknown, missing or incompatible unit is excluded and counted
(`skipped_unit_mismatch_observations`). Before this fix the generic conductivity code, reported in mS/cm, was compared
with a limit in uS/cm and always passed; Loc-Almyros moved from 100.0 to 69.46 (two conductivity readings of 18.4 and 12.2
mS/cm against a 2500 uS/cm proxy limit that is not meaningful for a brackish coastal stream).

**Confidence.** A site is `low_confidence` if it has fewer than 4 distinct parameters (CCME 2001) **or** at least 50 %
of its scorable Observations were excluded for data quality (project convention). Loc-Almyros: 85 of 97 scorable
Observations excluded (88 %), 12 measurements used, 0 failures, `low_confidence`. This example predates the units fix directly above: after that fix the same location scored 69.46, not 100.0 (see "Units (added 2026-09-26)"). The exclusion mechanics illustrated here (which observations are dropped and why) are still correct; only the final score is stale. A score of 100 means "nothing usable exceeded a limit", not "the site is healthy", regardless of which run produced it.

**Non-compensatory veto (project convention, not from CCME 2001 or the WFD).** For each parameter take the worst
test's excursion. If it is at least `VETO_EXCURSION = 1.0` (twice a maximum limit, or half a minimum), the veto fires
for that parameter, whatever the composite says; `veto_parameters` lists them worst first and
`worst_parameter_excursion` is the maximum. `eclipsed` is true when the veto fired while the composite class is
Excellent, Good or Fair. It is inspired by the WFD one-out, all-out principle but requires a severe, not any,
exceedance. Worked example (tests): five parameters within limits plus nitrate at 300 mg/L against 50 mg/L gives
CCME WQI 70.44 (Fair), excursion 5.0, veto and eclipsing both true. Limitation: the threshold is untuned and the
composite is only as good as the excursions it is built from.


## Numeric-grounding check for LLM text (`oah.explain.grounding`, rewritten 2026-09-25)

The check flags numbers and units in generated text that the evidence does not support. It is purely syntactic; the
model's explanation is always returned, with `grounded`, `ungrounded_numbers` and `unit_mismatches` shown to the reviewer.

**Matching rule (project design; no external source).** A number written with $d$ decimals matches evidence $e$ when
$|t - e| \le 0.5 \cdot 10^{-d}$, in exact decimal arithmetic (rounding half up or half down; truncation beyond that is not
accepted). Percentages: `55%` matches a fraction $0.55$ (via $100e$), an evidence value above 1, or an evidence value whose
unit is `%`; `0.55%` does not match a fraction. Units: a dict with a `unit` key gives its numeric fields that unit; the same
number written with a different known unit (ug/L for mg/L, degF for Cel, mS/cm for uS/cm, % for mg/L) is a `unit_mismatch`.
Numbers are read from ASCII or full-width digits, `1,256`, `2.5e3`, signed values (`-` or U+2212, only when not part of a
range such as `2013-2015`) and spelled-out numbers up to millions (`nineteen`, `twenty-five`, `eighty-seven point five`).
Always allowed: 0, 1, 100, the length of any list in the evidence, and the size of a nested object whose values are all
numbers (a distribution); the size of a record is not allowed.

**Evidence** (`scripts/eval_grounding.py`, `tests/unit/test_grounding_adversarial.py`; synthetic cases written by the project
authors, deterministic). The "curated + generated" set was built while inspecting failures of the original check, so it is
not independent. The holdout set was written after the new implementation and measured before any further change.

| Set | Check | Faithful cases wrongly rejected | Fabricated cases detected |
| --- | --- | --- | --- |
| curated + generated (58 valid, 74 adversarial) | original | 15 (25.9 %) | 64 (86.5 %) |
| curated + generated | rewritten | 0 (0.0 %) | 74 (100 %) |
| holdout (18 valid, 17 adversarial) | original | 3 (16.7 %) | 9 (52.9 %) |
| holdout | rewritten | 0 (0.0 %) | 17 (100 %) |

Defects of the original check that the harness exposed: percentages of fractions, thousands separators, en-dash ranges,
scientific notation, full-width digits and half-rounding rejected faithful text; spelled-out numbers, unit swaps, percent
misuse and mixed-precision numbers passed unflagged. Two defects of the rewrite were found by the harness itself and fixed
before the figures above: a record's key count was accepted as a valid number, and a unit followed by a word (`ug/L against`)
was not recognised.

**Discourse counts (added 2026-09-26 after a real run):** a count of 2-10 directly before `points`, `things`, `reasons`, `steps`, `options`, `caveats`, `notes` or `questions` is exempt, because it numbers the writer's own remarks (`Two points for your decision`). Data nouns are not exempt. Motivation: in the first two real runs 2 of 4 outputs were flagged only for such words.

**What it cannot do (asserted in the tests as documented blind spots):** a correct number on the wrong claim (`limit 18.5`
when 18.5 is the temperature), swapped labels (`Baetidae 0.45` when 0.45 belongs to Perlidae), and a count reused for another
quantity. **Flagged on purpose (false alarms by design):** derived numbers (3 of 15 written as 0.2 or 20 %), sums, factors
written as words (`six`), and European decimal commas (`19,93` is read as 19 and 93). Fractions written as words
(`half`, `a third`) are not parsed as numbers. The 100 % figures apply only to these authored cases; real model output has
not been measured (no API credit), and 100 % on a curated set is not a claim about real-world performance.

## Non-finite inputs (added 2026-09-26)

- `excursion`, `ccme_wqi` and `eqr` raise `ValueError` for NaN or infinite observed values, limits or references. Before this change a NaN counted as a pass (every comparison with NaN is false) and an infinite value made F3 NaN, so `max(0, min(100, nan))` returned 100.0 ("Excellent").
- The sandbox pipeline (`apply_ccme_wqi_to_sandbox`) never passes a non-finite value to the index: `exact_numeric_value` and `is_physically_possible` reject it, and the observation is excluded and counted in `skipped_non_finite_observations`.
- Traceability: regression tests in `tests/unit/test_nonfinite.py` (including a property test over arbitrary floats that includes NaN and infinity).

## Two-sided (range) objectives (added 2026-09-29)

- `oah.indices.water_parameter_limits.TWO_SIDED_LIMITS` maps a parameter name to a `(lower, upper)` range. A listed parameter is scored against the range instead of the single limit in `CLOSED_PARAM_MAPPING`.
- Formula (`resolve_range_limit`): each measurement is ONE CCME test. Below `lower` it is scored against `lower` as a minimum (excursion `lower/observed - 1`); above `upper` against `upper` as a maximum (excursion `observed/upper - 1`); inside `[lower, upper]` it passes (excursion 0). The `(name, value, limit, is_lower)` test shape and `ccme_wqi` are unchanged. CCME 2001 defines excursions relative to the violated objective; applying it per violated bound is this project's reading of that rule for range objectives.
- Censored values ("<", ">") are always indeterminate for a range, since one comparator bound can prove only one side. They are skipped and counted in `skipped_censored_quantities`.
- Status: the registry holds one entry, pH (6.5, 9.5), from Directive (EU) 2020/2184, Annex I Part C ("Hydrogen ion concentration >= 6,5 and <= 9,5 pH units"; see `docs/unvalidated_values_register.md` section 3a). Enabled 2026-09-29 on the project auditor's sign-off (the user, who stated they are the auditor in chat). The old single pH limit of 8.5 in `CLOSED_PARAM_MAPPING` is unsourced and no longer used for scoring; it only serves name matching.
- Traceability: `tests/unit/test_two_sided_limits.py` (unit, property and pipeline tests with an injected range).

## Limit regimes per location and dated limits (added 2026-09-29)

Decisions taken by the project auditor (the user) on 2026-09-29, after the PDF extraction in `docs/unvalidated_values_register.md` section 10.

- **Regime is decided per location** (`oah.indices.regimes`), never per parameter. `drinking` (default): Directive (EU) 2020/2184, Annex I parametric values, i.e. `CLOSED_PARAM_MAPPING`. `surface`: Directive 2013/39/EU, Annex II, AA-EQS for inland surface waters, for Locations typed SNOMED 420531007 "River" (the only water-body type seen in real Locations). Resolution order: `LOCATION_REGIME_OVERRIDES` (by Location id, empty), then `REGIME_BY_LOCATION_TYPE`, then the default. Locations typed 288520005 "City environment" keep the default, because that type says nothing about the water body. Without a `locations` argument every site uses the default. Each evaluated site reports `limit_regime`.
- **Surface limits enabled** (ug/L, dissolved concentration as reported): mercury 0.07, lead 1.2, nickel 4. Lead and nickel EQS are defined as bioavailable concentrations (footnote 13); comparing dissolved values with them is an approximation that can overstate an exceedance. Cadmium's EQS depends on hardness class (0.08-0.25 ug/L) and the sandbox has no hardness, so cadmium observations at surface sites are skipped and counted in `skipped_surface_limit_needs_hardness_observations`. Parameters without a surface EQS keep their `CLOSED_PARAM_MAPPING` value.
- **Copper corrected** from 20 ug/L to 2000 ug/L (2020/2184 Annex I Part B: "Copper 2,0 mg/l"); the old value was 100x too strict.
- **Dated lead limit** (drinking regime): 10 ug/L before 2036-01-12, 5 ug/L from that instant ("shall be met, at the latest, by 12 January 2036"). The assessment instant is the last moment of the Observation's effective time (`observation_instant`), so a period touching the change date is judged by the stricter limit; a missing or unparseable time falls back to the current time (`oah.timeutil.utc_now`).
- Traceability: `tests/unit/test_regimes.py`.

## Country-dependent surface limits, phosphate basis and oxygen saturation (added 2026-09-29)

Auditor decisions (the user, 2026-09-29): the limit regime also depends on the location's country; phosphorus is compared as phosphate (PO4) because phosphorus does not occur free in nature; dissolved oxygen is converted to percent saturation where the national classification scores it that way; water temperature is an interpretive parameter, not a scored one, where the national text says so.

- **Country of a Location** (`oah.indices.regimes.country_for_location`): explicit `LOCATION_COUNTRY_OVERRIDES` (only `Loc-Almyros` -> GR, the Greek pilot fixture whose own text names no country), else the "(..., XX)" suffix of the description (`IT`, `GR`/`EL`, `NO`), else the `partOf` parent chain (at most five levels). Otherwise unknown; nothing is guessed. Each evaluated site reports `limit_country`.
- **Only Italy is implemented** (DM 8 November 2010, n. 260, Annex 1, Tab. 4.1.2/a, LIMeco "Livello 2" = good status), and only for river (surface-regime) locations. Greece and Norway use the EU surface/default values until their instruments are read.
- **Phosphate:** LIMeco total phosphorus 100 ug/l as P becomes `0.100 x PO4_PER_P` mg/L as PO4, with `PO4_PER_P = (30.973762 + 4 x 15.999) / 30.973762` (about 3.066; standard atomic weights). This replaces the unsourced 0.10 mg/L proxy for Italian rivers. Assumption stated by the auditor: all phosphorus is compared as phosphate-equivalent.
- **Oxygen:** `|100 - % saturation| <= 20` (LIMeco level 2) replaces the 6.0 mg/L minimum for Italian rivers. `% saturation = 100 x DO / DO_sat(T)`, with `DO_sat` the fresh-water equilibrium concentration at 1 atm from Benson and Krause (1984) as in Standard Methods 4500-O G: `ln DO_sat = -139.34411 + 1.575701e5/T - 6.642308e7/T^2 + 1.243800e10/T^3 - 8.621949e11/T^4` (T in kelvin, mg/L). Checks: 14.62 mg/L at 0 C, 9.09 at 20 C, 8.26 at 25 C. Valid 0-40 C; pressure (altitude) and salinity are not corrected because the sandbox has neither, so altitude or brackish sites are approximated. The temperature comes from the Water temperature Observation of the same site and the same effective period; without one the oxygen observation is skipped and counted (`skipped_no_temperature_for_saturation_observations`). The test appears in the index as the parameter "Dissolved oxygen saturation deviation" (unit %), upper-limit shape; censored values are indeterminate. The median oxygen and median temperature of a period are combined, which approximates the median saturation.
- **Temperature:** for Italian rivers it is not scored ("Gli altri parametri, temperatura, pH, alcalinita' e conducibilita', sono utilizzati esclusivamente per una migliore interpretazione del dato biologico e non per la classificazione", DM 260/2010), counted in `skipped_interpretive_only_observations`; it is still used to derive oxygen saturation. Elsewhere the 25 C proxy stays.
- **Nitrogen:** Italian ammonium (N-NH4) and nitrate (N-NO3) LIMeco boundaries (0.06 and 1.2 mg/l as N) are applied as ions; see the nitrogen update at the end of this section (they were first recorded as pending).
- Traceability: `tests/unit/test_country_regimes.py`.
- Update 2026-09-29 (nitrogen): Italian river nitrate and ammonium now use the LIMeco level-2 boundaries converted from mg/l as N to the ion: nitrate 1.2 x 4.427 = 5.31 mg/L NO3 and ammonium 0.06 x 1.288 = 0.0773 mg/L NH4 (`NO3_PER_N`, `NH4_PER_N`), replacing the drinking-water 50 mg/L and 0.50 mg/L for those sites. Tests: `tests/unit/test_country_regimes.py`.
- Update 2026-09-29 (Greece): rivers resolved to country GR use the HWQI good-class boundaries (Water 2022, 14, 2738, Table 1): nitrate 2.656 mg/L NO3, ammonium 0.0773 mg/L NH4, nitrite 0.02628 mg/L NO2, total phosphates 0.506 mg/L PO4, dissolved oxygen minimum 6.4 mg/L; water temperature is interpretive only (not scored). Conversions use `NO3_PER_N`, `NH4_PER_N`, `NO2_PER_N`, `PO4_PER_P`. Source and choices: `docs/unvalidated_values_register.md` section 17. Tests: `tests/unit/test_country_regimes.py`.

## Audit corrections to the index pipeline (added 2026-09-29, independent re-audit)

- **Oxygen plausibility:** for countries that score oxygen as percent saturation, the raw mg/L concentration is checked for physical possibility before the deviation is derived (a negative concentration is excluded and counted, as in every other regime).
- **Every scorable observation is accounted for:** an observation counted in `scorable_observations` is either measured, censored, skipped with a named counter, or (new) counted in `skipped_invalid_quantity_observations` when it has no usable number; an observation without a subject is counted in `skipped_no_subject_observations`. `skipped_non_finite_observations` is part of the shared data-quality block.
- **Oxygen and temperature pairing:** the temperature must come from a water-profile Observation (same profile filters as the index) of the same site and the same normalised effective interval (UTC; `...Z` and `+00:00` are the same instant; a period and an instant inside it do not pair). Two different temperatures for one site and period are `ambiguous` (never resolved by input order): the oxygen observation is skipped and counted in `skipped_ambiguous_temperature_for_saturation_observations`; a temperature that exists but is not exact, not convertible to Cel, or outside 0-40 C is counted in `skipped_unusable_temperature_for_saturation_observations`; a missing one in `skipped_no_temperature_for_saturation_observations`.
- **Units:** the UCUM code `[pH]` and the lower-case litre forms (`mg/l`, `ug/l`, `ng/l`, `g/l`) are accepted alongside the forms used by the sandbox.
- **Robustness:** explicit JSON nulls in `partOf`, `type` or `description` no longer raise; country names may carry trailing punctuation or sit in parentheses; up to five ancestors are read; the description is bounded before the regular expression runs.
- **Provenance and wording:** every evaluated site lists `limit_basis` per parameter, every index output carries `interpretation_notice` (reference values, not a legal compliance determination) and the exported indicator Observation carries the same note; `objective_limits_source` names the national regimes.
- Traceability: `tests/unit/test_index_audit_fixes.py`, `tests/unit/test_output_provenance.py`.
