#!/usr/bin/env Rscript
# Extract frozen reference outputs from the public R `scorecard` German Credit vignette.
#
# Purpose
# -------
# This script is NOT part of normal Cardre test execution. It is a reference
# fixture generator. Run it manually in a pinned R environment, inspect the
# outputs, then commit the generated files as golden fixtures for calculation
# oracle tests.
#
# Reference workflow:
#   https://shichen.name/scorecard/articles/demo.html
#
# Default output directory:
#   tests/fixtures/reference_scorecard_r_german_credit
#
# Usage:
#   Rscript tools/reference_extractors/extract_scorecard_r_german_credit.R
#   Rscript tools/reference_extractors/extract_scorecard_r_german_credit.R --out-dir /tmp/cardre_ref
#   Rscript tools/reference_extractors/extract_scorecard_r_german_credit.R /tmp/cardre_ref

options(stringsAsFactors = FALSE)

required_packages <- c("scorecard", "data.table", "jsonlite")
missing_packages <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing_packages) > 0) {
  stop(
    "Missing required R packages: ", paste(missing_packages, collapse = ", "),
    "\nInstall them first, for example:\n",
    "  install.packages(c(\"scorecard\", \"data.table\", \"jsonlite\"))",
    call. = FALSE
  )
}

suppressPackageStartupMessages({
  library(scorecard)
  library(data.table)
  library(jsonlite)
})

parse_out_dir <- function(args) {
  default_out_dir <- file.path("tests", "fixtures", "reference_scorecard_r_german_credit")

  if (length(args) == 0) {
    return(default_out_dir)
  }

  if (length(args) == 1 && args[[1]] %in% c("-h", "--help")) {
    cat(
      "Usage:\n",
      "  Rscript tools/reference_extractors/extract_scorecard_r_german_credit.R\n",
      "  Rscript tools/reference_extractors/extract_scorecard_r_german_credit.R --out-dir <directory>\n",
      "  Rscript tools/reference_extractors/extract_scorecard_r_german_credit.R <directory>\n",
      sep = ""
    )
    quit(status = 0)
  }

  if (length(args) == 1) {
    return(args[[1]])
  }

  if (length(args) == 2 && args[[1]] == "--out-dir") {
    return(args[[2]])
  }

  stop("Invalid arguments. Use --help for usage.", call. = FALSE)
}

out_dir <- parse_out_dir(commandArgs(trailingOnly = TRUE))
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

write_dt <- function(x, filename) {
  data.table::fwrite(as.data.table(x), file.path(out_dir, filename), na = "")
}

write_json_pretty <- function(x, filename) {
  jsonlite::write_json(
    x,
    path = file.path(out_dir, filename),
    pretty = TRUE,
    auto_unbox = TRUE,
    null = "null",
    digits = NA
  )
}

flatten_named_tables <- function(x) {
  data.table::rbindlist(
    lapply(names(x), function(name) {
      dt <- as.data.table(x[[name]])
      dt[, cardre_reference_list_name := name]
      data.table::setcolorder(dt, c("cardre_reference_list_name", setdiff(names(dt), "cardre_reference_list_name")))
      dt
    }),
    use.names = TRUE,
    fill = TRUE
  )
}

# -----------------------------------------------------------------------------
# 1. Load and filter data exactly as in the public scorecard vignette.
# -----------------------------------------------------------------------------

data("germancredit", package = "scorecard")
germancredit <- as.data.table(germancredit)

if (!"creditability" %in% names(germancredit)) {
  stop("Expected target column `creditability` not found in scorecard::germancredit.", call. = FALSE)
}
if (nrow(germancredit) != 1000L) {
  stop("Expected scorecard::germancredit to contain 1000 rows; got ", nrow(germancredit), call. = FALSE)
}

# The vignette filters variables before splitting.
dt_f <- scorecard::var_filter(germancredit, y = "creditability")

# Add a reference row number only for exported traceability. Do not let this
# column enter WOE binning or model fitting.
dt_f_with_row_id <- copy(dt_f)
dt_f_with_row_id[, cardre_reference_row_number := .I]

# -----------------------------------------------------------------------------
# 2. Split, bin, WOE-transform, model, score, and PSI following the vignette.
# -----------------------------------------------------------------------------

split_seed <- 30L
split_ratios <- c(0.6, 0.4)

dt_list_with_row_id <- scorecard::split_df(
  dt_f_with_row_id,
  y = "creditability",
  ratios = split_ratios,
  seed = split_seed
)

dt_list <- lapply(dt_list_with_row_id, function(x) {
  y <- copy(as.data.table(x))
  y[, cardre_reference_row_number := NULL]
  y
})

breaks_adj <- list(
  age.in.years = c(26, 35, 40),
  other.debtors.or.guarantors = c("none", "co-applicant%,%guarantor")
)

bins_adj <- scorecard::woebin(
  dt_f,
  y = "creditability",
  breaks_list = breaks_adj
)

dt_woe_list <- lapply(dt_list, function(x) scorecard::woebin_ply(x, bins_adj))

m1 <- glm(
  creditability ~ .,
  family = binomial(),
  data = dt_woe_list$train
)

# step() is used in the public vignette. The returned object is already the
# selected model; keep it directly to avoid call-environment surprises.
m2 <- step(m1, direction = "both", trace = FALSE)

card <- scorecard::scorecard(bins_adj, m2)
score_list <- lapply(dt_list, function(x) scorecard::scorecard_ply(x, card))

# perf_psi returns plot objects as well as tabular payloads in some versions of
# scorecard. Keep the raw JSON export best-effort; the core test fixtures are the
# CSV/JSON tables above.
psi <- tryCatch(
  scorecard::perf_psi(
    score = score_list,
    label = lapply(dt_list, function(x) x$creditability)
  ),
  error = function(e) list(error = conditionMessage(e))
)

# -----------------------------------------------------------------------------
# 3. Export frozen reference artifacts.
# -----------------------------------------------------------------------------

write_dt(dt_f, "filtered_data.csv")

train_raw <- copy(as.data.table(dt_list_with_row_id$train))
test_raw <- copy(as.data.table(dt_list_with_row_id$test))
data.table::setcolorder(train_raw, c("cardre_reference_row_number", setdiff(names(train_raw), "cardre_reference_row_number")))
data.table::setcolorder(test_raw, c("cardre_reference_row_number", setdiff(names(test_raw), "cardre_reference_row_number")))
write_dt(train_raw, "train_raw.csv")
write_dt(test_raw, "test_raw.csv")

train_woe <- copy(as.data.table(dt_woe_list$train))
test_woe <- copy(as.data.table(dt_woe_list$test))
train_woe[, cardre_reference_row_number := train_raw$cardre_reference_row_number]
test_woe[, cardre_reference_row_number := test_raw$cardre_reference_row_number]
data.table::setcolorder(train_woe, c("cardre_reference_row_number", setdiff(names(train_woe), "cardre_reference_row_number")))
data.table::setcolorder(test_woe, c("cardre_reference_row_number", setdiff(names(test_woe), "cardre_reference_row_number")))
write_dt(train_woe, "train_woe.csv")
write_dt(test_woe, "test_woe.csv")

train_scores <- copy(as.data.table(score_list$train))
test_scores <- copy(as.data.table(score_list$test))
train_scores[, cardre_reference_row_number := train_raw$cardre_reference_row_number]
test_scores[, cardre_reference_row_number := test_raw$cardre_reference_row_number]
data.table::setcolorder(train_scores, c("cardre_reference_row_number", setdiff(names(train_scores), "cardre_reference_row_number")))
data.table::setcolorder(test_scores, c("cardre_reference_row_number", setdiff(names(test_scores), "cardre_reference_row_number")))
write_dt(train_scores, "train_scores.csv")
write_dt(test_scores, "test_scores.csv")

bins_table <- flatten_named_tables(bins_adj)
scorecard_table <- flatten_named_tables(card)
write_dt(bins_table, "bins_adj.csv")
write_dt(scorecard_table, "scorecard.csv")
write_json_pretty(bins_adj, "bins_adj.json")
write_json_pretty(card, "scorecard.json")

coef_df <- data.table::data.table(
  term = names(coef(m2)),
  coefficient = as.numeric(coef(m2))
)
write_dt(coef_df, "model_coefficients.csv")

selected_terms <- data.table::data.table(
  term = attr(stats::terms(m2), "term.labels")
)
write_dt(selected_terms, "selected_terms.csv")

write_json_pretty(psi, "psi.json")

metadata <- list(
  reference_name = "R scorecard German Credit vignette extractor",
  reference_url = "https://shichen.name/scorecard/articles/demo.html",
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"),
  r_version = R.version.string,
  platform = R.version$platform,
  packages = list(
    scorecard = as.character(utils::packageVersion("scorecard")),
    data.table = as.character(utils::packageVersion("data.table")),
    jsonlite = as.character(utils::packageVersion("jsonlite"))
  ),
  dataset = list(
    package = "scorecard",
    object = "germancredit",
    original_rows = nrow(germancredit),
    filtered_rows = nrow(dt_f),
    filtered_columns = names(dt_f),
    target = "creditability"
  ),
  split = list(
    seed = split_seed,
    ratios = split_ratios,
    train_rows = nrow(dt_list$train),
    test_rows = nrow(dt_list$test)
  ),
  manual_breaks = breaks_adj,
  model = list(
    initial_formula = paste(deparse(stats::formula(m1)), collapse = " "),
    selected_formula = paste(deparse(stats::formula(m2)), collapse = " "),
    family = "binomial",
    selection = "stats::step(direction = 'both', trace = FALSE)"
  ),
  scorecard_scaling = list(
    source = "scorecard::scorecard defaults unless changed by package version",
    expected_vignette_defaults = list(points0 = 600, odds0 = 1 / 19, pdo = 50)
  ),
  files = list(
    filtered_data = "filtered_data.csv",
    train_raw = "train_raw.csv",
    test_raw = "test_raw.csv",
    bins = c("bins_adj.csv", "bins_adj.json"),
    train_woe = "train_woe.csv",
    test_woe = "test_woe.csv",
    coefficients = "model_coefficients.csv",
    selected_terms = "selected_terms.csv",
    scorecard = c("scorecard.csv", "scorecard.json"),
    train_scores = "train_scores.csv",
    test_scores = "test_scores.csv",
    psi = "psi.json"
  )
)
write_json_pretty(metadata, "metadata.json")

# Lightweight sanity checks for deterministic fixture shape.
stopifnot(nrow(dt_list$train) == 600L)
stopifnot(nrow(dt_list$test) == 400L)
stopifnot(nrow(train_scores) == 600L)
stopifnot(nrow(test_scores) == 400L)
stopifnot(nrow(coef_df) >= 2L)
stopifnot(file.exists(file.path(out_dir, "metadata.json")))

cat("German Credit scorecard reference extraction complete.\n")
cat("Output directory: ", normalizePath(out_dir, mustWork = FALSE), "\n", sep = "")
cat("Generated files:\n")
cat(paste0("  - ", sort(basename(list.files(out_dir, full.names = TRUE))), collapse = "\n"), "\n", sep = "")
