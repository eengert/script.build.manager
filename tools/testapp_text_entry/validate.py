"""Validate the unapplied patch against the pinned installed MCP, offline only."""
from pathlib import Path
import hashlib,json,shutil,subprocess,tempfile
HERE=Path(__file__).resolve().parent
BASE=Path('/Users/eengert/.codex/mcp/build_manager_testapp')
with tempfile.TemporaryDirectory(prefix='bm-text-entry-') as tmp:
    target=Path(tmp)
    for name,digest in json.loads((HERE/'baseline.json').read_text()).items():
        assert hashlib.sha256((BASE/name).read_bytes()).hexdigest()==digest, 'MCP baseline changed: '+name
    shutil.copytree(BASE/'src',target/'src')
    (target/'package.json').write_text('{"type":"module"}\n')
    subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(HERE/'text-entry.patch')],cwd=target,check=True)
    shutil.copy(HERE/'text-entry.test.mjs',target/'text-entry.test.mjs')
    subprocess.run(['node','--test','text-entry.test.mjs'],cwd=target,check=True)
    # Existing controller/transport regressions, with only the tool-count
    # expectations updated for the fifth tool. Native execution is selftest only.
    source=Path('/Users/eengert/Documents/Kodi/tools/build-manager-testapp-mcp')
    original=(source/'tests/control.test.js').read_text()
    original=original.replace("'test_app_launch','test_app_quit']);", "'test_app_launch','test_app_quit','test_app_send_text']);")
    original=original.replace("result.tools.length,4)", "result.tools.length,5)")
    (target/'tests').mkdir()
    (target/'tests/control.test.js').write_text(original)
    (target/'dist').mkdir()
    shutil.copy(BASE/'native/testapp-helper',target/'dist/testapp-helper')
    (target/'native').mkdir()
    shutil.copy(source/'native/main.swift',target/'native/main.swift')
    (target/'node_modules').symlink_to(BASE/'node_modules',target_is_directory=True)
    subprocess.run(['node','--test','tests/control.test.js'],cwd=target,check=True)
