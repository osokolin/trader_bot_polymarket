from __future__ import annotations

import unittest

from bot.cli.presenter import INTENT_STATUS_HELP, PROPOSAL_STATUS_HELP
from bot.domain.enums import IntentStatus, ProposalStatus


class ConsistencyAuditTest(unittest.TestCase):
    def test_operator_status_help_covers_current_workflow_statuses(self) -> None:
        expected_proposal_statuses = {
            ProposalStatus.PENDING_MANUAL_CONFIRMATION,
            ProposalStatus.APPROVED,
            ProposalStatus.POLICY_REJECTED,
            ProposalStatus.CANCELLED,
            ProposalStatus.PAUSED_BY_SAFETY,
            ProposalStatus.FILLED,
            ProposalStatus.CLOSED,
        }
        self.assertEqual(set(PROPOSAL_STATUS_HELP), expected_proposal_statuses)

        expected_intent_statuses = {
            IntentStatus.CREATED,
            IntentStatus.PREPARED,
            IntentStatus.BLOCKED,
            IntentStatus.SUPERSEDED,
            IntentStatus.SUBMISSION_ACCEPTED,
            IntentStatus.SUBMISSION_REJECTED,
            IntentStatus.SUBMISSION_DISABLED,
            IntentStatus.SIMULATED_REJECTED,
            IntentStatus.SIMULATED_SUBMITTED,
            IntentStatus.SIMULATED_PARTIALLY_FILLED,
            IntentStatus.SIMULATED_FILLED,
            IntentStatus.SIMULATED_EXPIRED,
            IntentStatus.SIMULATED_CANCELLED,
        }
        self.assertEqual(set(INTENT_STATUS_HELP), expected_intent_statuses)

    def test_status_help_strings_are_sentence_like_and_non_empty(self) -> None:
        for mapping in (PROPOSAL_STATUS_HELP, INTENT_STATUS_HELP):
            for value in mapping.values():
                self.assertTrue(value)
                self.assertTrue(value[0].isupper())
                self.assertTrue(value.endswith("."))
