import Foundation

/// Midea air conditioners on the local network, through `tools/midea-bridge` (msmart-ng), which
/// serves them as JSON on 127.0.0.1. The bridge keeps each unit's token and key; this client only
/// speaks the panel's vocabulary to it, so nothing about Midea's protocol lives in the app.
///
/// Besides the panel's own AC fields (`on`, `target`, `mode`, `fan`, `swing`, `sleep`, `eco`,
/// `roomTemp`) a Midea unit reports `turbo`, `display`, `breeze`, `humidity`, `outdoorTemp`,
/// `power` (watts), `totalEnergy` (kWh) and `freeze`, which the panel shows when present.
@MainActor
public final class MideaService: DeviceService {
    public let id = "midea"
    public let title = "Midea"
    public var onChange: (() -> Void)?

    private let base: URL
    private let session: URLSession
    private var known: [[String: Any]] = []
    private var poll: Task<Void, Never>?

    public init(bridge: URL = URL(string: "http://127.0.0.1:8765")!) {
        base = bridge
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 12
        session = URLSession(configuration: configuration)
        Task { [weak self] in await self?.refreshDevices() }
    }

    public var isConnected: Bool { !known.isEmpty }

    public var info: [String: Any] {
        ["connected": isConnected, "name": "Midea bridge", "url": base.absoluteString, "units": known.count]
    }

    private func refreshDevices() async {
        known = ((try? await get("devices")) as? [[String: Any]]) ?? []
        if !known.isEmpty { onChange?() }
    }

    public func devices() async throws -> [ServiceDevice] {
        await refreshDevices()
        var out: [ServiceDevice] = []
        for unit in known {
            guard let id = unit["id"] as? String else { continue }
            var device = ServiceDevice(id: id, name: unit["name"] as? String ?? "Midea AC", kind: .ac)
            if let state = (try? await get("state/\(id)")) as? [String: Any] {
                device.online = state["online"] as? Bool ?? false
                if let range = state["range"] as? [Double], range.count == 2 { device.range = (range[0], range[1]) }
            }
            device.detail = "Midea · \(unit["ip"] as? String ?? "")"
            out.append(device)
        }
        return out
    }

    public func read(_ ids: Set<String>) async throws -> [String: DeviceReading] {
        var out: [String: DeviceReading] = [:]
        for id in ids {
            guard let state = try await get("state/\(id)") as? [String: Any] else { continue }
            if state["online"] as? Bool == false {
                out[id] = DeviceReading(online: false)
                continue
            }
            var reading = DeviceReading(ac: state["ac"] as? [String: Any], features: state["features"] as? [String: Any])
            reading.online = true
            out[id] = reading
        }
        return out
    }

    public func send(kind: DeviceKind, id: String, patch: [String: Any], state: [String: Any]) async throws {
        guard kind == .ac else { return }
        // Picking a mode or a target on a unit that is off is what switches it on in the panel.
        _ = try await post("control/\(id)", body: patch)
    }

    public func watch(_ ids: Set<String>) {
        poll?.cancel()
        guard !ids.isEmpty else { return }
        // The units do not push changes (the Midea app or the remote may change them): read again every 20 s.
        poll = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 20_000_000_000)
                guard !Task.isCancelled else { return }
                self?.onChange?()
            }
        }
    }

    public func disconnect() {
        poll?.cancel()
        known = []
    }

    // MARK: - HTTP

    private func get(_ path: String) async throws -> Any? {
        let (data, _) = try await session.data(from: base.appendingPathComponent(path))
        return try JSONSerialization.jsonObject(with: data)
    }

    private func post(_ path: String, body: [String: Any]) async throws -> Any? {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        let json = try? JSONSerialization.jsonObject(with: data)
        if (response as? HTTPURLResponse)?.statusCode ?? 200 >= 400 {
            throw ServiceFailure((json as? [String: Any])?["error"] as? String ?? "The Midea bridge refused the command")
        }
        return json
    }
}
