from aistack.config import get_settings
from aistack.eval.rag_eval import acl_check, evaluate, load_golden
from aistack.retrieval.hybrid import HybridIndex


def test_golden_set_is_well_formed() -> None:
    golden = load_golden()
    assert len(golden) >= 30
    assert len({q["id"] for q in golden}) == len(golden)
    assert all(q["relevant_docs"] and q["answer_contains"] for q in golden)


def test_retrieval_quality_gate_and_no_acl_leaks() -> None:
    """Regression gate: fails if retrieval quality drops or any forbidden chunk is returned."""
    index = HybridIndex.from_gold(get_settings().gold_chunks_path)
    golden = load_golden()
    res = evaluate(index, golden)
    assert res["hybrid (RRF) + rerank"]["hit@3"] >= 0.95
    assert res["hybrid (RRF) + rerank"]["mrr"] >= 0.9
    acl = acl_check(index, golden)
    assert acl["forbidden_results_returned"] == 0
    assert acl["restricted_probes_correctly_withheld"] == acl["restricted_probes"]


def test_end_to_end_agent_eval_quality_gate() -> None:
    import asyncio

    from aistack.config import get_settings
    from aistack.eval.agent_eval import evaluate
    from aistack.eval.rag_eval import load_golden

    report = asyncio.run(evaluate(get_settings(), load_golden()))
    assert report["cites_relevant_doc"] >= 0.9
    assert report["answer_contains_all"] >= 0.8
