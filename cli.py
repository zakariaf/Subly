"""Command-line entry point — handy for testing the pipeline without Telegram.

    python cli.py input.mp4 -l Spanish -o out.srt
    python cli.py input.mp4 -l Chinese --bilingual
"""

import argparse
import sys

from subtrans.config import Config
from subtrans.pipeline import run


def main() -> int:
    p = argparse.ArgumentParser(description="Translate a video/audio file into an SRT subtitle file.")
    p.add_argument("input", help="Path to a video or audio file")
    p.add_argument("-l", "--language", required=True, help="Target language (e.g. Spanish, Chinese)")
    p.add_argument("-o", "--output", help="Output .srt path (default: <input>.<lang>.srt)")
    p.add_argument("--source-language", default=None, help="Source language hint (default: auto-detect)")
    p.add_argument("--bilingual", action="store_true", help="Keep original text under each translation")
    p.add_argument("--burn", action="store_true",
                   help="Also burn subtitles into the video (writes <input>.subbed.mp4)")
    args = p.parse_args()

    cfg = Config.from_env()

    def on_stage(name):
        print({"extract": "🎬 Extracting audio…",
               "transcribe": "🎙  Transcribing…",
               "translate": "🌐 Translating…",
               "build": "📝 Building SRT…"}[name], file=sys.stderr)

    srt_text = run(
        args.input,
        target_language=args.language,
        cfg=cfg,
        source_language=args.source_language,
        bilingual=args.bilingual,
        on_stage=on_stage,
    )

    out = args.output or f"{args.input.rsplit('.', 1)[0]}.{args.language.lower()}.srt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(srt_text)
    print(f"✅ Wrote {out}", file=sys.stderr)

    if args.burn:
        from subtrans.video import burn_subtitles, has_video_stream
        if not has_video_stream(args.input):
            print("⚠️  Input has no video track — skipping burn.", file=sys.stderr)
        else:
            print("🔥 Burning subtitles into video…", file=sys.stderr)
            burned = f"{args.input.rsplit('.', 1)[0]}.subbed.mp4"
            burn_subtitles(args.input, out, burned, args.language)
            print(f"✅ Wrote {burned}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
