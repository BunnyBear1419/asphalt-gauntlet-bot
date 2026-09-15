from discord.ext import commands
from discord import app_commands
from ..core.core import *

class SystemCog(commands.Cog):

    @commands.command(name='forcesync')
    @commands.has_permissions(administrator=True)
    async def force_command(self, ctx: commands.Context, full_cleanup: str=None):
        """Prefix recovery command. Use !forcesync to re-sync slash commands, or
        !forcesync full to also clear stale per-server command overrides."""
        try:
            synced = await bot.sync_application_commands()
            description_extra = ''
            cleaned_count = None
            if full_cleanup and full_cleanup.lower() in ('full', 'cleanup', 'true'):
                cleaned_count = await bot.sync_guild_application_commands(force_fetch=True)
                if not bot._guild_cleanup_failed:
                    await bot.db.settings.update_one({'_id': 'global_meta'}, {'$set': {'guild_overrides_cleaned': True, 'command_architecture_version': COMMAND_ARCHITECTURE_VERSION}}, upsert=True)
                    description_extra = f'\n**Server overrides cleared and verified:** `{cleaned_count}`'
                else:
                    description_extra = '\n⚠️ Some server overrides could not be verified; cleanup was not marked complete.'
            embed = discord.Embed(title='⚡ FORCE SYNC COMPLETE', description=f'Slash-command tree was manually synchronized with Discord.\n\n**Commands synced:** `{len(synced)}`\n**Requested by:** {ctx.author.mention}{description_extra}', color=ASPHALT_VICTORY_COLOR)
            await ctx.send(embed=embed)
            logging.info('Manual !forcesync completed by %s; %d commands synchronized.', ctx.author, len(synced))
            if ctx.guild:
                await dispatch_audit_log(str(ctx.guild.id), '🛡️ Admin Action — Force Sync', f'**Actor:** {ctx.author.mention} (`{ctx.author.id}`)\n**Channel:** <#{ctx.channel.id}>\nSynchronized {len(synced)} global application commands.' + (f' Cleared {cleaned_count} server override(s).' if cleaned_count is not None else ''), color=ASPHALT_ADMIN_COLOR)
        except Exception as exc:
            logging.exception('Manual !forcesync failed')
            await ctx.send(f'❌ Force sync failed: `{exc}`')

    async def cog_load(self):
        self.force_command.error(self.force_command_error)

    async def force_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('❌ Access Denied: Administrator permission is required.')
        else:
            logging.exception('!forcesync command error', exc_info=error)
            await ctx.send(f'❌ Force sync command error: `{error}`')

async def setup(bot):
    await bot.add_cog(SystemCog(bot))
