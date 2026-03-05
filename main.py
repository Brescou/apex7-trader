from app import app


def main():
    app.run(debug=False, host="0.0.0.0", port=8050)


if __name__ == "__main__":
    main()
