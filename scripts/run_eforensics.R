#!/usr/bin/env Rscript
# Thin wrapper around Walter Mebane's `eforensics` package, invoked via
# subprocess from oscar/statistics/mebane_bridge.py — kept as a standalone
# script (not rpy2) so the R/JAGS dependency stays fully optional and
# decoupled from the Python process's ABI.
#
# NOTE: the formula below (`~ 1`, no covariates) is a placeholder. Mebane's
# eforensics() expects formulas for the abstention/legitimate-vote/fraud
# components specified for the actual dataset (covariates such as registered
# voters, urban/rural indicators, etc.) — that specification needs input from
# someone with election-forensics/political-science modeling judgment before
# results here should be trusted. This script only wires up the plumbing.
#
# Usage: Rscript run_eforensics.R --input mesas.csv --output result.json

suppressMessages({
  library(argparse)
  library(eforensics)
  library(jsonlite)
})

parser <- ArgumentParser()
parser$add_argument("--input", required = TRUE)
parser$add_argument("--output", required = TRUE)
args <- parser$parse_args()

data <- read.csv(args$input)

fit <- eforensics(
  formula.classification = total_votes ~ 1,
  formula.fraud = ~ 1,
  data = data,
  model = "bl",
  chains = 2,
  iter = 2000,
  burnin = 500,
  verbose = FALSE
)

result <- summary(fit)
write(toJSON(result, auto_unbox = TRUE), file = args$output)
