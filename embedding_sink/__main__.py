"""Entrypoint: python -m embedding_sink."""
import logging
from .sink import EmbeddingSink


def main() -> None:
    """Configure logging and run the sink loop forever."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    EmbeddingSink.from_env().run_forever()


if __name__ == "__main__":
    main()
