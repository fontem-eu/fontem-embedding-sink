import logging
from .sink import EmbeddingSink


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    EmbeddingSink.from_env().run_forever()


if __name__ == "__main__":
    main()
