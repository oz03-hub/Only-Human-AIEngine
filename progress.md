Schema changes (schemas.py):
- Messages are now nested inside threads (no more flat questions/messages on groups)
- WebhookIncomingMessage no longer has question_id, adds is_current_member, names are Optional
- New WebhookIncomingThread wraps question + its messages
- New WebhookIncomingPayload wraps groups_metadata + groups
- WebhookIncomingRequest now takes payload: WebhookIncomingPayload
- Added a field_validator to normalize the +00 timezone format the real app sends

message_service.py:
- store_webhook_content now syncs group active status from groups_metadata, then iterates threads (question + messages together)
- New get_active_group_questions_not_in() method for the 20% sampling rule

facilitation_service.py (created): Runs the pipeline for a list of (group_external_id, question_external_id) pairs, respects min_messages, logs results to FacilitationLog

messages.py: Webhook route now collects active threads from the payload, samples 20% of other active DB threads, and passes the combined list to the background task

Tests: New test_schemas.py (21 tests), fixed old schema format in test_api.py and broken import in conftest.py
