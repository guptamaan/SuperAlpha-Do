"""Audio filter graph for FFmpeg (bass, nightcore, 8D, EQ presets, ...)."""

from __future__ import annotations


EQ_PRESETS = {
    "bass": "equalizer=f=100:width_type=o:width=2:g=15",
    "treble": "equalizer=f=3000:width_type=o:width=2:g=10",
    "pop": "equalizer=f=500:width_type=o:width=2:g=6,equalizer=f=3000:width_type=o:width=2:g=6",
    "rock": "equalizer=f=100:width_type=o:width=2:g=8,equalizer=f=5000:width_type=o:width=2:g=8",
    "jazz": "equalizer=f=200:width_type=o:width=2:g=5,equalizer=f=4000:width_type=o:width=2:g=5",
    "classical": "equalizer=f=300:width_type=o:width=2:g=5,equalizer=f=2000:width_type=o:width=2:g=5",
    "electronic": "equalizer=f=100:width_type=o:width=2:g=12,equalizer=f=5000:width_type=o:width=2:g=8",
}


def build_filter_string(player) -> str:
    filters = []
    if player.bassboost:
        filters.append("bass=g=15")
    if player.nightcore:
        filters.append("asetrate=48000*1.25,aresample=48000")
    if player.eight_d:
        filters.append("aecho=0.8:0.9:50:0.5,aecho=0.8:0.9:70:0.4,apulsator=hz=0.3,stereowiden=1.5")
    if player.slowed:
        filters.append("asetrate=44100*0.75,aresample=44100,aecho=0.8:0.88:60:0.4")
    eq = player.equalizer.lower()
    if eq != "flat" and eq:
        if eq in EQ_PRESETS:
            filters.append(EQ_PRESETS[eq])
    return ",".join(filters) if filters else ""


def get_ffmpeg_opts(filter_str: str = "") -> dict:
    before = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -thread_queue_size 8192"
    options = "-vn -bufsize 384k -maxrate 256k"
    if filter_str:
        options += f' -af "{filter_str}"'
    return {
        "before_options": before,
        "options": options,
    }