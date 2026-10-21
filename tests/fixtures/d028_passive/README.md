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
