import asyncio

from dotenv import load_dotenv

from lifeos import logging


async def run_cli() -> None:
    load_dotenv()
    logging.setup()

    from lifeos.agent import process_message
    from lifeos.db import init_db

    init_db()

    while True:
        try:
            user_input = await asyncio.to_thread(input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input.strip():
            continue

        response = await process_message(user_input, chat_id="cli")
        print(response)


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
