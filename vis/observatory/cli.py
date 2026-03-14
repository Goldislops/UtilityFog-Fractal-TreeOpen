"""Cosmic Observatory: CLI entry point.

Phase 8 -- The Cosmic Observatory

Usage:
    python -m vis.observatory body <snapshot>
    python -m vis.observatory slice <snapshot> [--axis z] [--level 32]
    python -m vis.observatory signal <snapshot>
    python -m vis.observatory warmth <snapshot>
    python -m vis.observatory elders <snapshot>
    python -m vis.observatory channel <snapshot> <channel_index>
    python -m vis.observatory dashboard <snapshot>
    python -m vis.observatory animate <data_dir> [--max-frames 50]
    python -m vis.observatory info <snapshot>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cosmic-observatory",
        description="Phase 8 Cosmic Observatory -- UtilityFog CA Visualization",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- body: 3D organism view -------------------------------------------
    p_body = sub.add_parser("body", help="3D organism body (Plotly WebGL)")
    p_body.add_argument("snapshot", help="Path to .npz or .genome.json file")
    p_body.add_argument("--save", help="Save as HTML file")
    p_body.add_argument("--show-void", action="store_true",
                        help="Include void cells in render")

    # ---- slice: 2D cross-section ------------------------------------------
    p_slice = sub.add_parser("slice", help="2D lattice slice (matplotlib)")
    p_slice.add_argument("snapshot")
    p_slice.add_argument("--axis", choices=["x", "y", "z"], default="z")
    p_slice.add_argument("--level", type=int, default=None)
    p_slice.add_argument("--channel", type=int, default=None,
                         help="Overlay memory channel (0-7)")
    p_slice.add_argument("--save", help="Save as PNG file")

    # ---- tri: three orthogonal slices -------------------------------------
    p_tri = sub.add_parser("tri", help="Three orthogonal slices (matplotlib)")
    p_tri.add_argument("snapshot")
    p_tri.add_argument("--channel", type=int, default=None,
                       help="Show memory channel instead of states (0-7)")
    p_tri.add_argument("--save", help="Save as PNG file")

    # ---- signal: signal field 3D view -------------------------------------
    p_signal = sub.add_parser("signal", help="Signal field 3D view (Plotly)")
    p_signal.add_argument("snapshot")
    p_signal.add_argument("--save", help="Save as HTML")
    p_signal.add_argument("--threshold", type=float, default=0.01)

    # ---- warmth: metta warmth 3D view ------------------------------------
    p_warmth = sub.add_parser("warmth", help="Metta warmth 3D view (Plotly)")
    p_warmth.add_argument("snapshot")
    p_warmth.add_argument("--save", help="Save as HTML")

    # ---- elders: compute age 3D view -------------------------------------
    p_elders = sub.add_parser("elders", help="Compute elder cells 3D view (Plotly)")
    p_elders.add_argument("snapshot")
    p_elders.add_argument("--save", help="Save as HTML")

    # ---- channel: arbitrary channel view ----------------------------------
    p_chan = sub.add_parser("channel", help="View any memory channel")
    p_chan.add_argument("snapshot")
    p_chan.add_argument("channel_index", type=int, choices=range(8),
                        metavar="CHANNEL")
    p_chan.add_argument("--mode", choices=["slice", "3d"], default="3d")
    p_chan.add_argument("--axis", choices=["x", "y", "z"], default="z")
    p_chan.add_argument("--level", type=int, default=None)
    p_chan.add_argument("--save", help="Save output")

    # ---- dashboard: multi-panel summary -----------------------------------
    p_dash = sub.add_parser("dashboard", help="Full observatory dashboard (matplotlib)")
    p_dash.add_argument("snapshot")
    p_dash.add_argument("--save", help="Save as PNG")

    # ---- animate: time-lapse GIF ------------------------------------------
    p_anim = sub.add_parser("animate", help="Animated time-lapse GIF")
    p_anim.add_argument("data_dir", help="Directory containing .npz files")
    p_anim.add_argument("--max-frames", type=int, default=50)
    p_anim.add_argument("--fps", type=int, default=4)
    p_anim.add_argument("--output", default="observatory_timelapse.gif")
    p_anim.add_argument("--channel", type=int, default=None,
                        help="Overlay memory channel (0-7)")
    p_anim.add_argument("--axis", choices=["x", "y", "z"], default="z")

    # ---- info: snapshot metadata ------------------------------------------
    p_info = sub.add_parser("info", help="Show snapshot metadata and statistics")
    p_info.add_argument("snapshot")

    args = parser.parse_args(argv)

    # Lazy imports to keep CLI fast
    from vis.observatory.loader import load_snapshot
    from vis.observatory.constants import (
        STATE_NAMES, CHANNEL_NAMES, SIGNAL_FIELD_CHANNEL, WARMTH_CHANNEL,
        COMPUTE_AGE_CHANNEL,
    )

    # ---- Dispatch ---------------------------------------------------------

    if args.command == "info":
        snap = load_snapshot(args.snapshot)
        print(f"Source:     {snap.source_path}")
        print(f"Shape:      {snap.shape}")
        print(f"Generation: {snap.generation:,}")
        print(f"CA Step:    {snap.ca_step:,}")
        print(f"Fitness:    {snap.best_fitness:.4f}")
        print(f"Non-void:   {snap.non_void_count:,} / {int(__import__('numpy').prod(snap.shape)):,}")
        print()
        for sid, name in STATE_NAMES.items():
            cnt = snap.state_count(sid)
            pct = cnt / int(__import__('numpy').prod(snap.shape)) * 100
            print(f"  {name:12s}: {cnt:>8,} ({pct:5.1f}%)")
        print()
        import numpy as _np
        for ci, cname in enumerate(CHANNEL_NAMES):
            ch = snap.channel(ci)
            nonvoid = ch[snap.lattice > 0]
            if len(nonvoid) > 0:
                print(f"  Ch {ci} {cname:22s}: "
                      f"min={nonvoid.min():+.4f}  max={nonvoid.max():+.4f}  "
                      f"mean={nonvoid.mean():+.4f}")
        return

    if args.command == "slice":
        snap = load_snapshot(args.snapshot)
        if args.channel is not None:
            from vis.observatory.slicer import slice_composite
            fig, _ = slice_composite(
                snap, axis=args.axis, level=args.level,
                overlay_channel=args.channel, save_path=args.save,
            )
        else:
            from vis.observatory.slicer import slice_lattice
            fig, _ = slice_lattice(
                snap, axis=args.axis, level=args.level, save_path=args.save,
            )
        if not args.save:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return

    if args.command == "tri":
        snap = load_snapshot(args.snapshot)
        from vis.observatory.slicer import tri_slice
        fig = tri_slice(snap, channel=args.channel, save_path=args.save)
        if not args.save:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return

    if args.command == "body":
        snap = load_snapshot(args.snapshot)
        from vis.observatory.scatter3d import organism_body
        fig = organism_body(snap, show_void=args.show_void, save_html=args.save)
        if not args.save:
            fig.show()
        return

    if args.command == "signal":
        snap = load_snapshot(args.snapshot)
        from vis.observatory.scatter3d import signal_field_3d
        fig = signal_field_3d(snap, threshold=args.threshold, save_html=args.save)
        if not args.save:
            fig.show()
        return

    if args.command == "warmth":
        snap = load_snapshot(args.snapshot)
        from vis.observatory.scatter3d import warmth_glow_3d
        fig = warmth_glow_3d(snap, save_html=args.save)
        if not args.save:
            fig.show()
        return

    if args.command == "elders":
        snap = load_snapshot(args.snapshot)
        from vis.observatory.scatter3d import compute_elders_3d
        fig = compute_elders_3d(snap, save_html=args.save)
        if not args.save:
            fig.show()
        return

    if args.command == "channel":
        snap = load_snapshot(args.snapshot)
        if args.mode == "slice":
            from vis.observatory.slicer import slice_channel
            fig, _ = slice_channel(
                snap, args.channel_index, axis=args.axis, level=args.level,
                save_path=args.save,
            )
            if not args.save:
                import matplotlib.pyplot as plt
                plt.show()
            else:
                import matplotlib.pyplot as plt
                plt.close(fig)
        else:
            from vis.observatory.scatter3d import channel_overlay
            fig = channel_overlay(
                snap, args.channel_index, save_html=args.save,
            )
            if not args.save:
                fig.show()
        return

    if args.command == "dashboard":
        snap = load_snapshot(args.snapshot)
        from vis.observatory.dashboard import observatory_dashboard
        fig = observatory_dashboard(snap, save_path=args.save)
        if not args.save:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return

    if args.command == "animate":
        from vis.observatory.animation import animate_from_directory
        animate_from_directory(
            args.data_dir,
            max_frames=args.max_frames,
            output_path=args.output,
            fps=args.fps,
            overlay_channel=args.channel,
            axis=args.axis,
        )
        return


if __name__ == "__main__":
    main()
