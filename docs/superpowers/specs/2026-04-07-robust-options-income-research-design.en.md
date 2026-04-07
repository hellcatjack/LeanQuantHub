# Robust Options Income Research Design

## 1. Purpose

The project goal is long-term robustness first, not raw return maximization. This design defines a disciplined research path for evaluating whether options-based income can improve returns without materially degrading robustness.

This is a research design only. It does not introduce real options trading into production.

## 2. Current Constraints

- Lean + IB have lower-level options capability.
- The StockLean application layer is still equity-only in practice.
- There is no production-ready options chain, Greeks, IV history, bid/ask, open-interest, assignment, or exercise workflow in the current app stack.
- The current account and strategy structure is small-account, multi-symbol, low per-name sizing, which is a poor fit for immediate covered-call deployment.

## 3. Recommended Direction

Do not connect real options execution to the main trading path yet.

Recommended sequence:

1. Study options-income exposure through proxy ETFs.
2. Require a robustness pass before any real options buildout.
3. Only then design real options data, selection, execution, and risk controls.

## 4. Proxy Research Layer

Initial proxy set:

- `JEPI`
- `JEPQ`
- `XYLD`
- `QYLD`
- `DIVO`

These are not substitutes for real options execution, but they are a practical way to test whether options-income style exposure improves the project’s robustness-adjusted profile.

## 5. Integration Modes

Research only two safe insertion modes first:

1. Replace part of the defensive sleeve
2. Replace part of the idle defensive allocation

Do not:

- replace the core alpha sleeve
- replace the entire defensive allocation in the first round
- promote any proxy asset directly into defaults

## 6. Decision Framework

### Approach A: Build real options now

Not recommended. Too much data, execution, UI, and risk complexity for the current system state.

### Approach B: Run proxy ETF research first

Recommended. Fastest feedback, lowest implementation risk, aligned with robustness-first development.

### Approach C: Do theory-only analysis

Not recommended. Produces weak, non-operational conclusions.

## 7. Experiment Matrix

Baseline:

- `risk_off_symbol = SGOV`
- `risk_off_symbols = SGOV,VGSH`
- `benchmark = SPY`

Proxy sleeve candidates:

- `JEPI`
- `JEPQ`
- `XYLD`
- `QYLD`
- `DIVO`

Each candidate should be tested as:

1. a partial defensive replacement
2. a partial idle-allocation replacement

## 8. Evaluation Metrics

Return efficiency:

- Total Return
- CAGR
- Sharpe
- Sortino

Robustness:

- Max Drawdown
- Ulcer Index
- Recovery time
- Stress-period drawdown
- Annual return stability

Behavioral consistency:

- Whether risk-off behavior remains interpretable
- Whether defensive logic remains coherent
- Whether style drift becomes excessive

## 9. Promotion Gate

A candidate can only advance if:

1. max drawdown worsens by no more than `1.5` percentage points
2. recovery time worsens by no more than `20%`
3. ulcer index worsens by no more than `10%`
4. return improvement is meaningful enough to justify the sleeve, defined as:
   - `CAGR` improvement of at least `0.5` percentage points, or
   - `Sharpe` improvement of at least `0.05`
5. both robustness and return conditions are met together

If robustness degrades, the path stops there.

## 10. Future Real Options Scope

If a proxy path passes the gate, the next-stage real options design must add:

- options chain access
- contract selection rules
- IV / Greeks / liquidity data
- assignment and exercise handling
- ex-dividend / event risk controls
- UI support for contract choice and audit visibility
- paper-only rollout before any live use

Until those exist, real options execution must stay out of the default trading path.
