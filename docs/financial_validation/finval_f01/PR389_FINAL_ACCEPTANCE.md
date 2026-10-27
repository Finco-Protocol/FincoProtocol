# PR #389 — Correction C final acceptance tracker

- Current baseline (before Correction C): PR HEAD `035b73a1efe4d20859b34199e52d34ca891af493`; main `cf7056de4078ca66afcf52265a9bacafe35586f7`; failed Public Safety run `40487284039`, 37 pytest failures.
- Independently inspected all five worker native JUnit XMLs. All exact 37 test names pass on main run `40463817978`, and fail on PR baseline.
- Correction C proposed: V11 release-detector exception only for exact F01 acceptance workflow bytes; preserve all financial output contracts and previously GREEN F01 native/browser CI.
- **Do not record acceptance until corrective commit has exact-head five-worker Public Safety, all required workflows, F01 browser/native/security, negative controls and no unexpected skips all GREEN.**
- PR stays DRAFT. No merge, deploy, release activation, production change or self-approval.
Correction C code correction HEAD (before documentation sync): `21e60530ea4447e1e7cc4599bdd3e05a5e76b3d6`; new V11 guard tests blob `f33d1a54a4aa59fdc0b29ffc6b1046ddbe18b66c`. Hosted full CI has been triggered and remains pending. All GREEN is not yet asserted.
