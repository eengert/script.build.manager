# Test.app AF3 cache quarantine

This host tool covers the one sealed 235-file cache inventory for the disposable
portable Test.app. Independent acceptance and a native execution assignment are
required before running either command against Test.app.

1. Establish fresh stopped identity using the repository helper. Verify the
   Build Manager ZIP and installed tree, 17 original ArtifactStore hits, the
   native run card's public state, the incomplete provisioning journal and
   consumed Auto-Keep marker. Resolve the ZIP-native diagnostic gate before
   beginning a transaction. Keep other launchers and writers idle throughout
   the stopped phases.
2. From the worktree, run `python3 -B -m tools.bm_af3_cache quarantine`.
   Require `status=quarantined`. The tool checks the fixed stopped bundle,
   executable, portable directory, inventory seal and backup seal, and hashes
   each corresponding source against the original archive. It compares each
   original cache to its backup and recorded identity. It moves only those
   files using same-volume, descriptor-relative, exclusive renames. No ZIP
   member is extracted as executable content.
3. Use the existing MCP launcher for the authorized portable session. Verify
   the owned control endpoints and current dependency/PIL authority before
   activating AF3. Embedded Kodi source loading remains a separate observation.
   Follow the Item 4 run card for Estuary fallback, manual Keep, private-off
   capture, one-setting correction and second reconciliation.
4. Exit Build Manager, gracefully quit the authenticated PID and independently
   verify zero Test.app processes. Compare installed package and public state
   against the run card, classifying generated includes and new caches.
5. Run `python3 -B -m tools.bm_af3_cache restore` after the stopped checks.
   Require `status=restored` before claiming restoration. If a new cache
   occupies any original path, the tool reports the colliding relative names
   and retains both versions. Preserve them and the backup for explicit
   disposition. Never run the tool against a running app.
6. Seal the final stopped identity, package comparison, cache disposition,
   journal, public association and typed settings evidence.

The protected transaction directory is `.bm-af3-cache-quarantine-v1` under
`portable_data`, beside `addons`. The published inventory record precedes the
first rename. Recovery checks the recorded inode, content and metadata at the
original location or its numbered quarantine slot. Repeat an interrupted
quarantine, or request restoration to reverse a stopped partial quarantine.
Once the durable restoration marker is published, retry restoration only.
Unpublished record files and completed transaction records are retained.
Restore preserves the inode, permissions, ownership, flags, mtime, birth time,
extended attributes and ACL. Reads can advance access time and renames change
ctime. Neither is used as a post-rename preservation claim.

The current adapter's generated binding covers the 89-member Git-stage
projection. The release ZIP contains 88 members, omits the BM-022 fixture
package and serializes a different `addon.xml`. The in-Kodi diagnostic checks
the generated binding before acquiring native platform authority. A host-only
substitution cannot make that exact installed adapter accept the ZIP. The next
native diagnostic needs an independently reviewed, ZIP-specific adapter binding
and authorized deployment, or a reviewed diagnostic that independently obtains
the same runtime authority. Keep the current Git-stage route intact.
