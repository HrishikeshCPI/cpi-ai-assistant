"""
Automated agent regression test harness.

Run from cpi-ai-assistant project root:
    python test_agent_regression.py

This calls the REAL chat agent (same create_chat/chat_turn path the
Streamlit UI uses) with a fixed set of questions whose correct answers
are already independently verified against the graph. It checks whether
key facts appear in the response, and flags anything unexpected.

This is NOT a substitute for occasionally re-reading full responses
yourself - substring checks can pass even if the surrounding explanation
is wrong or misleading. Treat a FAIL as "definitely broken, investigate
now" and a PASS as "the key fact is present, worth a periodic manual
skim anyway."

Add new cases here every time you discover and fix a new bug, so this
suite grows every time trust is earned back.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.agent.chat import create_chat, chat_turn

# Each case: question, list of substrings that MUST appear (case-insensitive),
# list of substrings that must NOT appear (catches known wrong-answer patterns)
TEST_CASES = [
    {
        "question": "Which iFlows call Subflow_1_Northwind_Customer_Data as a subflow?",
        "must_contain": ["NorthWind_Customer_OData_Git"],
        "must_not_contain": ["no iflows currently call", "no iflows call"],
    },
    {
        "question": "How many iFlows have error-handling subprocesses?",
        "must_contain": ["8"],
        "must_not_contain": ["no iflows found", "0 iflows"],
    },
    {
        "question": "Which mappings use complex transformation logic, not direct copies?",
        "must_contain": ["businesspartner.replicate", "contract.replicate", "salesorder.replicate"],
        "must_not_contain": ["PrePostProcessing.groovy"],
    },
    {
        "question": "How many Multicast steps exist across the whole landscape?",
        "must_contain": ["8"],
        "must_not_contain": ["no multicast steps"],
    },
    {
        "question": "Which iFlow has the deepest combined subprocess/error-handling nesting?",
        "must_contain": ["Data_Extractor_copy"],
        "must_not_contain": [],
    },
    {
        "question": "Which iFlows combine complex mapping logic with zero error handling?",
        "must_contain": ["businesspartner.replicate", "contract.replicate", "salesorder.replicate"],
        "must_not_contain": ["businesspartnerrelationshi", "PrePostProcessing.groovy"],
    },
    {
        "question": "Trace the full call chain from the main NorthWind flow to its deepest subflow.",
        "must_contain": ["Subflow_1_Northwind_Customer_Data", "Subflow_2_Northwind_Customer_Data"],
        "must_not_contain": [],
    },
    {
        "question": "Is any iFlow both a caller and a callee in the subflow chain?",
        "must_contain": ["Subflow_1_Northwind_Customer_Data"],
        "must_not_contain": ["no iflow", "none"],
    },
    {
        "question": "If I change MM_ConvertNorthWindStructuer.mmap, what breaks?",
        "must_contain": ["NorthWind_Customer_OData_Git"],
        "must_not_contain": [],
    },
    {
        "question": "Which systems are shared across multiple iFlows, and how many iFlows use S4?",
        "must_contain": ["S4", "11"],
        "must_not_contain": [],
    },
]

REQUEST_DELAY_SECONDS = 15


def run_suite():
    passed = 0
    failed = 0
    for i, case in enumerate(TEST_CASES, 1):
        chat = create_chat()
        response_text = chat_turn(chat, case["question"])
        lower_response = response_text.lower()

        missing = [s for s in case["must_contain"] if s.lower() not in lower_response]
        forbidden_found = [s for s in case["must_not_contain"] if s.lower() in lower_response]

        ok = not missing and not forbidden_found

        print(f"\n{'='*70}")
        print(f"Case {i}: {case['question']}")
        print(f"{'='*70}")
        if ok:
            print("[PASS]")
            passed += 1
        else:
            print("[FAIL]")
            if missing:
                print(f"  Missing expected content: {missing}")
            if forbidden_found:
                print(f"  Contains known-wrong content: {forbidden_found}")
            print(f"  Full response:\n{response_text}")
            failed += 1

        if i < len(TEST_CASES):
            print(f"Waiting {REQUEST_DELAY_SECONDS} seconds before the next chat request...")
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\n{'='*70}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print(f"{'='*70}")
    return failed == 0


if __name__ == "__main__":
    success = run_suite()
    sys.exit(0 if success else 1)
