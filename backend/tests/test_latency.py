from app.utils.latency import TurnLatencyRecord


def test_turn_latency_record_to_budget_metrics_computes_exact_phase_values():
    record = TurnLatencyRecord(
        session_id="session-latency",
        turn_index=2,
        vad_end_ts=10.000,
        stt_final_ts=10.125,
        analysis_complete_ts=10.150,
        llm_first_token_ts=10.240,
        tts_task_created_ts=10.260,
        first_audio_byte_ts=10.345,
    )

    metrics = record.to_budget_metrics()

    assert metrics.stt_ms == 125
    assert metrics.analysis_ms == 25
    assert metrics.llm_first_token_ms == 90
    assert metrics.tts_first_audio_ms == 85
    assert metrics.total_turn_ms == 345
