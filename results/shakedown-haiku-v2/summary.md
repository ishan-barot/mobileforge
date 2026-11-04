# Benchmark results

| metric | single | multi | full |
|---|---|---|---|
| verified repair rate | 56% | 88% | 94% |
| reproduction rate | - | 100% | 100% |
| regression rate | 0% | 0% | 0% |
| failed safely (no bad patch shipped) | 0% | 0% | 0% |
| reviewer rejected a correct patch | 0% | 0% | 0% |
| median time per issue (s) | 27.9 | 63.5 | 58.8 |
| avg cost per issue (usd) | $0.008 | $0.015 | $0.013 |
| avg tool calls | 14.4 | 28.7 | 23 |
| needed more info | 0% | 0% | 0% |
| runs | 16 | 16 | 16 |

memory benefit (full minus multi): +6.3 percentage points
multi-agent vs single agent: +31.3 percentage points

## Per case (verified fixes / trials)

| case | single | multi | full |
|---|---|---|---|
| core-01 | 0/1 | 0/1 | 1/1 |
| core-02 | 0/1 | 1/1 | 1/1 |
| core-03 | 0/1 | 1/1 | 1/1 |
| core-04 | 1/1 | 1/1 | 1/1 |
| core-05 | 1/1 | 1/1 | 1/1 |
| core-06 | 1/1 | 1/1 | 1/1 |
| core-07 | 0/1 | 0/1 | 1/1 |
| core-08 | 0/1 | 1/1 | 1/1 |
| core-09 | 1/1 | 1/1 | 1/1 |
| core-10 | 1/1 | 1/1 | 1/1 |
| core-11 | 1/1 | 1/1 | 1/1 |
| core-12 | 0/1 | 1/1 | 0/1 |
| core-13 | 1/1 | 1/1 | 1/1 |
| core-14 | 1/1 | 1/1 | 1/1 |
| core-15 | 0/1 | 1/1 | 1/1 |
| core-16 | 1/1 | 1/1 | 1/1 |
