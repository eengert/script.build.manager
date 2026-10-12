# Item 8 package readiness audit — October 12, 2026

Read-only source audit at `38c9910d936c6b9d8bc2357ecbe188c12478ebcc`, with
uncommitted offline queue candidates present. No package was built, published,
installed or runtime-tested. This is not beta or release acceptance.

| Check | Evidence / verification | Result and limit |
| --- | --- | --- |
| Metadata | Parse `addon.xml`; verify script/service libraries exist | ID `script.build.manager`, version `0.1.0`, Python requirement `3.0.0`, `default.py` and `service.py`; source/license/platform and managed-scope description present. Eventual release version needs a separate decision. |
| Required icon | Read PNG signature/IHDR and SHA-256 at `resources/images/icon.png` | 512×512; `207c44a0474e7e370cf6d210c7646ce243c704a0694ef422c12bd51401628d23`, matches approved asset recorded in `.orchestrator/HANDOFF.md`. No installed-app check performed. |
| Localization | Extract `msgctxt` IDs from English PO; presentation tests | 288 unique IDs including eight new candidate strings, 33000–33007. Candidate presentation contains no raw metadata substitutions. Existing frontend suite checks its required strings; only English resources are present. No translated-layout qualification claimed. |
| UI assets and routes | `ui/controller.py`, `ui/native_dialogs.py`, `default.py`; XML parsing of `resources/settings.xml` | All six native menu routes and runtime providers exist. Current accepted native-dialog foundation supersedes the early WindowXML proposal; absence of a custom skin workspace is not itself a package blocker. |
| Create runtime | `create_workflow.runtime_create_workflow`; `docs/CREATE_RUNTIME_DEPENDENCIES.md` | Missing accepted Create lifecycle composition, trusted in-flight competition evidence and operation-bound restart proof. The standalone observer/presenter candidates are intentionally unwired. Native menu availability does not establish full workflow readiness. |
| Startup/recovery | `service.py`, `startup.py`; new namespace tests | Install/Apply resume is present; no production Create recovery composition accepted. Synthetic classification evidence does not qualify service execution. |
| Repository assumptions | `BUILD_MANAGER_PROJECT_PLAN.md`, Beta Candidate phase exit | Future distribution uses Eengert `omega/zips/` and its `scripts/build_repository.py`. That repository and its packaging implementation were not accessed. Inclusion/exclusion policy, deterministic package contents and private-file exclusion must be verified before publication; `.agent`, evidence, caches and test scratch are not distribution assets. |
| Complete workflow qualification | `.orchestrator/HANDOFF.md`, beta checklist | Earlier runtime evidence is preserved, tied to earlier candidates. Complete Estuary, restart/resume, error-state and second-run qualification tied to one final candidate remains open. This queue supplies offline preparation only. |

Next package boundary: independently review and separately commit the offline
candidates, establish the remaining Create runtime contracts, and obtain named
runtime authorization for exact-candidate qualification. Repository publication,
repository install/update testing and protected-branch integration each need their
own explicit authority. Do not manufacture a new BM-023A adapter version.
