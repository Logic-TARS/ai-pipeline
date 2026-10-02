from content_pipeline.models import TaskInput
from content_pipeline.router import route_task
from content_pipeline.settings import Settings


def test_explicit_content_type_skips_llm() -> None:
    task = TaskInput(description="anything", content_type="anime", topic="topic", params={"x": 1})
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "anime"
    assert route.topic == "topic"
    assert route.params == {"x": 1}


def test_rule_router_detects_finance() -> None:
    task = TaskInput(description="做一个股票和基金的财经短视频")
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "finance"


def test_rule_router_detects_ai_art_before_anime_keywords() -> None:
    task = TaskInput(description="把动漫图片做成 AI 绘画改图视频")
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "ai_art"


def test_rule_router_detects_ai_briefing() -> None:
    task = TaskInput(description="把今天的 AI 简报做成人工智能新闻视频")
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "ai_briefing"


def test_rule_router_detects_japanese_before_ai_art() -> None:
    task = TaskInput(description="把图片文件夹做成日语改图并保存本地")
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "japanese"


def test_rule_router_keeps_ai_briefing_cover_in_ai_briefing_pipeline() -> None:
    task = TaskInput(description="为今天的 AI 简报生成封面和视频")
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "ai_briefing"


def test_rule_router_does_not_offer_standalone_cover() -> None:
    task = TaskInput(description="只生成封面")
    route = route_task(task, Settings(_env_file=None))
    assert route.content_type == "unknown"


def test_explicit_content_type_normalizes_topic() -> None:
    task = TaskInput(description="anything", content_type="anime", topic="  周五下班  ")
    route = route_task(task, Settings(_env_file=None))

    assert route.topic == "周五下班"
