export type AudioChunk = {
  codec: "opus";
  payload: string;
  durationMs: number;
};

export class AudioCaptureService {
  // Placeholder for next phase where real microphone streaming is wired.
  async start(): Promise<void> {
    return;
  }

  async stop(): Promise<void> {
    return;
  }

  onChunk(_: (chunk: AudioChunk) => void): void {
    return;
  }
}
