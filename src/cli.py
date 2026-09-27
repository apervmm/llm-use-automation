import click
from dotenv import load_dotenv

load_dotenv()

from commands.discover import discover
from commands.replay import replay


@click.group()
def cli():
    """Computer-use automation CLI"""


cli.add_command(discover)
cli.add_command(replay)


if __name__ == "__main__":
    cli()