# Benchmark results

| metric | single | multi | full |
|---|---|---|---|
| verified repair rate | 94% | 94% | 94% |
| reproduction rate | - | 100% | 100% |
| regression rate | 0% | 0% | 0% |
| failed safely (no bad patch shipped) | 0% | 0% | 0% |
| reviewer rejected a correct patch | 0% | 0% | 0% |
| wrong patch reached human approval | 6% | 6% | 6% |
| median time per issue (s) | 19.7 | 49.0 | 51.7 |
| avg cost per issue (usd) | $0.064 | $0.146 | $0.163 |
| avg tool calls | 9.7 | 16.9 | 17.7 |
| needed more info | 0% | 0% | 0% |
| runs | 16 | 16 | 16 |

memory benefit (full minus multi): +0.0 percentage points
multi-agent vs single agent: +0.0 percentage points

## Per case (verified fixes / trials)

| case | single | multi | full |
|---|---|---|---|
| core-01 | 1/1 | 1/1 | 1/1 |
| core-02 | 1/1 | 1/1 | 1/1 |
| core-03 | 1/1 | 1/1 | 1/1 |
| core-04 | 1/1 | 1/1 | 1/1 |
| core-05 | 1/1 | 1/1 | 1/1 |
| core-06 | 1/1 | 1/1 | 1/1 |
| core-07 | 1/1 | 1/1 | 1/1 |
| core-08 | 1/1 | 1/1 | 1/1 |
| core-09 | 1/1 | 1/1 | 1/1 |
| core-10 | 1/1 | 1/1 | 1/1 |
| core-11 | 1/1 | 1/1 | 1/1 |
| core-12 | 0/1 | 0/1 | 0/1 |
| core-13 | 1/1 | 1/1 | 1/1 |
| core-14 | 1/1 | 1/1 | 1/1 |
| core-15 | 1/1 | 1/1 | 1/1 |
| core-16 | 1/1 | 1/1 | 1/1 |
