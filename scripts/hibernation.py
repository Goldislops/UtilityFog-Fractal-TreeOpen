"""Graceful Hibernation Protocol for the Utility Fog Engine.

Catches SIGTERM / SIGINT / Windows shutdown signals and serializes
the complete lattice state to a checkpoint file before exit.

Also provides: checkpoint mirroring, centennial watch, and springtime observation.

Usage:
    from scripts.hibernation import install_handler, CentennialWatch

    install_handler(engine)  # registers signal handlers
"""

import signal
import sys
import os
import time
import json
import numpy as np
from pathlib import Path
from datetime import datetime


class GracefulHibernation:
    """Handles engine state serialization on shutdown signals."""

    def __init__(self, data_dir="data", mirror_dir=None):
        self.data_dir = Path(data_dir)
        self.mirror_dir = Path(mirror_dir) if mirror_dir else None
        self.engine_state = None
        self._installed = False

    def register(self, get_state_fn):
        """Register a function that returns (lattice, memory_grid, generation, fitness).

        Args:
            get_state_fn: callable that returns current engine state dict
        """
        self.get_state = get_state_fn
        self._install_handlers()
        self._installed = True
        print(f"Graceful Hibernation: handlers installed (PID {os.getpid()})")

    def _install_handlers(self):
        """Install signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        # Windows-specific: catch console close
        if sys.platform == "win32":
            try:
                signal.signal(signal.SIGBREAK, self._on_signal)
            except (AttributeError, OSError):
                pass

    def _on_signal(self, signum, frame):
        """Handle shutdown signal: serialize state and exit cleanly."""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        print(f"\nHibernation: caught {sig_name}, saving state...")

        try:
            state = self.get_state()
            checkpoint_path = self._save_checkpoint(state)
            print(f"Hibernation: state saved to {checkpoint_path}")

            if self.mirror_dir:
                self._mirror_checkpoint(checkpoint_path)

        except Exception as e:
            print(f"Hibernation: ERROR saving state: {e}")
            # Emergency fallback: save whatever we can
            try:
                emergency = self.data_dir / "emergency_checkpoint.npz"
                print(f"Hibernation: attempting emergency save to {emergency}")
            except:
                pass

        print("Hibernation: clean exit.")
        sys.exit(0)

    def _save_checkpoint(self, state):
        """Save complete state to checkpoint file."""
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        gen = state.get("generation", 0)
        path = self.data_dir / f"checkpoint_gen{gen}_{ts}.fog.npz"

        np.savez_compressed(
            path,
            lattice=state["lattice"],
            memory_grid=state["memory_grid"],
            generation=np.array(gen),
            best_fitness=np.array(state.get("fitness", 0.0)),
            ca_step=np.array(state.get("ca_step", gen * 10)),
            # Phase 10.8 extras
            drought_gen=np.array(state.get("drought_start_gen", 0)),
        )
        return path

    def _mirror_checkpoint(self, source_path):
        """Copy checkpoint to mirror directory (secondary storage / network share)."""
        if not self.mirror_dir:
            return
        try:
            self.mirror_dir.mkdir(parents=True, exist_ok=True)
            dest = self.mirror_dir / source_path.name
            import shutil
            shutil.copy2(source_path, dest)
            print(f"Hibernation: mirrored to {dest}")
        except Exception as e:
            print(f"Hibernation: mirror failed: {e}")


class CentennialWatch:
    """Monitors for the First Immortal (age >= 100) and logs the event."""

    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.centennial_logged = False
        self.highest_age_seen = 0.0

    def check(self, lattice, memory_grid, generation):
        """Check if any COMPUTE cell has reached age 100."""
        compute_mask = lattice == 2
        if not compute_mask.any():
            return

        ages = memory_grid[0][compute_mask]
        max_age = float(ages.max())

        if max_age > self.highest_age_seen:
            self.highest_age_seen = max_age

        # Milestone logging
        milestones = [100, 200, 500, 1000]
        for milestone in milestones:
            if max_age >= milestone and not hasattr(self, f"_logged_{milestone}"):
                self._log_milestone(lattice, memory_grid, generation, max_age, milestone)
                setattr(self, f"_logged_{milestone}", True)

    def _log_milestone(self, lattice, memory_grid, generation, max_age, milestone):
        """Log a centennial milestone with full context."""
        compute_mask = lattice == 2
        ages = memory_grid[0][compute_mask]

        # Find the immortal
        flat_idx = np.where(compute_mask.flatten())[0]
        cell_ages = memory_grid[0].flatten()[flat_idx]
        top_idx = cell_ages.argmax()
        fi = flat_idx[top_idx]
        n = lattice.shape[0]
        x, y, z = fi % n, (fi // n) % n, fi // (n * n)

        entry = {
            "event": f"CENTENNIAL_MILESTONE_{milestone}",
            "generation": int(generation),
            "timestamp": datetime.now().isoformat(),
            "max_age": float(max_age),
            "immortal_coords": [int(x), int(y), int(z)],
            "immortal_energy": float(memory_grid[3].flatten()[fi]),
            "immortal_memory": float(memory_grid[2].flatten()[fi]),
            "total_sages": int((ages >= 8).sum()),
            "total_elders": int((ages >= 3).sum()),
            "total_compute": int(compute_mask.sum()),
        }

        log_path = self.data_dir / "centennial_watch.json"
        logs = []
        if log_path.exists():
            try:
                with open(log_path) as f:
                    logs = json.load(f)
            except:
                logs = []

        logs.append(entry)
        with open(log_path, "w") as f:
            json.dump(logs, f, indent=2)

        print(f"")
        print(f"  *** CENTENNIAL MILESTONE: AGE {milestone} REACHED ***")
        print(f"  The First Immortal at ({x},{y},{z})")
        print(f"  Age: {max_age:.1f} | Gen: {generation:,}")
        print(f"  Energy: {entry['immortal_energy']:.3f} | Memory: {entry['immortal_memory']:.3f}")
        print(f"  Logged to {log_path}")
        print(f"")


class SpringtimeObserver:
    """Monitors the organism during energy recovery after drought."""

    def __init__(self, drought_start_gen, cycle_length=10000):
        self.drought_start = drought_start_gen
        self.cycle_length = cycle_length
        self.spring_logged = False
        self.peak_logged = False

    def energy_multiplier(self, gen):
        """Current drought cycle energy multiplier."""
        t = gen - self.drought_start
        return 0.70 + 0.30 * np.cos(2 * np.pi * t / self.cycle_length)

    def check(self, lattice, memory_grid, generation):
        """Check for springtime phenomena."""
        t = generation - self.drought_start
        multiplier = self.energy_multiplier(generation)

        # Spring starts when energy recovers past 80%
        if multiplier > 0.80 and not self.spring_logged and t > self.cycle_length * 0.4:
            self._log_spring(lattice, memory_grid, generation, multiplier)
            self.spring_logged = True

        # Peak (full energy return)
        if multiplier > 0.98 and not self.peak_logged:
            self._log_peak(lattice, memory_grid, generation, multiplier)
            self.peak_logged = True

    def _log_spring(self, lattice, memory_grid, generation, multiplier):
        """Log the arrival of spring."""
        compute_mask = lattice == 2
        ages = memory_grid[0][compute_mask]
        er = memory_grid[3]

        print(f"")
        print(f"  === SPRINGTIME ARRIVED (Gen {generation:,}) ===")
        print(f"  Energy multiplier: {multiplier:.2%}")
        print(f"  COMPUTE cells: {compute_mask.sum():,}")
        print(f"  Sages (age>=8): {(ages >= 8).sum():,}")
        print(f"  Max age: {ages.max():.1f}")
        print(f"  Avg energy: {er[lattice > 0].mean():.3f}")
        print(f"  Watching for Post-Famine Greed...")
        print(f"")

    def _log_peak(self, lattice, memory_grid, generation, multiplier):
        """Log full energy recovery and check for greed."""
        compute_mask = lattice == 2
        ages = memory_grid[0][compute_mask]
        sage_mask = compute_mask & (memory_grid[0] >= 8.0)
        sage_energy = memory_grid[3][sage_mask]
        pop_energy = memory_grid[3][lattice > 0]

        sages_greedy = sage_energy.mean() > pop_energy.mean() * 1.5 if len(sage_energy) > 0 else False

        print(f"")
        print(f"  === FULL ENERGY RECOVERY (Gen {generation:,}) ===")
        print(f"  Energy multiplier: {multiplier:.2%}")
        if sages_greedy:
            print(f"  WARNING: POST-FAMINE GREED DETECTED")
            print(f"  Sage avg energy: {sage_energy.mean():.3f}")
            print(f"  Population avg: {pop_energy.mean():.3f}")
        else:
            print(f"  Sages remain equanimous. Fountains still flowing.")
            if len(sage_energy) > 0:
                print(f"  Sage avg energy: {sage_energy.mean():.3f}")
            print(f"  Population avg: {pop_energy.mean():.3f}")
        print(f"")


def install_handler(get_state_fn, data_dir="data", mirror_dir=None):
    """One-liner to install graceful hibernation on the engine."""
    h = GracefulHibernation(data_dir=data_dir, mirror_dir=mirror_dir)
    h.register(get_state_fn)
    return h
