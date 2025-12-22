from __future__ import annotations

import typing
import traceback

import discord
from discord.ui.select import BaseSelect

class BaseView(discord.ui.View):
    interaction: discord.Interaction | None = None
    message: discord.Message | None = None

    def __init__(self, user: discord.User | discord.Member, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        # We set the user who invoked the command as the user who can interact with the view
        self.user = user

    # make sure that the view only processes interactions from the user who invoked the command
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "You cannot interact with this view.", ephemeral=True
            )
            return False
        # update the interaction attribute when a valid interaction is received
        self.interaction = interaction
        return True

    # to handle errors we first notify the user that an error has occurred and then disable all components

    def _disable_all(self) -> None:
        # disable all components
        # so components that can be disabled are buttons and select menus
        for item in self.children:
            if isinstance(item, discord.ui.Button) or isinstance(item, BaseSelect):
                item.disabled = True

    # after disabling all components we need to edit the message with the new view
    # now when editing the message there are two scenarios:
    # 1. the view was never interacted with i.e in case of plain timeout here message attribute will come in handy
    # 2. the view was interacted with and the interaction was processed and we have the latest interaction stored in the interaction attribute
    async def _edit(self, **kwargs: typing.Any) -> None:
        if self.interaction is None and self.message is not None:
            # if the view was never interacted with and the message attribute is not None, edit the message
            await self.message.edit(**kwargs)
        elif self.interaction is not None:
            try:
                # if not already responded to, respond to the interaction
                await self.interaction.response.edit_message(**kwargs)
            except discord.InteractionResponded:
                # if already responded to, edit the response
                await self.interaction.edit_original_response(**kwargs)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[BaseView]) -> None:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        message = f"An error occurred while processing the interaction for {str(item)}:\n```py\n{tb}\n```"
        # disable all components
        self._disable_all()
        # edit the message with the error message
        await self._edit(content=message, view=self)
        # stop the view
        self.stop()

    async def on_timeout(self) -> None:
        # disable all components
        self._disable_all()
        # edit the message with the new view
        await self._edit(view=self)

class AutoPostView(BaseView):
    def __init__(self, user: discord.User | discord.Member, timeout: float = 60.0):
        super().__init__(user=user, timeout=timeout)
        
        self.confirmed: bool | None = None
        self.characters: str | None = None
        self.selected_forum: discord.ForumChannel | None = None

    async def _turn_off_view(self, interaction: discord.Interaction, *, confirmed: bool):
        self.confirmed = confirmed
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _confirm_check(self, interaction: discord.Interaction):
        if self.characters == "":
            await interaction.response.send_message(
                "Please fill out the characters. Use commas as a delimiter for multiple characters.", ephemeral=True
            )
        elif not self.selected_forum:
            await interaction.response.send_message(
                "Please select a forum.", ephemeral=True
            )
        else:
            await self._turn_off_view(interaction, confirmed=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Edit forum channel", channel_types=[discord.ChannelType.forum], min_values=1, max_values=1,)
    async def forum_select(self, interaction: discord.Interaction, forum_choice: discord.ui.ChannelSelect):
        self.selected_forum = await forum_choice.values[0].fetch()

        embed = interaction.message.embeds[0]
        embed.set_field_at(index=1, name="Forum Overriden", value=self.selected_forum.mention, inline=False)
        await interaction.response.edit_message(embed=embed)
    
    @discord.ui.button(label="Edit Characters", style=discord.ButtonStyle.grey, emoji="✏️", custom_id="character_edit")
    async def edit_chara_button(self, interaction: discord.Interaction, button: discord.ui.Button[AutoPostView]) -> None:
        await interaction.response.send_modal(CharaEditModel(self))
    
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, emoji="✅", custom_id="yes")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button[AutoPostView]) -> None:
        await self._confirm_check(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌", custom_id="no")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button[AutoPostView]) -> None:
        await self._turn_off_view(interaction, confirmed=False)

class BaseModal(discord.ui.Modal):
    _interaction: discord.Interaction | None = None

    # sets the interaction attribute when a valid interaction is received i.e modal is submitted
    # via this we can know if the modal was submitted or it timed out
    async def on_submit(self, interaction: discord.Interaction) -> None:
        # if not responded to, defer the interaction
        if not interaction.response.is_done():
            await interaction.response.defer()
        self._interaction = interaction
        self.stop()

    # make sure any errors don't get ignored
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        message = f"An error occurred while processing the interaction:\n```py\n{tb}\n```"
        try:
            await interaction.response.send_message(message, ephemeral=True)
        except discord.InteractionResponded:
            await interaction.edit_original_response(content=message, view=None)
        self.stop()

    @property
    def interaction(self) -> discord.Interaction | None:
        return self._interaction
    
class CharaEditModel(BaseModal, title="Character Edit Modal"):
    characters = discord.ui.TextInput(label="Characters", placeholder="Enter an error message", min_length=1, max_length=100)

    def __init__(self, view: AutoPostView):
        super().__init__()
        self.view = view  # store reference

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view.characters = self.characters.value

        embed = interaction.message.embeds[0]
        embed.set_field_at(index=0, name="Characters Overriden", value=self.characters.value, inline=False)
        await interaction.response.edit_message(embed=embed)