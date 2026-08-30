# Resolution-check subagent batches

Split of the Step 1 audit in `../resolution_check_handoff.md` into 6
independent subagents, grouped by source subtree so each agent reuses the
same headers, conventions, and nearby call chains.

## Batches

| Agent | Prompt | Claims CSV | Claim rows | Unique sites | Source scope (under /home/chukyu) |
|---|---|---|---:|---:|---|
| 1 | agent1.md | agent1_claims.csv | 464 | 417 | t-dyn/src: dyn234d, dyn401d, dyn501d, dyn600, dyn730 |
| 2 | agent2.md | agent2_claims.csv | 441 | 383 | t-dyn/src: libDynRe, libDynDspCom, dyn232d, dyn402d, dyn430d, dyn562, dyn563, dyn710, dyn810d, dyn812d |
| 3 | agent3.md | agent3_claims.csv | 410 | 392 | t-dyn/src (all remaining ~40 small dirs) + t-dyn/tool |
| 4 | agent4.md | agent4_claims.csv | 449 | 437 | t-dif (src+tool), t-tmm (src+tool) |
| 5 | agent5.md | agent5_claims.csv | 359 | 330 | t-dxi (src+tool), t-cha (src+tool) |
| 6 | agent6.md | agent6_claims.csv | 396 | 393 | t-sim, t-svm, t-rep (src+tool) |
| **Total** | | | **2519** | **2352** | all of step1_sites.csv |

## Manifest / partition proof

- Source of truth: `../analysis/step1_results/step1_sites.csv` (2519 rows,
  2352 unique (file, line) sites — matches the handoff population:
  2312 c-viz sites + 1121 legacy sites − 1081 shared = 2352).
- Partition rule: every row assigned to exactly one batch by its
  absolute_file's third path component (t-dyn) or second component
  (other packages); verified programmatically — **0 unassigned rows,
  0 overlapping unique sites between batches**.
- Each `agentN_claims.csv` is a verbatim subset of step1_sites.csv (same
  columns), so claim row identity is preserved for reconciliation.
- After the subagents finish, the coordinator must re-verify that every
  batch summary's "sites audited" count plus "unfinished items" equals the
  batch's site count, and aggregate verdicts/cause tags from each agent's
  `## Results` section into `../analysis/resolution_check_report.md`,
  `resolution_check_claims.csv`, and `resolution_check_summary.json`.

## How to launch

Start each agent with its own prompt file, e.g. in a fresh session:
`See subagents/agent1.md and complete the audit it describes.`
Each agent appends its results below the `## Results` heading in its own
prompt file. Agents must run in separate sessions (they share no state).
