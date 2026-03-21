export const MIN_SEND_CHUNK_DURATION_MS = 220;
export const MIN_SEND_PAYLOAD_CHARS = 48;

export function shouldSendCapturedChunk(chunk: { durationMs: number; payload: string } | null): boolean {
  if (!chunk) {
    return false;
  }
  return chunk.durationMs >= MIN_SEND_CHUNK_DURATION_MS || chunk.payload.length >= MIN_SEND_PAYLOAD_CHARS;
}
