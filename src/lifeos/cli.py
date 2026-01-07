from dotenv import load_dotenv

from lifeos import logging


def main():
    load_dotenv()
    logging.setup()

    from lifeos.agent import process_message
    from lifeos.db import init_db

    init_db()

    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input.strip():
            continue

        response = process_message(user_input, chat_id="cli")
        print(response)


if __name__ == "__main__":
    main()
