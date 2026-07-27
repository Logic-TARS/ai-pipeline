from pathlib import Path

from content_pipeline.grouping import group_by_prefix


def test_multiple_prefixes() -> None:
    images = [
        Path("a_001.jpg"),
        Path("a_002.jpg"),
        Path("a_010.jpg"),
        Path("b_001.jpg"),
        Path("b_002.jpg"),
        Path("c_001.jpg"),
    ]
    result = group_by_prefix(images)
    assert len(result) == 3
    assert list(result.keys()) == ["a_", "b_", "c_"]
    assert result["a_"] == [Path("a_001.jpg"), Path("a_002.jpg"), Path("a_010.jpg")]
    assert result["b_"] == [Path("b_001.jpg"), Path("b_002.jpg")]
    assert result["c_"] == [Path("c_001.jpg")]


def test_single_prefix() -> None:
    images = [
        Path("naruto_final_001.jpg"),
        Path("naruto_final_002.jpg"),
        Path("naruto_final_010.jpg"),
    ]
    result = group_by_prefix(images)
    assert len(result) == 1
    assert "naruto_final_" in result
    assert result["naruto_final_"] == [
        Path("naruto_final_001.jpg"),
        Path("naruto_final_002.jpg"),
        Path("naruto_final_010.jpg"),
    ]


def test_no_trailing_digits() -> None:
    images = [
        Path("image.jpg"),
        Path("photo.png"),
        Path("picture.webp"),
    ]
    result = group_by_prefix(images)
    assert len(result) == 3
    assert result["image.jpg"] == [Path("image.jpg")]
    assert result["photo.png"] == [Path("photo.png")]
    assert result["picture.webp"] == [Path("picture.webp")]


def test_empty_list() -> None:
    result = group_by_prefix([])
    assert result == {}


def test_natural_sort_order() -> None:
    images = [
        Path("hero_010.jpg"),
        Path("hero_002.jpg"),
        Path("hero_001.jpg"),
        Path("hero_1.jpg"),
    ]
    result = group_by_prefix(images)
    assert len(result) == 1
    assert result["hero_"] == [
        Path("hero_001.jpg"),
        Path("hero_1.jpg"),
        Path("hero_002.jpg"),
        Path("hero_010.jpg"),
    ]


def test_mixed_valid_and_invalid() -> None:
    images = [
        Path("char_001.jpg"),
        Path("char_002.jpg"),
        Path("random.jpg"),
        Path("char_010.jpg"),
    ]
    result = group_by_prefix(images)
    assert len(result) == 2
    assert "char_" in result
    assert "random.jpg" in result
    assert result["char_"] == [
        Path("char_001.jpg"),
        Path("char_002.jpg"),
        Path("char_010.jpg"),
    ]
    assert result["random.jpg"] == [Path("random.jpg")]
