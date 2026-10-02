from scripts.verify_evidence_quotes import verify_evidence_quotes


def test_all_evidence_quotes_have_auditable_sources() -> None:
    report = verify_evidence_quotes()
    assert report["passed"], report["results"]
    assert report["verified"] == report["total"] >= 18
