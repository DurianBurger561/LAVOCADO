"""Command-line entry point for LAVOCADO."""

from app.service import LavocadoService


def main() -> None:
    service = LavocadoService()
    print("LAVOCADO protection is active. Press Ctrl+C to stop.")

    try:
        service.start()
    except KeyboardInterrupt:
        service.stop()
        print("\nLAVOCADO protection stopped.")


if __name__ == "__main__":
    main()
