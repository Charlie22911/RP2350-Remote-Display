from rp2350_remote_display.protocol import MSG_SESSION_CLOSE, CAP_SESSION_REATTACH


def test_session_protocol_constants() -> None:
    assert MSG_SESSION_CLOSE == 0x0D
    assert CAP_SESSION_REATTACH == 1 << 9
