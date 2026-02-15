import asyncio
import json
import logging
import uuid
from typing import Any

from app.config import (
    GCP_PROJECT_ID,
    GCP_PUBSUB_SUBSCRIPTION_PREFIX,
    GCP_PUBSUB_TOPIC,
)

logger = logging.getLogger(__name__)

try:  # Optional dependency for GCP Pub/Sub
    from google.cloud import pubsub_v1  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pubsub_v1 = None


class CaseEventBus:
    """Simple in-memory pub/sub for broadcasting case updates."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._global_subscribers: set[asyncio.Queue] = set()

    def subscribe_all(self) -> asyncio.Queue:
        """Subscribe to all case events. Returns a queue to await events from."""
        queue: asyncio.Queue = asyncio.Queue()
        self._global_subscribers.add(queue)
        return queue

    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from all case events."""
        self._global_subscribers.discard(queue)

    def subscribe(self, case_id: str) -> asyncio.Queue:
        """Subscribe to events for a specific case."""
        queue: asyncio.Queue = asyncio.Queue()
        if case_id not in self._subscribers:
            self._subscribers[case_id] = set()
        self._subscribers[case_id].add(queue)
        return queue

    def unsubscribe(self, case_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from a specific case's events."""
        if case_id in self._subscribers:
            self._subscribers[case_id].discard(queue)
            if not self._subscribers[case_id]:
                del self._subscribers[case_id]

    async def publish(self, case_id: str, event: dict) -> None:
        """Publish an event for a case to all subscribers."""
        event["case_id"] = case_id

        for queue in self._subscribers.get(case_id, set()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full for case %s subscriber", case_id)

        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Global event queue full")


class PubSubEventBus(CaseEventBus):
    """Pub/Sub-backed event bus for multi-instance deployments."""

    def __init__(self, project_id: str, topic: str) -> None:
        super().__init__()
        self._project_id = project_id
        self._publisher = pubsub_v1.PublisherClient()  # type: ignore[call-arg]
        self._subscriber = pubsub_v1.SubscriberClient()  # type: ignore[call-arg]
        if topic.startswith("projects/"):
            self._topic_path = topic
        else:
            self._topic_path = self._publisher.topic_path(project_id, topic)
        self._subscriptions: dict[asyncio.Queue, tuple[str, Any, str | None]] = {}

    def _create_subscription(self, case_id: str | None) -> tuple[str, str | None]:
        subscription_id = f"{GCP_PUBSUB_SUBSCRIPTION_PREFIX}-{uuid.uuid4().hex}"
        sub_path = self._subscriber.subscription_path(self._project_id, subscription_id)
        filter_expr = None
        if case_id:
            filter_expr = f'attributes.case_id="{case_id}"'
        try:
            if filter_expr:
                self._subscriber.create_subscription(
                    name=sub_path,
                    topic=self._topic_path,
                    filter=filter_expr,
                )
            else:
                self._subscriber.create_subscription(
                    name=sub_path,
                    topic=self._topic_path,
                )
            fallback_filter = None
        except Exception as exc:
            logger.warning("Failed to create filtered subscription: %s", exc)
            self._subscriber.create_subscription(
                name=sub_path,
                topic=self._topic_path,
            )
            fallback_filter = case_id
        return sub_path, fallback_filter

    def _start_listener(self, queue: asyncio.Queue, sub_path: str, filter_expr: str | None) -> Any:
        loop = asyncio.get_running_loop()

        def _callback(message) -> None:
            try:
                event = json.loads(message.data.decode("utf-8"))
            except Exception:
                message.ack()
                return

            if filter_expr:
                queue_case = event.get("case_id")
                if queue_case and queue_case != filter_expr:
                    message.ack()
                    return

            loop.call_soon_threadsafe(queue.put_nowait, event)
            message.ack()

        return self._subscriber.subscribe(sub_path, callback=_callback)

    def subscribe_all(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        sub_path, filter_expr = self._create_subscription(None)
        future = self._start_listener(queue, sub_path, filter_expr)
        self._subscriptions[queue] = (sub_path, future, filter_expr)
        return queue

    def subscribe(self, case_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        sub_path, filter_expr = self._create_subscription(case_id)
        future = self._start_listener(queue, sub_path, filter_expr)
        self._subscriptions[queue] = (sub_path, future, filter_expr)
        return queue

    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        self._unsubscribe(queue)

    def unsubscribe(self, case_id: str, queue: asyncio.Queue) -> None:
        self._unsubscribe(queue)

    def _unsubscribe(self, queue: asyncio.Queue) -> None:
        sub = self._subscriptions.pop(queue, None)
        if not sub:
            return
        sub_path, future, _ = sub
        try:
            future.cancel()
        except Exception:
            logger.debug("Failed to cancel subscription future")
        try:
            self._subscriber.delete_subscription(subscription=sub_path)
        except Exception as exc:
            logger.warning("Failed to delete subscription %s: %s", sub_path, exc)

    async def publish(self, case_id: str, event: dict) -> None:
        event["case_id"] = case_id
        payload = json.dumps(event).encode("utf-8")
        try:
            self._publisher.publish(
                self._topic_path,
                payload,
                case_id=case_id,
            )
        except Exception as exc:
            logger.error("Failed to publish Pub/Sub event: %s", exc)


if GCP_PROJECT_ID and GCP_PUBSUB_TOPIC and pubsub_v1 is not None:
    logger.info("Using GCP Pub/Sub event bus for case updates")
    event_bus: CaseEventBus = PubSubEventBus(GCP_PROJECT_ID, GCP_PUBSUB_TOPIC)
else:
    if GCP_PROJECT_ID or GCP_PUBSUB_TOPIC:
        logger.warning("Pub/Sub config set but google-cloud-pubsub not installed; falling back to in-memory bus")
    event_bus = CaseEventBus()
