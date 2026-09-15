from features.salm.media import RollingAudioActivity


def test_short_sound_does_not_create_media_session():
    rolling = RollingAudioActivity()
    assert not rolling.update((("chrome", 0.5, True),), now=0)
    assert not rolling.update((("chrome", 0.0, True),), now=1)


def test_two_sessions_in_one_poll_are_still_one_sample():
    rolling = RollingAudioActivity()
    assert not rolling.update((("chrome", 0.5, True), ("chrome", 0.7, True)), now=0)


def test_two_peaks_activate_and_eight_second_hangtime():
    rolling = RollingAudioActivity()
    rolling.update((("vlc", 0.2, True),), now=0)
    assert rolling.update((("vlc", 0.3, True),), now=1) == frozenset(("vlc",))
    assert rolling.update((("vlc", 0.0, True),), now=8.9) == frozenset(("vlc",))
    assert not rolling.update((("vlc", 0.0, True),), now=9.01)


def test_peak_returning_inside_hangtime_keeps_activity():
    rolling = RollingAudioActivity()
    rolling.update((("vlc", 0.2, True),), now=0)
    rolling.update((("vlc", 0.2, True),), now=1)
    rolling.update((("vlc", 0.0, True),), now=8)
    assert rolling.update((("vlc", 0.2, True),), now=8.5) == frozenset(("vlc",))
    assert rolling.update((("vlc", 0.0, True),), now=16) == frozenset(("vlc",))
