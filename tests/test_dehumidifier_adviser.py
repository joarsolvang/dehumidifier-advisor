from dehumidifier_adviser import hello


def test_dehumidifier_adviser_says_hello() -> None:
    assert hello() == "Hello, world!"
