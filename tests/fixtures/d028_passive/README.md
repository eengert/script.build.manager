# Exact pinned passive descriptors

These files are unchanged public source bytes from Kodi revision `a3a448d26b`:
`https://raw.githubusercontent.com/xbmc/xbmc/a3a448d26b/addons/{id}/addon.xml`.
Their SHA-256 digests match the independently supplied actual-bundle pins for
Kodi 21.3, build `20251031-a3a448d26b`. No application was read for this task.
`test_d028_passive.py` checks each literal hash before installing the bytes in
its disposable synthetic application tree.

The real Info.plist bytes are deliberately absent. Positive offline fixtures
use synthetic plist bytes and a test-only replacement trust anchor, while a
separate negative case proves the production pin refuses those synthetic
bytes. Production retains the exact supplied real Info.plist SHA-256.
This is offline implementation evidence, not native qualification or proof of
independent GUI, resource or core API functional usability.

`xbmc.metadata.xml` (D-032, pinned `2.1.0` / ABI `1.0`) has different provenance.
Its bytes were copied read-only from the bundled `addons/xbmc.metadata/addon.xml`
of the portable Kodi 21.3 Test.app (build `20251031-a3a448d26b`). The application
was not launched or staged for the copy. The file's SHA-256
`95082198599c695a91d2aefb072f0457e9ffd5eb3f2dc1587fa58159750db1b6` matches the
descriptor digest reported by the accepted 2026-11-14 native observation in
`.qualification-evidence/bm-023a-0017-xbmc-metadata-20261114/`. It was not fetched
from upstream. Its only outgoing requirement is a mandatory `xbmc.core` 0.1.0 import.
Passive registration proves that and nothing more: the type is UNKNOWN and JSON-RPC
omits the add-on by Kodi design, and no metadata scraper functionality is proven.
