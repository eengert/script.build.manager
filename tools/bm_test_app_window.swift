// Read-only window census for ONE process id (CoreGraphics window list metadata only).
// Prints JSON: frontmost app pid/name, and the target's layer-0 windows (id, bounds, onscreen).
// Sends no input and captures no pixels.
import AppKit
import CoreGraphics

let args = CommandLine.arguments
guard args.count == 2, let pid = Int32(args[1]) else {
    print("{\"error\":\"usage: window <pid>\"}")
    exit(2)
}
let front = NSWorkspace.shared.frontmostApplication
let all = (CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]) ?? []
let mine = all.filter {
    ($0[kCGWindowOwnerPID as String] as? Int32) == pid && ($0[kCGWindowLayer as String] as? Int) == 0
}
let result: [String: Any] = [
    "front_pid": front?.processIdentifier ?? -1,
    "front_app": front?.localizedName ?? "unknown",
    "target_pid": pid,
    "windows": mine.map {
        [
            "id": $0[kCGWindowNumber as String] ?? -1,
            "bounds": $0[kCGWindowBounds as String] ?? [:],
            "onscreen": $0[kCGWindowIsOnscreen as String] ?? false,
        ] as [String: Any]
    },
]
let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
