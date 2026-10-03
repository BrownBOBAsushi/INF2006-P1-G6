"""Small SQS task transport; message bodies contain no personal data."""
from __future__ import annotations

import json
import uuid


class SqsTaskQueue:
    def __init__(self, queue_url: str, kind: str, *, client):
        if not queue_url.startswith("https://") or kind not in {"EXTRACTION", "EMBEDDING"}:
            raise ValueError("HTTPS queue URL and supported task kind are required")
        self.queue_url = queue_url
        self.kind = kind
        self.client = client

    def publish(self, task_id: uuid.UUID) -> str:
        response = self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"task_id": str(task_id), "kind": self.kind}, separators=(",", ":")),
        )
        message_id = response.get("MessageId")
        if not message_id:
            raise RuntimeError("SQS did not confirm task publication")
        return message_id

    def receive(self, *, wait_seconds: int = 20, visibility_timeout: int = 900) -> list[dict]:
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=visibility_timeout,
        )
        return response.get("Messages", [])

    def delete(self, receipt_handle: str) -> None:
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)

    def change_visibility(self, receipt_handle: str, seconds: int) -> None:
        self.client.change_message_visibility(
            QueueUrl=self.queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=max(0, min(900, seconds))
        )
