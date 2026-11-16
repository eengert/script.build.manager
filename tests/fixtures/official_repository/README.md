# Official repository descriptor fixture

`repository.xbmc.org-3.4.0.addon.xml` is a byte-for-byte copy of the public
`addon.xml` of `repository.xbmc.org` 3.4.0 bundled in the authorized Kodi Build
Manager Test.app (`Contents/Resources/Kodi/addons/repository.xbmc.org/`),
read-only. SHA-256 `1453e050fb6c9c49bf23af2ab60c3a18c886021364670b5960fa06cf862ba055`.
It contains only public Team Kodi metadata. Its repository directory declares
`checksum verify="sha256"` with a `?sha256` URL, no `compressed` attribute, a
`datadir` without `zip` or trailing slash, and `<hashes>sha256</hashes>`.
