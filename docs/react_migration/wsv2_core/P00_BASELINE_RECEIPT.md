# P00 baseline receipt — WS1

Observed 2026-10-28, independently via live GitHub REST and git ls-remote.

- Repository: Finco-Protocol/FincoProtocol (public); default branch main.
- Main HEAD: `b1a58681e41af9f1b4d52b176f0001725720b15c`.
- Tree: `d86732d7b7e187d14e01be5f0b65c663feeca8bd`.
- Isolated branch: `feat/finco-react-wsv2-core`; created from exact main. Initial merge-base = main; ahead/behind 0/0; clean worktree.
- Both intended WS1 and WS2 remote branches absent at git ls-remote. No WS2 PR or named active partner chat identified. Contract is proposed, not partner-approved. No shared financial editor files may be overwritten.
- Connector search returned only two old PRs; full live REST listing independently recovered all 17 open PRs. Full file patches, metadata, comparisons, and relevant review submissions/comments retained in external evidence, not imported into the public repository.
- Main exact-head checks below. These are baseline evidence only, never acceptance for the new branch. Branch protection REST returned 403 (integration cannot inspect rules); required protection configuration remains unverified.
- Feature gate source: FINCO_MODEL_REACT_V1, fail-closed OFF by default. Runtime process flags/deployed SHA not available through GitHub; live host read is separate evidence. No SSH, deploy, flag change or live model mutation authorized/executed.
- API contracts: same-origin canonical writers, CSRF and composite CAS preserved. Save != Run; existing D-029 runModel verifies exact historyId/snapshotId. WS1 changes only presentation and subsequent reads.
- Protected authorities remain read-only: financial_engine, finco_core, app/workbook, app/v2/router.py, project/run/history persistence, run-intent service, post_run_context. Archive has no existing endpoint; protected lifecycle authority is a path gate. True blank unsupported by current request-keyed seeded creator; no blank defaults disguised as missing inputs.
- Source pins: tests/model_mutation_security_successor.py (historical RC_UX_SUCCESSORS), tests/test_rcux_governance.py exact-current assertions; WorkspaceView, FinancialResults and generated static bundle are pinned. A new exact presentation successor requires a concrete narrow governance proposal; historical pin values/negative controls cannot be replaced or relaxed.

## Open PR inventory and overlaps

| PR | Head | Merge base | Ahead/behind | WS1 overlap |
|---|---|---|---|---|
| #328 | `e42d15ee60343b3153aa74a9821669a75e87790b` | `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` | 2/485 | none |
| #327 | `2f6f6626d0d981d8278ecde9785361ac0c3775a5` | `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` | 1/485 | none |
| #324 | `1b56bc7ec124ee4cc26001f46ee58082b2e4b5b5` | `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d` | 3/534 | none |
| #323 | `6ef433ac727e003bf9f61b8818898ed31e179505` | `eb3aaaa9d4270444842656c50f6b1a51a303c876` | 1/179 | none |
| #322 | `a00cf1f599c78163ec08c09edaca4b0bc0cd3ad6` | `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d` | 3/534 | none |
| #321 | `f4ff18cd66a784c7e7aedfbf13df94b26c7e1d60` | `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d` | 14/534 | none |
| #318 | `582bdd0a7db8c99cb4a8c496bb0af0b2b9b3dec3` | `ee5290c7ed8d567490a88d10e029e4633b84bd22` | 10/556 | none |
| #261 | `8a9d5f3f9f4488737298816d3f0750c28b7a6aa5` | `7fb47c087db09ea4dd07a46b9352ab729486a5cc` | 1/320 | none |
| #260 | `80c9d1ece3ce76208b89677c4806205a2c1f3084` | `2913c90852aad0abde7265b9ffc145125ced8ac6` | 1/941 | none |
| #184 | `26b8e4e64a01a7d44b659e8a63877b5f4286580f` | `d2597f2cb31d7b92eb1a65f05c6cb8f8432faac8` | 4/1469 | none |
| #17 | `a16ff1a0e2a2ea8a598a4ea46830ddd4848808fe` | `b0b588a9a506c815d4bb61650f7ba11f34f8ff6b` | 1/2442 | none |
| #16 | `677f144c145400806e8838388b43ec2dcfd978fb` | `1f273d91792df3c4322781c5e815c72415f14f72` | 1/1884 | none |
| #15 | `2e7f72f960daea2f0f43e6e2b5e284595b1fee7b` | `1951e26df9305edaa4cec3d0066af9fd2ec48fb9` | 1/1313 | none |
| #14 | `9448604048a38b50b60eff541247bc407b507ef8` | `1f273d91792df3c4322781c5e815c72415f14f72` | 1/1884 | none |
| #12 | `0c3df0c61f5e0f4d9e4fc57e19ffeee1cfd99d49` | `4527ceadea7a5b9a8c3e2e63eb9fb3395ef9b66e` | 1/703 | none |
| #11 | `0b773d1a58bc6ce79c334d00bd5d616966a1cf55` | `6e4c28f6aeb6949169d84aaad23842c3db4c66a7` | 1/956 | none |
| #10 | `99a62ecbcda0e5a54986c16d4579391f4c2a6946` | `6e4c28f6aeb6949169d84aaad23842c3db4c66a7` | 1/956 | none |

## Baseline exact-head checks

- mandatory-evidence: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / tests: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / aggregate: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / worker-4: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / worker-1: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / worker-0: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / worker-2: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / worker-3: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / sequential: skipped (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / plan: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- safety-and-smoke / route: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- source-safety: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- protocol-verification: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).
- dependency-audit: success (`b1a58681e41af9f1b4d52b176f0001725720b15c`).

Independent review submissions/comments of open model PRs were read; no partner WS1/WS2 review exists. Old experiment findings are not imported or resolved by this UI work. Runtime acceptance, production persistence and customer authentication remain UNVERIFIED.

## Later WS2/live checkpoint

Owner identified PR #397 after the initial P00. Reverified initial cc48391b, then current 44621e0044f48c1fec32e491e35f879664b1cd61 (29 files) on 2026-10-28. Read both partner interface documents at the latter exact ref; blobs remain ead940641f9355ffaa5e49e5c17fe0ef2e29e99a and a2a9fc5a0cfe33a82cfee76d71176b6ae3d72de8. Its backend additions include react_workspace_router plus persistence/SaveAll writers; none is imported. WS1 modifies a separate read-only overview adapter and react_rcux aggregator; no same-file overlap with those 29 partner paths. Shared integration must refresh this statement if the partner moves again.

Read-only live host: app.finco.one /v2/model-react returned 200, existing React Preview title and asset rc-sec-mutation-v1-8fa62268ae87. Staging React route returned 404; this says nothing about Legacy reference availability or live process flags. No production project, database or Run mutation occurred.
