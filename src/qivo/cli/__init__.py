import click
import json

from dotenv import load_dotenv
from qivo.settings import BASE_TOML, load_toml_file
from qivo.cli import migrate
from qivo.cli import run
from qivo.cli import seed


@click.group()
@click.option("--env", "-e", type=str, default=None)
@click.option("--quiet-env", "-qe", is_flag=True, default=False)
def cli(env=None, quiet_env=False):
    subenv = env
    if subenv and not quiet_env:
        click.echo(f"Using {subenv}")
    load_dotenv(".env" if not subenv else f".env.{subenv}", override=True)

@cli.command()
def init():
    with open("qivo.toml", "w", encoding="utf-8") as f:
        f.write(BASE_TOML)

@cli.command("config:dump")
def config_dump():
    data = load_toml_file("qivo.toml")
    click.echo(json.dumps(data, indent=2))

cli.add_command(run.run_app)
cli.add_command(seed.run_seeder)

for command in migrate.commands:
    cli.add_command(command)
