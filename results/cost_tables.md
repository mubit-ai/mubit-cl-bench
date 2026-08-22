# Per-task cost tables

Method: Provider list prices (litellm model_cost, matching Google/OpenAI model cards) applied to per-run usage telemetry from the submitted traces; suite cost = sum across tasks of mean per-run cost.
Validation: Reproduces published suite costs: mubit-gemini-3.7 $18.17 vs $18.16; mubit-gpt-5.4 $14.45 vs $14.49.
Note: cached_input_tokens were 0 in these runs, so cache-read rates did not affect totals.

All figures are mean per-run cost in USD (5 stateful runs per task). Suite cost = sum of the six task means.

## Mubit · Gemini 3.7 Flash — suite total $18.17

Rates: input $0.75/M · output $3.75/M · cache-read $0.07/M

| Task | Input tok/run | Cached tok/run | Output tok/run | Cost/run |
|---|---:|---:|---:|---:|
| Sales | 2,095,266 | 0 | 103,371 | $1.96 |
| BSM | 91,784 | 0 | 70,333 | $0.33 |
| DB | 2,726,738 | 0 | 24,422 | $2.14 |
| Codebase | 10,350,348 | 0 | 67,134 | $8.01 |
| Poker | 6,519,728 | 0 | 21,346 | $4.97 |
| Cohort | 666,746 | 0 | 68,130 | $0.76 |
| **Suite** | | | | **$18.17** |

## Mubit · Gemini 3.5 Flash — suite total $42.60

Rates: input $1.50/M · output $9.00/M · cache-read $0.15/M

| Task | Input tok/run | Cached tok/run | Output tok/run | Cost/run |
|---|---:|---:|---:|---:|
| Sales | 3,783,043 | 0 | 107,958 | $6.65 |
| BSM | 91,784 | 0 | 81,471 | $0.87 |
| DB | 3,841,819 | 0 | 24,653 | $5.98 |
| Codebase | 9,113,107 | 0 | 59,381 | $14.20 |
| Poker | 5,934,730 | 0 | 17,885 | $9.06 |
| Cohort | 3,338,097 | 0 | 91,044 | $5.83 |
| **Suite** | | | | **$42.60** |

## Mubit · GPT-5.4 — suite total $14.45

Rates: input $2.50/M · output $15.00/M · cache-read $0.25/M

| Task | Input tok/run | Cached tok/run | Output tok/run | Cost/run |
|---|---:|---:|---:|---:|
| Sales | 1,505,229 | 723,354 | 73,716 | $3.24 |
| BSM | 100,163 | 0 | 42,770 | $0.89 |
| DB | 978,489 | 414,054 | 15,712 | $1.75 |
| Codebase | 2,009,728 | 1,321,011 | 50,704 | $2.81 |
| Poker | 360,119 | 717 | 35,607 | $1.43 |
| Cohort | 2,197,268 | 1,195,366 | 100,905 | $4.32 |
| **Suite** | | | | **$14.45** |

## Mubit · GPT-5.4 Mini — suite total $4.94

Rates: input $0.75/M · output $4.50/M · cache-read $0.07/M

| Task | Input tok/run | Cached tok/run | Output tok/run | Cost/run |
|---|---:|---:|---:|---:|
| Sales | 1,299,320 | 757,914 | 54,282 | $0.71 |
| BSM | 100,163 | 0 | 45,771 | $0.28 |
| DB | 1,041,234 | 268,237 | 19,080 | $0.69 |
| Codebase | 4,969,375 | 3,816,755 | 73,057 | $1.48 |
| Poker | 420,042 | 38,758 | 41,462 | $0.48 |
| Cohort | 2,261,162 | 1,139,200 | 84,703 | $1.31 |
| **Suite** | | | | **$4.94** |

## Mubit · Gemini 3.1 Flash-Lite — suite total $4.08

Rates: input $0.25/M · output $1.50/M · cache-read $0.02/M

| Task | Input tok/run | Cached tok/run | Output tok/run | Cost/run |
|---|---:|---:|---:|---:|
| Sales | 1,116,273 | 0 | 54,049 | $0.36 |
| BSM | 91,784 | 0 | 82,418 | $0.15 |
| DB | 950,003 | 0 | 9,221 | $0.25 |
| Codebase | 5,629,223 | 0 | 76,959 | $1.52 |
| Poker | 6,230,582 | 0 | 18,208 | $1.58 |
| Cohort | 463,558 | 0 | 67,236 | $0.22 |
| **Suite** | | | | **$4.08** |

## Mubit · Gemini 3 Flash Preview — suite total $11.34

Rates: input $0.50/M · output $3.00/M · cache-read $0.50/M

| Task | Cost/run |
|---|---:|
| Sales | $1.23 |
| BSM | $0.21 |
| DB | $1.16 |
| Codebase | $3.62 |
| Poker | $3.91 |
| Cohort | $1.21 |
| **Suite** | **$11.34** |
