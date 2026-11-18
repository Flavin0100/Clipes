from clipador.cli import build_parser


def test_parse_args():
    a = build_parser().parse_args(["https://youtu.be/x", "--max-clips", "10", "--min", "20", "--max", "60"])
    assert a.max_clips == 10 and a.min_seconds == 20 and a.max_seconds == 60
