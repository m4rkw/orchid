from orchid.bus import EventBus


def test_publish_seq_and_routing():
    bus = EventBus()
    sub = bus.subscribe({"onboarding"})
    only_sidebar = bus.subscribe()

    e1 = bus.publish("sidebar", "project_added", {"a": 1})
    e2 = bus.publish("onboarding", "message", {"b": 2})
    e3 = bus.publish("onboarding", "message", {"c": 3})

    assert (e1["seq"], e2["seq"], e3["seq"]) == (1, 1, 2)
    assert bus.current_seq("onboarding") == 2
    assert sub.queue.qsize() == 3
    assert only_sidebar.queue.qsize() == 1  # not subscribed to onboarding


def test_unsubscribed_topic_not_delivered():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish("session:x", "message", {})
    assert sub.queue.qsize() == 0


def test_overflow_marks_dead():
    bus = EventBus(max_queue=2)
    sub = bus.subscribe()
    for _ in range(3):
        bus.publish("sidebar", "tick", {})
    assert sub.dead.is_set()


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    sub = bus.subscribe()
    bus.unsubscribe(sub)
    bus.publish("sidebar", "tick", {})
    assert sub.queue.qsize() == 0
