"""Application entry point."""

from __future__ import annotations

import argparse
import signal
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="synthrack", description="A patchable rack of drum machines, "
                                     "synths and tape")
    parser.add_argument("--rack", help="load this rack at startup")
    parser.add_argument("--start", action="store_true", help="start the audio engine immediately")
    parser.add_argument("--play", action="store_true", help="start the engine and the transport")
    parser.add_argument("--screenshot", metavar="PNG",
                        help="render the window to a PNG and exit (no audio)")
    args = parser.parse_args(argv)

    # The audio callback is Python too. Let it take the GIL from the UI thread
    # within 0.1 ms instead of the default 5 ms, which is as long as a buffer.
    sys.setswitchinterval(1e-4)

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Synth Rack")
    window = MainWindow()
    if args.rack:
        window._load_rack(args.rack)
    window.show()
    # `kill` / Ctrl-C close the window properly, so the session is still saved.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: QTimer.singleShot(0, window.close))
    window.raise_()
    window.activateWindow()

    if args.screenshot:
        def shoot():
            window.grab().save(args.screenshot)
            window.closeEvent = lambda event: event.accept()  # leave the saved session alone
            app.quit()
        QTimer.singleShot(600, shoot)
    elif args.play:
        QTimer.singleShot(200, lambda: window._play(True))
    elif args.start:
        QTimer.singleShot(200, lambda: window._power(True))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
