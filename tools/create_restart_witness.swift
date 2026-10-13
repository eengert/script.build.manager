// Offline feasibility probe only. No Kodi/Create composition or durable authority.
// Compile: xcrun swiftc -lbsm create_restart_witness.swift -o witness
import Foundation
import Darwin

struct Refusal: Error { let code: String }
func require(_ value: Bool, _ code: String) throws {
    if !value { throw Refusal(code: code) }
}
func emit(_ value: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data + Data([10]))
}
struct Incarnation: Equatable {
    let pid: Int32
    let seconds: UInt64
    let micros: UInt64
    var json: [String: Any] { ["pid": pid, "start_seconds": seconds, "start_micros": micros] }
}
func incarnation(_ pid: Int32) throws -> Incarnation {
    try require(pid > 0, "invalid_pid")
    var info = proc_bsdinfo()
    let size = Int32(MemoryLayout.size(ofValue: info))
    let count = proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size)
    try require(count == size && info.pbi_pid == UInt32(pid) && info.pbi_status != SZOMB,
                "incarnation_unavailable")
    try require(info.pbi_start_tvsec > 0 && info.pbi_start_tvusec < 1_000_000,
                "invalid_start_identity")
    return Incarnation(pid: pid, seconds: info.pbi_start_tvsec, micros: info.pbi_start_tvusec)
}

// EV_RECEIPT gives an explicit kernel registration acknowledgement. DispatchSource's
// asynchronous delivery is unnecessary here; kqueue is its supported public substrate.
func arm(_ identity: Incarnation) throws -> Int32 {
    try require(try incarnation(identity.pid) == identity, "stale_incarnation")
    let queue = kqueue()
    try require(queue >= 0, "kqueue_unavailable")
    do {
        var change = kevent(ident: UInt(identity.pid), filter: Int16(EVFILT_PROC),
            flags: UInt16(EV_ADD | EV_ENABLE | EV_CLEAR | EV_RECEIPT),
            fflags: UInt32(NOTE_EXIT) | UInt32(NOTE_EXEC), data: 0, udata: nil)
        var receipt = kevent()
        let count = kevent(queue, &change, 1, &receipt, 1, nil)
        try require(count == 1 && receipt.ident == UInt(identity.pid) &&
                    receipt.filter == Int16(EVFILT_PROC) &&
                    receipt.flags & UInt16(EV_ERROR) != 0 && receipt.data == 0,
                    "registration_refused")
        try require(try incarnation(identity.pid) == identity, "registration_race")
        var pending = kevent()
        var zero = timespec(tv_sec: 0, tv_nsec: 0)
        try require(kevent(queue, nil, 0, &pending, 1, &zero) == 0, "event_before_readiness")
        return queue
    } catch { close(queue); throw error }
}
func awaitExit(_ queue: Int32, _ identity: Incarnation, _ timeout: Int) throws {
    var event = kevent()
    var limit = timespec(tv_sec: timeout, tv_nsec: 0)
    let count = kevent(queue, nil, 0, &event, 1, &limit)
    try require(count == 1, "exit_evidence_missing")
    try require(event.ident == UInt(identity.pid) && event.filter == Int16(EVFILT_PROC)
                && event.flags & UInt16(EV_ERROR) == 0, "invalid_event")
    // An exec observation poisons this binding, even if coalesced with an exit.
    try require(event.fflags & UInt32(NOTE_EXEC) == 0, "exec_is_not_exit")
    try require(event.fflags & UInt32(NOTE_EXIT) != 0, "not_exit")
    var now = timeval()
    try require(gettimeofday(&now, nil) == 0, "exit_time_unavailable")
    emit(["kind": "exit", "old": identity.json, "kernel_note_exit": true,
          "witness_pid": getpid(), "observed_seconds": now.tv_sec,
          "observed_micros": now.tv_usec])
}

func listener(_ path: String) throws -> Int32 {
    let fd = socket(AF_UNIX, SOCK_STREAM, 0)
    try require(fd >= 0, "socket_unavailable")
    do {
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let bytes = Array(path.utf8) + [UInt8(0)]
        try require(bytes.count <= MemoryLayout.size(ofValue: address.sun_path), "socket_path_too_long")
        withUnsafeMutableBytes(of: &address.sun_path) { buffer in
            buffer.copyBytes(from: bytes)
        }
        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        try require(result == 0, "socket_bind_refused")
        try require(chmod(path, 0o600) == 0 && listen(fd, 2) == 0, "socket_listen_refused")
        return fd
    } catch { close(fd); throw error }
}
func token(_ fd: Int32) throws -> audit_token_t {
    var result = audit_token_t()
    var length = socklen_t(MemoryLayout.size(ofValue: result))
    try require(getsockopt(fd, 0, LOCAL_PEERTOKEN, &result, &length) == 0 &&
                length == MemoryLayout.size(ofValue: result), "peer_token_unavailable")
    return result
}
func peer(_ fd: Int32) throws -> [String: Any] {
    let first = try token(fd)
    let pid = audit_token_to_pid(first)
    let version = audit_token_to_pidversion(first)
    var peerPID: Int32 = 0
    var length = socklen_t(MemoryLayout.size(ofValue: peerPID))
    try require(getsockopt(fd, 0, LOCAL_PEERPID, &peerPID, &length) == 0 &&
                length == MemoryLayout.size(ofValue: peerPID) && peerPID == pid,
                "peer_pid_disagreement")
    let identity = try incarnation(pid)
    let second = try token(fd)
    try require(audit_token_to_pid(second) == pid &&
                audit_token_to_pidversion(second) == version &&
                (try incarnation(pid)) == identity, "peer_identity_race")
    // Credential snapshot authenticates the connector, not a profile, binary, or
    // current holder of a delegated descriptor. No claimed field is authoritative.
    return ["incarnation": identity.json, "audit_pidversion": version,
            "euid": audit_token_to_euid(first)]
}
func claim(_ fd: Int32) throws -> [String: Any] {
    var bytes = [UInt8]()
    while bytes.count < 4096 {
        var byte: UInt8 = 0
        try require(read(fd, &byte, 1) == 1, "claim_incomplete")
        if byte == 10 {
            let object = try JSONSerialization.jsonObject(with: Data(bytes))
            guard let result = object as? [String: Any] else { throw Refusal(code: "invalid_claim") }
            return result
        }
        bytes.append(byte)
    }
    throw Refusal(code: "claim_too_large")
}
func acceptPeer(_ server: Int32) throws -> Int32 {
    var item = pollfd(fd: server, events: Int16(POLLIN), revents: 0)
    try require(poll(&item, 1, 5000) == 1 && item.revents & Int16(POLLIN) != 0,
                "peer_timeout")
    let fd = accept(server, nil, nil)
    try require(fd >= 0, "accept_refused")
    var timeout = timeval(tv_sec: 3, tv_usec: 0)
    if setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                  socklen_t(MemoryLayout.size(ofValue: timeout))) != 0 {
        close(fd); throw Refusal(code: "socket_timeout_unavailable")
    }
    return fd
}

do {
    let args = CommandLine.arguments
    try require(args.count >= 2, "arguments")
    switch args[1] {
    case "observe":
        try require(args.count == 6, "arguments")
        guard let pid = Int32(args[2]), let sec = UInt64(args[3]),
              let usec = UInt64(args[4]), let timeout = Int(args[5]),
              (1...5).contains(timeout) else { throw Refusal(code: "arguments") }
        let identity = Incarnation(pid: pid, seconds: sec, micros: usec)
        let queue = try arm(identity)
        defer { close(queue) }
        emit(["kind": "ready", "old": identity.json, "witness_pid": getpid()])
        try awaitExit(queue, identity, timeout)
    case "identity":
        try require(args.count == 3, "arguments")
        guard let pid = Int32(args[2]) else { throw Refusal(code: "arguments") }
        emit(["kind": "identity", "incarnation": try incarnation(pid).json])
    case "peer", "witness":
        try require(args.count == 3, "arguments")
        let path = args[2]
        let server = try listener(path)
        defer { close(server); unlink(path) }
        emit(["kind": "listening", "witness_pid": getpid()])
        let fd = try acceptPeer(server)
        defer { close(fd) }
        let auth = try peer(fd)
        let asserted = try claim(fd)
        let afterClaim = try peer(fd)
        try require(NSDictionary(dictionary: auth).isEqual(to: afterClaim), "peer_changed")
        if args[1] == "peer" {
            emit(["kind": "peer", "authenticated": auth, "asserted": asserted])
        } else {
            let value = auth["incarnation"] as! [String: Any]
            let identity = Incarnation(pid: value["pid"] as! Int32,
                seconds: value["start_seconds"] as! UInt64,
                micros: value["start_micros"] as! UInt64)
            let queue = try arm(identity)
            defer { close(queue) }
            emit(["kind": "ready", "old": identity.json, "authenticated": auth,
                  "asserted": asserted, "witness_pid": getpid()])
            try awaitExit(queue, identity, 5)
        }
    default: throw Refusal(code: "arguments")
    }
} catch let error as Refusal {
    emit(["kind": "refused", "code": error.code]); exit(2)
} catch {
    emit(["kind": "refused", "code": "malformed_evidence"]); exit(2)
}
