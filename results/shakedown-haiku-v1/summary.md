# Benchmark results

| metric | single | multi | full |
|---|---|---|---|
| verified repair rate | 44% | 19% | 19% |
| reproduction rate | - | 100% | 100% |
| regression rate | 0% | 0% | 0% |
| failed safely (no bad patch shipped) | 0% | 6% | 6% |
| median time per issue (s) | 27.9 | 84.9 | 96.8 |
| avg cost per issue (usd) | $0.009 | $0.017 | $0.020 |
| avg tool calls | 15 | 29.4 | 34.1 |
| needed more info | 0% | 0% | 0% |
| runs | 16 | 16 | 16 |

memory benefit (full minus multi): +0.0 percentage points
multi-agent vs single agent: -25.0 percentage points

## Per case (verified fixes / trials)

| case | single | multi | full |
|---|---|---|---|
| core-01 | 0/1 | 0/1 | 1/1 |
| core-02 | 1/1 | 0/1 | 0/1 |
| core-03 | 1/1 | 0/1 | 1/1 |
| core-04 | 0/1 | 0/1 | 0/1 |
| core-05 | 1/1 | 1/1 | 0/1 |
| core-06 | 1/1 | 0/1 | 0/1 |
| core-07 | 0/1 | 0/1 | 0/1 |
| core-08 | 1/1 | 0/1 | 0/1 |
| core-09 | 0/1 | 0/1 | 0/1 |
| core-10 | 0/1 | 0/1 | 1/1 |
| core-11 | 0/1 | 0/1 | 0/1 |
| core-12 | 0/1 | 0/1 | 0/1 |
| core-13 | 1/1 | 1/1 | 0/1 |
| core-14 | 0/1 | 0/1 | 0/1 |
| core-15 | 0/1 | 0/1 | 0/1 |
| core-16 | 1/1 | 1/1 | 0/1 |
