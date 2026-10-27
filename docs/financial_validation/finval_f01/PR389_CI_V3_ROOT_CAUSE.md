# PR #389 — CI V3 root cause / Correction C

Source: main `cf7056de4078ca66afcf52265a9bacafe35586f7` (tree `ba03a27692ca7bf47fb0170fd4fd5822f34ae4aa`) and PR #389 `035b73a1efe4d20859b34199e52d34ca891af493` (tree `e1b8ef0fe251af220807ad9ea8498384814a4688`). Synthetic merge commit `7ddd85fa9dd332ab1696ef077e6abfc2377efc3f` had the same PR tree.

Worker artifacts from failed Public Safety run [40487284039](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/40487284039): 0=`12729696168` (1 fail), 1=`12729450376` (8), 2=`12729295604` (3), 3=`12729119572` (8), 4=`12728674606` (17). 20,591 executed / 37 failed. All identical 37 test IDs passed on main run [40463817978](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/40463817978), independently verified from all ten native JUnit artifacts; no timeout or cleanup cause.

Confirmed direct false positive: `tests/v11_stage3_successor.py` runs `git grep` looking for `native_v11` over workflow files. F01 workflow checks native directory ownership with `stat` and contains that text. The scanner therefore reports `V11_STAGE3_ACTIVATION_SURFACE: ['.github/workflows/finval_f01_acceptance.yml']`. Seven V11 release/content failures arise directly, and the other thirty failures fit the subsequent `quarterly_candidate_recognition.recognized_state() == None` cascade. Attribution of every downstream node to this single cause is PENDING exact-head rerun, not asserted as proven.

F01 workflow first appears relative to main in commit `45bd6849cb4a8b93a105e3d7d313823c5bd50545`. No `financial_engine/` or `finco_core/` tracked file changed on this PR. Existing eight other CI workflows passed at previous head. The target correction changes V11 test-only recognition, not workflow bytes or financial outputs. No release authority or historical pin is changed.

**Disposition: CORRECTION REQUIRED until full corrected-head CI is green.**