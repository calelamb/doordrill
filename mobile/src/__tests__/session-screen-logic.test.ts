import { shouldSendCapturedChunk } from "../services/captureLogic";

describe("SessionScreen capture logic", () => {
  it("accepts short chunks when the payload is still substantial", () => {
    expect(
      shouldSendCapturedChunk({
        durationMs: 180,
        payload: "x".repeat(80),
      })
    ).toBe(true);
  });

  it("drops truly empty capture fragments", () => {
    expect(
      shouldSendCapturedChunk({
        durationMs: 120,
        payload: "x".repeat(12),
      })
    ).toBe(false);
  });
});
