import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s/%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from dashboard import create_app  # noqa: E402

app = create_app()


def main():
    app.run(debug=False, host="0.0.0.0", port=8050)


if __name__ == "__main__":
    main()
