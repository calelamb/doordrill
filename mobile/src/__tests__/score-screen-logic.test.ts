import { heroStateFor, shouldPollScorecard, shouldRetryScorecardLoadError, techniqueBuckets } from "../screens/ScoreScreen";

describe("ScoreScreen logic", () => {
  it("keeps polling while grading is processing and no scorecard exists", () => {
    expect(
      shouldPollScorecard({
        session: {
          id: "session-1",
          assignment_id: "assignment-1",
          rep_id: "rep-1",
          scenario_id: "scenario-1",
          started_at: new Date().toISOString(),
          ended_at: null,
          status: "processing",
        },
        scorecard: null,
        grading_meta: {
          status: "processing",
          provisional: false,
        },
        transcript: [],
      })
    ).toBe(true);
  });

  it("treats an initial scorecard timeout as processing when grading is still pending", () => {
    expect(
      shouldRetryScorecardLoadError(
        "Request timed out",
        {
          session: {
            id: "session-1",
            assignment_id: "assignment-1",
            rep_id: "rep-1",
            scenario_id: "scenario-1",
            started_at: new Date().toISOString(),
            ended_at: null,
            status: "processing",
          },
          scorecard: null,
          grading_meta: {
            status: "processing",
            provisional: false,
          },
          transcript: [],
        },
        0
      )
    ).toBe(true);
  });

  it("derives the correct hero state for provisional and no-rep-speech scorecards", () => {
    expect(
      heroStateFor(
        {
          id: "scorecard-1",
          overall_score: 7.1,
          scorecard_schema_version: "v2",
          category_scores: {},
          improvement_targets: [],
          highlights: [],
          ai_summary: "",
          evidence_turn_ids: [],
          weakness_tags: [],
          technique_checks: [],
        },
        {
          status: "provisional",
          provisional: true,
        }
      )
    ).toBe("provisional");

    expect(
      heroStateFor(
        {
          id: "scorecard-2",
          overall_score: 0,
          scorecard_schema_version: "v2",
          category_scores: {},
          improvement_targets: [],
          highlights: [],
          ai_summary: "",
          evidence_turn_ids: [],
          weakness_tags: ["no_rep_speech"],
          technique_checks: [],
        },
        {
          status: "no_rep_speech",
          provisional: false,
        }
      )
    ).toBe("no_rep_speech");
  });

  it("separates landed and missed technique checks for the summary cards", () => {
    const buckets = techniqueBuckets([
      {
        id: "opening_neighbor_route_frame",
        label: "Neighbor / route framing",
        category: "opening",
        status: "hit",
        kind: "reward",
        evidence_turn_ids: ["turn-1"],
      },
      {
        id: "opening_low_pressure_quote_pivot",
        label: "Low-pressure quote pivot",
        category: "opening",
        status: "partial",
        kind: "reward",
        evidence_turn_ids: ["turn-2"],
      },
      {
        id: "penalty_no_reclose_after_address",
        label: "No re-close after address",
        category: "closing_technique",
        status: "hit",
        kind: "cap",
        evidence_turn_ids: ["turn-3"],
      },
    ]);

    expect(buckets.landed.map((item) => item.id)).toEqual([
      "opening_neighbor_route_frame",
      "opening_low_pressure_quote_pivot",
    ]);
    expect(buckets.missed.map((item) => item.id)).toEqual(["penalty_no_reclose_after_address"]);
  });
});
