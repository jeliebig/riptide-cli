"""Click extension module"""

# TODO: Colored subcommand help
from click_help_colors import HelpColorsGroup


class ClickMainGroup(HelpColorsGroup):
    """
    Special group class that calls the group_callback always as a pre-invoke hook even
    before checking if the subcommand exists.

    Also allows grouping subcommands into sections using the @cli_section annotation.
    """
    def __init__(self, group_callback, *args, **kwargs):
        self.group_callback = group_callback
        self.has_invoked_group_callback = False
        super().__init__(*args, **kwargs)

    def invoke(self, ctx):
        self.invoke_group_callback(ctx)
        return super().invoke(ctx)

    def get_help(self, ctx):
        """
        Run group callback before invoking get_help()
        """
        # TODO: This kinda sucks, because other parameters may not available yet and are ignored.
        self.invoke_group_callback(ctx)
        return super().get_help(ctx)

    def format_commands(self, ctx, formatter):
        """
        Like multi command's version, but also grouping commands into subsections, if available.
        """
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            # What is this, the tool lied about a command.  Ignore it
            if cmd is None:
                continue
            if cmd.hidden:
                continue

            commands.append((subcommand, cmd))

        # allow for 3 times the default spacing
        if len(commands):
            limit = formatter.width - 6 - max(len(cmd[0]) for cmd in commands)

            sections = {}
            for subcommand, cmd in commands:
                help = cmd.get_short_help_str(limit)
                if not hasattr(cmd, 'riptide_section'):
                    cmd.riptide_section = 'General'
                if cmd.riptide_section not in sections:
                    sections[cmd.riptide_section] = []
                sections[cmd.riptide_section].append((subcommand, help))

            for section_name, rows in sections.items():
                with formatter.section(section_name + ' Commands'):
                    # Make sure the spacing between comamnd and help text is always the same, across all sections.
                    spacing = (formatter.width - 6 - max(len(cmd[0]) for cmd in rows)) - limit + 2
                    formatter.write_dl(rows, col_spacing=spacing)

    def invoke_group_callback(self, ctx):
        if not self.has_invoked_group_callback:
            self.has_invoked_group_callback = True
            ctx.invoke(self.group_callback, ctx, **ctx.params)
