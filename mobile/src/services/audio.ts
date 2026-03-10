import { Audio, InterruptionModeAndroid, InterruptionModeIOS } from "expo-av";
import * as FileSystem from "expo-file-system/legacy";

export type AudioChunk = {
  codec: "m4a" | "wav";
  contentType: string;
  payload: string;
  durationMs: number;
  createdAt: string;
};

type ChunkListener = (chunk: AudioChunk) => void;
type VadListener = (speaking: boolean) => void;
type MeterListener = (db: number) => void;

const SPEAKING_THRESHOLD_DB = -45;
const STATUS_UPDATE_MS = 80;

const RECORDING_OPTIONS: Audio.RecordingOptions = {
  ...Audio.RecordingOptionsPresets.HIGH_QUALITY,
  isMeteringEnabled: true,
};

export class AudioCaptureService {
  private recording: Audio.Recording | null = null;
  private chunkListener: ChunkListener | null = null;
  private vadListener: VadListener | null = null;
  private meterListener: MeterListener | null = null;
  private speaking = false;
  private permissionGranted = false;
  private startedAtMs = 0;
  private startPromise: Promise<void> | null = null;

  async start(): Promise<void> {
    if (this.recording) {
      return;
    }
    if (this.startPromise) {
      return this.startPromise;
    }

    this.startPromise = (async () => {
      await this.ensurePermission();
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        interruptionModeIOS: InterruptionModeIOS.DoNotMix,
        playsInSilentModeIOS: true,
        staysActiveInBackground: false,
        shouldDuckAndroid: true,
        interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
        playThroughEarpieceAndroid: false
      });

      try {
        const { recording } = await Audio.Recording.createAsync(
          RECORDING_OPTIONS,
          (status) => this.handleStatus(status),
          STATUS_UPDATE_MS
        );
        this.recording = recording;
        this.startedAtMs = Date.now();
      } catch (error) {
        this.recording = null;
        const message = error instanceof Error ? error.message : "Microphone failed to initialize";
        if (/recorder not prepared/i.test(message) || /prepare encountered an error/i.test(message)) {
          throw new Error("Microphone failed to initialize. Try pressing the mic again.");
        }
        throw error;
      }
    })();

    try {
      await this.startPromise;
    } finally {
      this.startPromise = null;
    }
  }

  async stop(): Promise<AudioChunk | null> {
    const active = this.recording;
    if (!active) {
      return null;
    }
    this.recording = null;

    let durationMs = Date.now() - this.startedAtMs;
    try {
      const status = await active.stopAndUnloadAsync();
      durationMs = status.durationMillis ?? durationMs;
    } catch {
      // If stop/unload fails, we still attempt to read URI and emit what we have.
    }

    const uri = active.getURI();
    this.updateSpeaking(false);
    await Audio.setAudioModeAsync({
      allowsRecordingIOS: false,
      interruptionModeIOS: InterruptionModeIOS.DoNotMix,
      playsInSilentModeIOS: true,
      staysActiveInBackground: false,
      shouldDuckAndroid: true,
      interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
      playThroughEarpieceAndroid: false
    });
    if (!uri) {
      return null;
    }

    const payload = await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64
    });

    const chunk: AudioChunk = {
      codec: "m4a",
      contentType: "audio/mp4",
      payload,
      durationMs: Math.max(180, durationMs),
      createdAt: new Date().toISOString()
    };
    this.chunkListener?.(chunk);
    return chunk;
  }

  onChunk(listener: ChunkListener): void {
    this.chunkListener = listener;
  }

  onVadChange(listener: VadListener): void {
    this.vadListener = listener;
  }

  onMeter(listener: MeterListener): void {
    this.meterListener = listener;
  }

  isRecording(): boolean {
    return this.recording !== null;
  }

  private async ensurePermission(): Promise<void> {
    if (this.permissionGranted) {
      return;
    }

    const current = await Audio.getPermissionsAsync();
    let granted = current.granted;
    if (!granted) {
      const requested = await Audio.requestPermissionsAsync();
      granted = requested.granted;
    }
    if (!granted) {
      throw new Error("Microphone permission is required to run live drills");
    }

    this.permissionGranted = true;
  }

  private handleStatus(status: Audio.RecordingStatus): void {
    if (!status.canRecord) {
      this.updateSpeaking(false);
      return;
    }

    const metering = status.metering ?? -160;
    this.meterListener?.(metering);
    this.updateSpeaking(metering > SPEAKING_THRESHOLD_DB);
  }

  private updateSpeaking(next: boolean): void {
    if (this.speaking === next) {
      return;
    }
    this.speaking = next;
    this.vadListener?.(next);
  }
}
