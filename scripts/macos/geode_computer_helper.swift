import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

struct HelperError: Error, CustomStringConvertible {
    let description: String
}

func emit(_ object: [String: Any]) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0a]))
    exit(0)
}

func fail(_ message: String, type: String = "execution") -> Never {
    emit([
        "error": message,
        "error_type": type,
        "driver": "macos_helper",
    ])
}

func screenSize() -> (width: Int, height: Int) {
    let display = CGMainDisplayID()
    return (Int(CGDisplayPixelsWide(display)), Int(CGDisplayPixelsHigh(display)))
}

func screenshotBase64(quality _: CGFloat = 0.75) throws -> String {
    let tmp = URL(fileURLWithPath: NSTemporaryDirectory())
        .appendingPathComponent("geode-computer-helper-\(UUID().uuidString).jpg")
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    proc.arguments = ["-x", "-t", "jpg", tmp.path]
    try proc.run()
    proc.waitUntilExit()
    defer { try? FileManager.default.removeItem(at: tmp) }
    guard proc.terminationStatus == 0 else {
        throw HelperError(description: "screencapture failed with exit \(proc.terminationStatus)")
    }
    let data = try Data(contentsOf: tmp)
    return data.base64EncodedString()
}

func targetToScreen(_ x: Int, _ y: Int, targetWidth: Int, targetHeight: Int) -> CGPoint {
    let size = screenSize()
    let sx = Double(x) * Double(size.width) / Double(max(targetWidth, 1))
    let sy = Double(y) * Double(size.height) / Double(max(targetHeight, 1))
    return CGPoint(x: sx, y: sy)
}

func mouseButton(_ value: String) -> CGMouseButton {
    switch value.lowercased() {
    case "right": return .right
    case "middle": return .center
    default: return .left
    }
}

func mouseEventType(button: CGMouseButton, down: Bool) -> CGEventType {
    switch button {
    case .right:
        return down ? .rightMouseDown : .rightMouseUp
    case .center:
        return down ? .otherMouseDown : .otherMouseUp
    default:
        return down ? .leftMouseDown : .leftMouseUp
    }
}

func loginSessionEventSource() -> CGEventSource {
    guard let source = CGEventSource(stateID: .combinedSessionState) else {
        fail("failed to create the login-session input event source")
    }
    return source
}

func currentCursorPosition() -> CGPoint {
    guard let event = CGEvent(source: nil) else {
        fail("failed to read the current cursor position", type: "permission")
    }
    return event.location
}

func warpCursor(to point: CGPoint) {
    let warpError = CGWarpMouseCursorPosition(point)
    guard warpError == .success else {
        fail(
            "mouse move failed with CoreGraphics error \(warpError.rawValue); " +
            "grant Accessibility permission to GEODE Computer Use Helper.app",
            type: "permission"
        )
    }
    usleep(50_000)
    let observed = currentCursorPosition()
    guard abs(observed.x - point.x) <= 2,
          abs(observed.y - point.y) <= 2
    else {
        fail(
            "mouse move postcondition failed: requested screen(\(Int(point.x)),\(Int(point.y))), " +
            "observed screen(\(Int(observed.x)),\(Int(observed.y))); grant Accessibility " +
            "permission to GEODE Computer Use Helper.app and re-run geode doctor",
            type: "permission"
        )
    }
}

func postMouse(_ type: CGEventType, at point: CGPoint, button: CGMouseButton) {
    guard let event = CGEvent(
        mouseEventSource: loginSessionEventSource(),
        mouseType: type,
        mouseCursorPosition: point,
        mouseButton: button
    ) else {
        fail("failed to create a mouse event", type: "permission")
    }
    event.post(tap: .cghidEventTap)
}

func click(at point: CGPoint, button: CGMouseButton, count: Int) {
    warpCursor(to: point)
    for _ in 0..<max(count, 1) {
        postMouse(mouseEventType(button: button, down: true), at: point, button: button)
        usleep(35_000)
        postMouse(mouseEventType(button: button, down: false), at: point, button: button)
        usleep(60_000)
    }
}

let keyCodes: [String: CGKeyCode] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "return": 36,
    "enter": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
    "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50,
    "delete": 51, "backspace": 51, "escape": 53, "esc": 53, "cmd": 55, "command": 55,
    "shift": 56, "capslock": 57, "option": 58, "alt": 58, "ctrl": 59, "control": 59,
    "right_shift": 60, "right_option": 61, "right_ctrl": 62, "fn": 63, "f17": 64,
    "volume_up": 72, "volume_down": 73, "mute": 74, "f18": 79, "f19": 80, "f20": 90,
    "f5": 96, "f6": 97, "f7": 98, "f3": 99, "f8": 100, "f9": 101, "f11": 103,
    "f13": 105, "f16": 106, "f14": 107, "f10": 109, "f12": 111, "f15": 113,
    "help": 114, "home": 115, "pageup": 116, "forwarddelete": 117, "f4": 118,
    "end": 119, "f2": 120, "pagedown": 121, "f1": 122, "left": 123, "right": 124,
    "down": 125, "up": 126,
]

func flagsFor(_ parts: [String]) -> CGEventFlags {
    var flags = CGEventFlags()
    let lowered = Set(parts.map { $0.lowercased() })
    if lowered.contains("cmd") || lowered.contains("command") { flags.insert(.maskCommand) }
    if lowered.contains("shift") { flags.insert(.maskShift) }
    if lowered.contains("option") || lowered.contains("alt") { flags.insert(.maskAlternate) }
    if lowered.contains("ctrl") || lowered.contains("control") { flags.insert(.maskControl) }
    return flags
}

func postKey(code: CGKeyCode, flags: CGEventFlags = []) {
    let source = loginSessionEventSource()
    guard let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true) else {
        fail("failed to create a key-down event", type: "permission")
    }
    down.flags = flags
    down.post(tap: .cghidEventTap)
    usleep(8_000)
    guard let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else {
        fail("failed to create a key-up event", type: "permission")
    }
    up.flags = flags
    up.post(tap: .cghidEventTap)
}

func postText(_ text: String) {
    let source = loginSessionEventSource()

    // Apple recommends combinedSessionState for events posted from the current
    // login session. Emit one Swift Character at a time so every grapheme's
    // complete UTF-16 buffer reaches keyboardSetUnicodeString together.
    // https://developer.apple.com/documentation/coregraphics/cgeventsourcestateid
    // https://developer.apple.com/documentation/coregraphics/cgevent/keyboardsetunicodestring(stringlength:unicodestring:)
    for character in text {
        let units = Array(String(character).utf16)
        units.withUnsafeBufferPointer { buffer in
            guard let base = buffer.baseAddress else { return }
            guard let down = CGEvent(
                keyboardEventSource: source,
                virtualKey: 0,
                keyDown: true
            ) else {
                fail("failed to create a Unicode key-down event", type: "permission")
            }
            down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: base)
            down.flags = []
            down.post(tap: .cghidEventTap)
            usleep(8_000)
            guard let up = CGEvent(
                keyboardEventSource: source,
                virtualKey: 0,
                keyDown: false
            ) else {
                fail("failed to create a Unicode key-up event", type: "permission")
            }
            up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: base)
            up.flags = []
            up.post(tap: .cghidEventTap)
            usleep(8_000)
        }
    }
}

let input = FileHandle.standardInput.readDataToEndOfFile()
guard !input.isEmpty else {
    fail("empty JSON request", type: "validation")
}
guard
    let root = try? JSONSerialization.jsonObject(with: input) as? [String: Any],
    let action = root["action"] as? String
else {
    fail("invalid JSON request", type: "validation")
}

let params = root["params"] as? [String: Any] ?? [:]
let targetWidth = root["target_width"] as? Int ?? 1280
let targetHeight = root["target_height"] as? Int ?? 800
let size = screenSize()

if action == "status" {
    var screenshotOK = false
    if (try? screenshotBase64()) != nil {
        screenshotOK = true
    }
    emit([
        "result": "success",
        "action": "status",
        "driver": "macos_helper",
        "ax_trusted": AXIsProcessTrusted(),
        "screenshot_ok": screenshotOK,
        "screen_width": size.width,
        "screen_height": size.height,
    ])
}

let mutatingActions: Set<String> = [
    "click", "left_click", "right_click", "middle_click", "triple_click",
    "double_click", "move", "scroll", "key", "keypress", "type", "drag",
]
if mutatingActions.contains(action), !AXIsProcessTrusted() {
    fail(
        "Accessibility permission is required for desktop input; grant it to " +
        "GEODE Computer Use Helper.app and re-run geode doctor",
        type: "permission"
    )
}

do {
    switch action {
    case "screenshot":
        break
    case "click", "left_click", "right_click", "middle_click", "triple_click":
        let x = params["x"] as? Int ?? 0
        let y = params["y"] as? Int ?? 0
        let point = targetToScreen(x, y, targetWidth: targetWidth, targetHeight: targetHeight)
        let buttonName = action == "right_click" ? "right" : action == "middle_click" ? "middle" : (params["button"] as? String ?? "left")
        let count = action == "triple_click" ? 3 : (params["click_count"] as? Int ?? 1)
        click(at: point, button: mouseButton(buttonName), count: count)
    case "double_click":
        let x = params["x"] as? Int ?? 0
        let y = params["y"] as? Int ?? 0
        click(at: targetToScreen(x, y, targetWidth: targetWidth, targetHeight: targetHeight), button: .left, count: 2)
    case "move":
        let x = params["x"] as? Int ?? 0
        let y = params["y"] as? Int ?? 0
        let point = targetToScreen(x, y, targetWidth: targetWidth, targetHeight: targetHeight)
        warpCursor(to: point)
    case "scroll":
        let amount = params["amount"] as? Int ?? 3
        let direction = (params["direction"] as? String ?? "down").lowercased()
        let dy = direction == "up" ? amount : direction == "down" ? -amount : 0
        let dx = direction == "right" ? amount : direction == "left" ? -amount : 0
        guard let event = CGEvent(
            scrollWheelEvent2Source: loginSessionEventSource(),
            units: .line,
            wheelCount: 2,
            wheel1: Int32(dy),
            wheel2: Int32(dx),
            wheel3: 0
        ) else {
            fail("failed to create a scroll event", type: "permission")
        }
        event.post(tap: .cghidEventTap)
    case "key", "keypress":
        let keys = (params["keys"] as? String ?? params["key"] as? String ?? "")
        let parts = keys.split(separator: "+").map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
        guard let last = parts.last, let code = keyCodes[last] else {
            fail("unsupported key combo: \(keys)", type: "validation")
        }
        postKey(code: code, flags: flagsFor(parts))
    case "type":
        postText(params["text"] as? String ?? "")
    case "wait":
        let ms = params["ms"] as? Int ?? 1000
        usleep(useconds_t(max(ms, 0) * 1000))
    case "cursor_position":
        let point = currentCursorPosition()
        let tx = Int(point.x * CGFloat(targetWidth) / CGFloat(max(size.width, 1)))
        let ty = Int(point.y * CGFloat(targetHeight) / CGFloat(max(size.height, 1)))
        emit([
            "result": "success",
            "action": action,
            "driver": "macos_helper",
            "cursor": [tx, ty],
            "screen_width": size.width,
            "screen_height": size.height,
            "screenshot": try screenshotBase64(),
        ])
    default:
        fail("unknown action: \(action)", type: "validation")
    }
    var response: [String: Any] = [
        "result": "success",
        "action": action,
        "driver": "macos_helper",
        "screen_width": size.width,
        "screen_height": size.height,
        "screenshot": try screenshotBase64(),
    ]
    if action == "move" {
        response["postcondition_verified"] = true
    }
    emit(response)
} catch {
    fail(String(describing: error))
}
