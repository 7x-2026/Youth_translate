import Foundation
import CoreAudio
import AVFoundation
import Darwin

// Audio-only Core Audio tap. No screen APIs, output devices, or playback streams.
// stdout: one JSON readiness line, then 16 kHz mono signed little-endian PCM16.
enum CaptureError: Error { case status(String, OSStatus), format }
func check(_ status: OSStatus, _ operation: String) throws {
    if status != noErr { throw CaptureError.status(operation, status) }
}

func deviceString(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) throws -> String {
    var address = AudioObjectPropertyAddress(mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var value: CFString = "" as CFString
    var size = UInt32(MemoryLayout<CFString>.size)
    try withUnsafeMutablePointer(to: &value) { pointer in
        try check(AudioObjectGetPropertyData(device, &address, 0, nil, &size, pointer), "device_name")
    }
    return value as String
}

func outputDevices() throws -> [[String: Any]] {
    var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice,
        mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var defaultDevice: AudioObjectID = 0
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &defaultDevice), "default_output")
    address.mSelector = kAudioHardwarePropertyDevices
    try check(AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size), "device_list_size")
    var devices = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &devices), "device_list")
    var outputs: [[String: Any]] = []
    for device in devices {
        var streams = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreams,
            mScope: kAudioDevicePropertyScopeOutput, mElement: kAudioObjectPropertyElementMain)
        var bytes: UInt32 = 0
        if AudioObjectGetPropertyDataSize(device, &streams, 0, nil, &bytes) != noErr || bytes == 0 { continue }
        outputs.append(["id": try deviceString(device, kAudioDevicePropertyDeviceUID),
            "label": try deviceString(device, kAudioObjectPropertyName), "isDefault": device == defaultDevice])
    }
    return outputs.sorted { ($0["isDefault"] as? Bool ?? false) && !($1["isDefault"] as? Bool ?? false) }
}

func writeJSON(_ value: Any) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

@available(macOS 14.2, *)
final class SystemAudio {
    var tap: AudioObjectID = 0
    var aggregate: AudioObjectID = 0
    var io: AudioDeviceIOProcID?
    let queue = DispatchQueue(label: "classroom.system-audio")
    var signals: [DispatchSourceSignal] = []

    func start(deviceID: String?) throws {
        let devices = try outputDevices()
        guard let device = deviceID == nil ? devices.first : devices.first(where: { $0["id"] as? String == deviceID }),
              let uid = device["id"] as? String, let label = device["label"] as? String else { throw CaptureError.format }
        let description = CATapDescription(excludingProcesses: [], deviceUID: uid, stream: 0)
        description.name = "课堂同传内部音频"
        description.isPrivate = true
        description.muteBehavior = .unmuted // Preserve the meeting/music output.
        try check(AudioHardwareCreateProcessTap(description, &tap), "create_tap")

        var address = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyFormat,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var asbd = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        try check(AudioObjectGetPropertyData(tap, &address, 0, nil, &size, &asbd), "tap_format")
        guard let inputFormat = AVAudioFormat(streamDescription: &asbd),
              let outputFormat = AVAudioFormat(commonFormat: .pcmFormatInt16,
                  sampleRate: 16000, channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
            throw CaptureError.format
        }
        converter.sampleRateConverterQuality = AVAudioQuality.high.rawValue
        let properties: [String: Any] = [
            kAudioAggregateDeviceNameKey: "课堂同传内部音频",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceTapListKey: [[
                kAudioSubTapUIDKey: description.uuid.uuidString,
                kAudioSubTapDriftCompensationKey: true,
            ]],
        ]
        try check(AudioHardwareCreateAggregateDevice(properties as CFDictionary, &aggregate), "create_aggregate")
        try check(AudioDeviceCreateIOProcIDWithBlock(&io, aggregate, queue) { _, data, _, _, _ in
            autoreleasepool {
                guard let input = AVAudioPCMBuffer(pcmFormat: inputFormat,
                    bufferListNoCopy: data, deallocator: nil) else { return }
                let frames = data.pointee.mBuffers.mDataByteSize / asbd.mBytesPerFrame
                if frames == 0 { return }
                input.frameLength = frames
                let capacity = AVAudioFrameCount(ceil(Double(frames) * 16000 / inputFormat.sampleRate)) + 64
                guard let output = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else { return }
                var supplied = false
                var error: NSError?
                let status = converter.convert(to: output, error: &error) { _, state in
                    if supplied { state.pointee = .noDataNow; return nil }
                    supplied = true; state.pointee = .haveData; return input
                }
                if status == .error { exit(3) }
                if let samples = output.int16ChannelData, output.frameLength > 0 {
                    let bytes = Int(output.frameLength) * MemoryLayout<Int16>.size
                    // Only a private input tap is serviced here; no meeting playback callback is touched.
                    FileHandle.standardOutput.write(Data(bytes: samples[0], count: bytes))
                }
            }
        }, "create_reader")
        // Serialize the header and first audio callback on the same queue.
        try queue.sync {
            try writeJSON(["type": "ready", "label": label, "sampleRate": 16000])
        }
        try check(AudioDeviceStart(aggregate, io), "start_reader")
        for number in [SIGTERM, SIGINT] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { self.stop(); exit(0) }
            source.resume(); signals.append(source)
        }
    }
    func stop() {
        if aggregate != 0, let io { AudioDeviceStop(aggregate, io); AudioDeviceDestroyIOProcID(aggregate, io) }
        io = nil
        if aggregate != 0 { AudioHardwareDestroyAggregateDevice(aggregate); aggregate = 0 }
        if tap != 0 { AudioHardwareDestroyProcessTap(tap); tap = 0 }
    }
}

if #available(macOS 14.2, *) {
    let capture = SystemAudio()
    do {
        if CommandLine.arguments.contains("--list") { try writeJSON(outputDevices()); exit(0) }
        let deviceIndex = CommandLine.arguments.firstIndex(of: "--device")
        let deviceID = deviceIndex.flatMap { $0 + 1 < CommandLine.arguments.count ? CommandLine.arguments[$0 + 1] : nil }
        try capture.start(deviceID: deviceID); dispatchMain()
    }
    catch {
        capture.stop()
        FileHandle.standardError.write(Data("系统音频启动失败：\(error)。请允许系统音频录制权限。\n".utf8))
        exit(2)
    }
} else {
    FileHandle.standardError.write(Data("内部音频采集需要 macOS 14.2 或更新版本。\n".utf8))
    exit(2)
}
