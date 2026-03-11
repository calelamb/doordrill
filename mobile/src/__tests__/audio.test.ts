jest.mock("expo-av", () => {
  const InterruptionModeIOS = { DoNotMix: 0 };
  const InterruptionModeAndroid = { DuckOthers: 2 };
  const IOSOutputFormat = { LINEARPCM: "lpcm" };
  const IOSAudioQuality = { MAX: 127 };
  const AndroidOutputFormat = { DEFAULT: 0 };
  const AndroidAudioEncoder = { DEFAULT: 0 };

  class MockRecording {
    static createAsync = jest.fn().mockImplementation(() =>
      Promise.resolve({
        recording: new MockRecording(),
      })
    );
    stopAndUnloadAsync = jest.fn().mockResolvedValue({ durationMillis: 1500 });
    getURI = jest.fn().mockReturnValue("file:///tmp/test.wav");
  }

  return {
    Audio: {
      Recording: MockRecording,
      RecordingOptionsPresets: { HIGH_QUALITY: {} },
      IOSOutputFormat,
      IOSAudioQuality,
      AndroidOutputFormat,
      AndroidAudioEncoder,
      getPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
      requestPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
      setAudioModeAsync: jest.fn().mockResolvedValue(undefined),
    },
    InterruptionModeIOS,
    InterruptionModeAndroid,
  };
});

jest.mock("expo-file-system/legacy", () => ({
  readAsStringAsync: jest.fn().mockResolvedValue("base64encodedaudio=="),
  EncodingType: { Base64: "base64" },
}));

import { Audio } from "expo-av";

import { AudioCaptureService } from "../services/audio";
import type { AudioChunk } from "../services/audio";

const VAD_ATTACK_FRAMES = 2;
const VAD_RELEASE_FRAMES = 5;
const SPEAKING_THRESHOLD_DB = -45;

function makeSvc() {
  return new AudioCaptureService();
}

async function getCreatedRecording(index = 0) {
  const result = (Audio.Recording as any).createAsync.mock.results[index];
  if (!result) {
    throw new Error(`Missing mocked recording at index ${index}`);
  }
  const created = await result.value;
  return created.recording;
}

function fireMetering(svc: AudioCaptureService, db: number, frames: number) {
  for (let i = 0; i < frames; i++) {
    (svc as any).handleStatus({ canRecord: true, metering: db });
  }
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("AudioCaptureService — codec", () => {
  it("stop() emits codec=wav and contentType=audio/wav", async () => {
    const svc = makeSvc();
    await svc.start();

    let received: AudioChunk | null = null;
    svc.onChunk((chunk) => {
      received = chunk;
    });

    await svc.stop();

    expect(received).not.toBeNull();
    expect(received!.codec).toBe("wav");
    expect(received!.contentType).toBe("audio/wav");
  });

  it("stop() emits sampleRate=16000 and channels=1", async () => {
    const svc = makeSvc();
    await svc.start();
    let received: AudioChunk | null = null;
    svc.onChunk((chunk) => {
      received = chunk;
    });
    await svc.stop();
    expect(received!.sampleRate).toBe(16000);
    expect(received!.channels).toBe(1);
  });

  it("stop() enforces minimum durationMs of 180", async () => {
    const svc = makeSvc();
    await svc.start();
    const recording = await getCreatedRecording();
    jest
      .spyOn(recording, "stopAndUnloadAsync")
      .mockResolvedValueOnce({ durationMillis: 10 });

    let received: AudioChunk | null = null;
    svc.onChunk((chunk) => {
      received = chunk;
    });

    await svc.stop();

    expect(received!.durationMs).toBeGreaterThanOrEqual(180);
  });
});

describe("AudioCaptureService — VAD hysteresis", () => {
  it("single frame above threshold does NOT trigger speaking=true", () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, 1);

    expect(changes).toHaveLength(0);
  });

  it(`requires ${VAD_ATTACK_FRAMES} consecutive frames above threshold to start speaking`, () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, VAD_ATTACK_FRAMES - 1);
    expect(changes).toHaveLength(0);

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, 1);
    expect(changes).toEqual([true]);
  });

  it("noise spike (1 frame above, 1 below) does not trigger speaking", () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 10, 1);
    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, 1);

    expect(changes).toHaveLength(0);
  });

  it("single frame below threshold does NOT trigger speaking=false once speaking", () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, VAD_ATTACK_FRAMES);
    expect(changes).toEqual([true]);
    changes.length = 0;

    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, 1);
    expect(changes).toHaveLength(0);
  });

  it(`requires ${VAD_RELEASE_FRAMES} consecutive frames below threshold to stop speaking`, () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, VAD_ATTACK_FRAMES);
    expect(changes).toEqual([true]);
    changes.length = 0;

    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, VAD_RELEASE_FRAMES - 1);
    expect(changes).toHaveLength(0);

    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, 1);
    expect(changes).toEqual([false]);
  });

  it("interleaved noise during silence resets the release counter", () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, VAD_ATTACK_FRAMES);
    changes.length = 0;

    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, VAD_RELEASE_FRAMES - 2);
    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, 1);
    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, VAD_RELEASE_FRAMES - 2);

    expect(changes).toHaveLength(0);

    fireMetering(svc, SPEAKING_THRESHOLD_DB - 10, 2);
    expect(changes).toEqual([false]);
  });

  it("frame counters reset when canRecord is false", () => {
    const svc = makeSvc();
    const changes: boolean[] = [];
    svc.onVadChange((v) => changes.push(v));

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, VAD_ATTACK_FRAMES - 1);
    (svc as any).handleStatus({ canRecord: false, metering: 0 });

    fireMetering(svc, SPEAKING_THRESHOLD_DB + 5, VAD_ATTACK_FRAMES - 1);
    expect(changes).toHaveLength(0);
  });
});

describe("AudioCaptureService — audio mode switching", () => {
  it("start() calls setAudioModeAsync with allowsRecordingIOS=true", async () => {
    const svc = makeSvc();
    await svc.start();
    expect(Audio.setAudioModeAsync).toHaveBeenCalledWith(
      expect.objectContaining({ allowsRecordingIOS: true })
    );
  });

  it("stop() calls setAudioModeAsync with allowsRecordingIOS=false", async () => {
    const svc = makeSvc();
    await svc.start();
    jest.clearAllMocks();
    await svc.stop();
    expect(Audio.setAudioModeAsync).toHaveBeenCalledWith(
      expect.objectContaining({ allowsRecordingIOS: false })
    );
  });
});
