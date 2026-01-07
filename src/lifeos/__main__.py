from dotenv import load_dotenv

from lifeos import logging


def main():
    load_dotenv()
    logging.setup()

    from lifeos.bot import run_bot

    run_bot()


if __name__ == "__main__":
    main()
