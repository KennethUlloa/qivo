import click

from qivo.cli import migrate
from qivo.cli import run
from qivo.cli import seed


@click.group()
def cli():
    pass


cli.add_command(run.run_app)
cli.add_command(seed.run_seeder)

[cli.add_command(command) for command in migrate.commands]