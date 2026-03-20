from app.services.homeowner_signal_detector import HomeownerSignalDetector


def test_detector_finds_warming_hardening_and_testing_signals():
    detector = HomeownerSignalDetector()

    warming = detector.detect("Okay, that makes sense. Tell me more.")
    hardening = detector.detect("I already said I'm not interested. I need to go.")
    testing = detector.detect("How do I know you're insured?")

    assert warming.signals == ["warming"]
    assert hardening.signals == ["hardening"]
    assert testing.signals == ["testing"]
    assert testing.pending_test_question == "How do I know you're insured?"
