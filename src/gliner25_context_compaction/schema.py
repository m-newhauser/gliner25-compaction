RETENTION_LABELS = {
    "keep_full": "The complete tool output is required or unsafe to reproduce.",
    "keep_evidence": "Only exact passages from the output remain necessary.",
    "keep_call_only": "Knowing the tool and input is enough; its output is reproducible.",
    "drop": "The call is irrelevant, superseded, or safely reproducible.",
}

REASON_LABELS = {
    "current_dependency": "Later work or the current goal depends on this output.",
    "unresolved_failure": "The output contains a failure that has not been resolved.",
    "binding_constraint": "The output contains a requirement or prohibition.",
    "non_reproducible": "Repeating the tool may not recreate this information.",
    "mutation_record": "The output records a change to local or external state.",
    "superseded": "A later result replaces this information.",
    "safely_rerunnable": "The same information can be recovered by rerunning the tool.",
}

EVIDENCE_TYPES = {
    "failing_test_or_error_location": "Exact failing test name, error location, or stack-frame location.",
    "expected_value": "The exact expected value in a failed assertion.",
    "received_value": "The exact actual or received value in a failed assertion.",
    "requirement_subject": "The exact object governed by a requirement or prohibition.",
    "changed_artifact": "The exact file, resource, or object that was changed.",
    "url": "An exact URL needed to access an artifact.",
    "identifier_or_handle": "An exact generated identifier or external handle.",
}
