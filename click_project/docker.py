#!/usr/bin/env python
# -*- coding:utf-8 -*-

import os
import click
import getpass

from click_project.lib import cd, call
from click_project.decorators import option, argument, flag, group as group_
from click_project.core import cache_disk
from click_project.lib import ParameterType, check_output
from click_project.completion import startswith
from click_project.config import config


def docker_command(group=None, **kwargs):
    """A decorator to create a group with docker subcommands"""
    def decorator(f):
        opts = dict((k, v) for k, v in kwargs.items() if k in ['directory', 'extra_options'])
        for k in opts.keys():
            del kwargs[k]
        g = group.group(**kwargs)(f) if group else group_(**kwargs)(f)
        docker_generic_commands(g, **opts)
        return g
    return decorator


def docker_generic_commands(group, directory, extra_options=lambda: ["-p", config.simulator_name.lower()]):
    def abs_directory():
        return os.path.abspath(directory() if callable(directory) else directory)

    def docker_compose(args, internal=False):
        call(["docker-compose"] +
             (extra_options() if callable(extra_options) else extra_options) +
             args, internal=internal, cwd=abs_directory())

    class DockerServices(ParameterType):
        @property
        def choices(self):
            @cache_disk(expire=60)
            def compute(directory, args):
                with cd(directory, internal=True):
                    return [
                        s.strip()
                        for s in
                        check_output(["docker-compose"] + args + ["config", "--services"],
                                     internal=True).splitlines()
                    ]
            return compute(abs_directory(), extra_options() if callable(extra_options) else extra_options)

        def complete(self, ctx, incomplete):
            return [
                choice
                for choice in self.choices
                if startswith(choice, incomplete)
            ]

    @group.command()
    @argument("service", type=DockerServices(), nargs=-1, help="The services to spin up")
    @option('--scale', 'scales', help="Scale a service. Use the format 'service=number'", multiple=True)
    @flag("--force-recreate/--no-force-recreate", help="Force the recreation of the services")
    def up(service, force_recreate, scales):
        """Create and start containers"""
        user_in_docker_group()
        up_args = []
        for scale in scales:
            up_args += ['--scale', scale]
        docker_compose(
            ['up', '-d', '--build'] +
            up_args +
            (["--force-recreate"] if force_recreate else []) +
            list(service)
        )

    @group.command()
    @option('--remove-orphans/--no-remove-orphans', default=True,
            help="Remove the container of the project that are not in the current config")
    def down(remove_orphans):
        """Stop and remove containers, networks, images, and volumes"""
        args = []
        if remove_orphans:
            args += ['--remove-orphans']
        docker_compose(['down'] + args)

    @group.command()
    @argument("service", type=DockerServices(), nargs=-1, help="The services to start")
    def start(service):
        """Start services"""
        with cd(abs_directory()):
            docker_compose(['start'] + list(service))

    @group.command()
    @argument("service", type=DockerServices(), nargs=-1, help="The services to stop")
    def stop(service):
        """Stop services"""
        docker_compose(['stop'] + list(service))

    @group.command()
    @argument("service", type=DockerServices(), nargs=-1, help="The services to restart")
    def restart(service):
        """Restart services"""
        docker_compose(['restart'] + list(service))

    @group.command(ignore_unknown_options=True)
    @argument("service", type=DockerServices(), nargs=-1, help="The services to list")
    def ps(service):
        """List containers"""
        service = service or []
        docker_compose(['ps'] + list(service))

    @group.command(ignore_unknown_options=True)
    @argument("service", type=DockerServices(), nargs=-1, help="The services to check the status")
    def status(service):
        """Show the services status"""
        service = service or []
        docker_compose(['ps'] + list(service))

    @group.command()
    @argument("service", type=DockerServices(), nargs=-1, help="The services to show the logs")
    def logs(service):
        """View output logs from containers"""
        docker_compose(['logs', '-f'] + list(service))

    @group.command()
    @option("--services/--no-services", help="List the services instead of the whole configuration")
    def _config(services):
        """Validate and view the compose file"""
        docker_compose(['config'] + (['--services'] if services else []))

    @group.command(ignore_unknown_options=True)
    @argument("service", type=DockerServices(), help="The container where the command will be run")
    @argument("command", nargs=-1, help="The command to run in the container")
    def _exec(service, command):
        """Execute a command in the running container"""
        docker_compose(['exec', service] + list(command))

    @group.command(ignore_unknown_options=True)
    @argument("service", type=DockerServices(), help="The container where the command will be run")
    @argument("command", nargs=-1, help="The command to run in the container")
    def run(service, command):
        """Run a one-off command in the container"""
        docker_compose(['run', service] + list(command))

    @group.command(ignore_unknown_options=True)
    @argument("service", type=DockerServices(), required=False, help="The service to build")
    @argument("args", nargs=-1, help="Extra arguments to pass to the build command")
    def build(service, args):
        """Build the container"""
        command = ['build'] + ([service] if service else []) + list(args)
        docker_compose(command)

    @group.command(ignore_unknown_options=True)
    @argument("args", nargs=-1, help="Extra arguments to pass to the images command")
    def images(args):
        """Build the container"""
        command = ['images'] + list(args)
        docker_compose(command)

    @group.command()
    def fix_up():
        """Add the current user to the docker group. Calling this will result in changing /etc/group using sudo
        and relogging using the 'login' command"""
        call(['sudo', 'adduser', getpass.getuser(), 'docker'])
        call(['sudo', 'login'])

    def user_in_docker_group():
        try:
            import grp
            groups = [g.gr_name for g in grp.getgrall() if getpass.getuser() in g.gr_mem]
            if 'docker' not in groups:
                raise click.ClickException("The current user is not in the docker group."
                                           " Please add it to '/etc/group' or use 'fix-up'")
        except ImportError:
            pass
