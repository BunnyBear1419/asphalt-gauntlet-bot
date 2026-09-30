"""RSL Discord Ticket Center."""
from __future__ import annotations
import time
import discord
from discord.ext import commands, tasks
from ..core.core import bot

DEFAULT_TYPES = [
 {"key":"general","label":"General Support","emoji":"💬","description":"General RSL help.","priority":"normal","category_id":"","staff_role_ids":[],"questions":["What do you need help with?"]},
 {"key":"match_dispute","label":"Match / Dispute","emoji":"⚖️","description":"Match results or competition disputes.","priority":"high","category_id":"","staff_role_ids":[],"questions":["Match or challenge ID?","What happened?","What evidence can you provide?"]},
 {"key":"report","label":"Report / Integrity","emoji":"🚨","description":"Report suspected rule or integrity issues.","priority":"high","category_id":"","staff_role_ids":[],"questions":["Who or what are you reporting?","What happened?","What evidence do you have?"]},
 {"key":"technical","label":"Technical Issue","emoji":"🛠️","description":"Website, bot, login, or technical problems.","priority":"normal","category_id":"","staff_role_ids":[],"questions":["What is broken?","Where did it happen?","What error did you see?"]},
 {"key":"economy","label":"Economy Issue","emoji":"🪙","description":"Credits, tickets, XP, or reward issues.","priority":"normal","category_id":"","staff_role_ids":[],"questions":["What reward or balance is affected?","What did you expect to happen?"]},
 {"key":"tournament","label":"Tournament Issue","emoji":"🏆","description":"Tournament registration, bracket, or result issues.","priority":"normal","category_id":"","staff_role_ids":[],"questions":["Tournament name or ID?","What happened?","What evidence can you provide?"]},
]

async def settings_for(guild_id):
    row = await bot.db.rsl_ticket_settings.find_one({"_id":str(guild_id)}) or {}
    return {
        "enabled":bool(row.get("enabled",True)),
        "panel_channel_id":str(row.get("panel_channel_id") or ""),
        "panel_message_id":str(row.get("panel_message_id") or ""),
        "transcript_channel_id":str(row.get("transcript_channel_id") or ""),
        "closed_category_id":str(row.get("closed_category_id") or ""),
        "default_category_id":str(row.get("default_category_id") or ""),
        "staff_role_ids":[str(x) for x in row.get("staff_role_ids",[])],
        "max_open_per_user":max(1,min(10,int(row.get("max_open_per_user",2) or 2))),
        "auto_close_hours":max(0,min(720,int(row.get("auto_close_hours",168) or 168))),
        "reminder_hours":max(0,min(168,int(row.get("reminder_hours",24) or 24))),
        "sla_minutes":max(0,min(10080,int(row.get("sla_minutes",60) or 60))),
        "types":(row.get("types") or DEFAULT_TYPES)[:25],
    }

async def log_event(guild_id,ticket_id,event,actor_id,**extra):
    await bot.db.rsl_ticket_events.insert_one({"guild_id":str(guild_id),"ticket_id":str(ticket_id),"event":str(event),"actor_id":str(actor_id),"created_at":time.time(),**extra})

def is_staff(member,role_ids):
    p=getattr(member,"guild_permissions",None)
    return bool(p and (p.administrator or p.manage_guild or p.manage_channels)) or any(str(r.id) in {str(x) for x in role_ids} for r in getattr(member,"roles",[]))

class TicketModal(discord.ui.Modal):
    def __init__(self,cog,ticket_type):
        super().__init__(title=str(ticket_type.get("label") or "RSL Support")[:45])
        self.cog,self.ticket_type=cog,ticket_type
        qs=[str(x)[:45] for x in (ticket_type.get("questions") or [])[:5]] or ["What do you need help with?"]
        for i,q in enumerate(qs):
            self.add_item(discord.ui.TextInput(label=q or f"Question {i+1}",custom_id=f"q{i}",required=False,max_length=1000,style=discord.TextStyle.paragraph))
    async def on_submit(self,interaction):
        if not interaction.guild:
            await interaction.response.send_message("Tickets can only be opened inside the RSL Discord server.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        answers={str(x.custom_id):str(x.value or "").strip() for x in self.children if isinstance(x,discord.ui.TextInput)}
        await interaction.followup.send(await self.cog.open_ticket(interaction.guild,interaction.user,self.ticket_type,answers),ephemeral=True)

class TicketPanelSelect(discord.ui.Select):
    def __init__(self,cog,types):
        self.cog=cog
        self.types={str(x.get("key")):x for x in types}
        opts=[discord.SelectOption(label=str(x.get("label") or x.get("key") or "Support")[:100],value=str(x.get("key") or "general")[:100],emoji=str(x.get("emoji") or "🎫")[:32],description=str(x.get("description") or "")[:100]) for x in types[:25]]
        super().__init__(placeholder="Choose the help you need…",min_values=1,max_values=1,options=opts,custom_id="rsl:tickets:panel")
    async def callback(self,interaction):
        item=self.types.get(str(self.values[0]))
        if not item:
            await interaction.response.send_message("That ticket type is no longer configured.",ephemeral=True); return
        await interaction.response.send_modal(TicketModal(self.cog,item))

class TicketPanelView(discord.ui.View):
    def __init__(self,cog,types):
        super().__init__(timeout=None); self.add_item(TicketPanelSelect(cog,types))

class TicketActions(discord.ui.View):
    def __init__(self,cog,ticket_id,closed=False):
        super().__init__(timeout=None); self.cog=cog; self.ticket_id=str(ticket_id)
        if closed:
            self.add_item(discord.ui.Button(label="Reopen",style=discord.ButtonStyle.success,custom_id=f"rsl:ticket:reopen:{self.ticket_id}"))
        else:
            self.add_item(discord.ui.Button(label="Claim",style=discord.ButtonStyle.primary,custom_id=f"rsl:ticket:claim:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Unclaim",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:unclaim:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Priority",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:priority:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Close",style=discord.ButtonStyle.danger,custom_id=f"rsl:ticket:close:{self.ticket_id}"))
        for child in self.children:
            child.callback=self._dispatch
    async def _dispatch(self,interaction):
        settings=await settings_for(str(interaction.guild.id)) if interaction.guild else {}
        if not interaction.guild or not isinstance(interaction.user,discord.Member) or not is_staff(interaction.user,settings["staff_role_ids"]):
            await interaction.response.send_message("Staff access is required for ticket controls.",ephemeral=True); return
        action=interaction.data.get("custom_id","").split(":")[2]
        if action=="claim":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            result=await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id),"status":{"$ne":"closed"},"claimed_by":None},{"$set":{"claimed_by":str(interaction.user.id),"status":"assigned","updated_at":time.time(),"last_activity_at":time.time()}})
            await log_event(interaction.guild.id,self.ticket_id,"claim",interaction.user.id)
            msg="✅ Ticket claimed." if result.modified_count else "ℹ️ Ticket is already claimed."
        elif action=="unclaim":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            result=await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id),"status":{"$ne":"closed"},"claimed_by":str(interaction.user.id)},{"$set":{"claimed_by":None,"status":"open","updated_at":time.time(),"last_activity_at":time.time()}})
            if result.modified_count: await log_event(interaction.guild.id,self.ticket_id,"unclaim",interaction.user.id)
            msg="Ticket unclaimed." if result.modified_count else "You do not own the ticket claim."
        elif action=="priority":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(interaction.guild.id)})
            order=["low","normal","high","urgent"]; cur=str((row or {}).get("priority","normal")); nxt=order[(order.index(cur)+1)%4] if cur in order else "normal"
            await bot.db.rsl_tickets.update_one({"_id":oid},{"$set":{"priority":nxt,"updated_at":time.time(),"last_activity_at":time.time()}})
            await log_event(interaction.guild.id,self.ticket_id,"priority",interaction.user.id,priority=nxt); msg=f"🔺 Priority changed to **{nxt.title()}**."
        elif action=="close":
            ok=await self.cog._close_ticket(str(interaction.guild.id),self.ticket_id,str(interaction.user.id),"staff")
            msg="🔒 Ticket closed." if ok else "ℹ️ Ticket was already closed."
        else:
            ok=await self.cog.reopen(str(interaction.guild.id),self.ticket_id,str(interaction.user.id))
            msg="🔓 Ticket reopened." if ok else "❌ Ticket could not be reopened."
        await interaction.response.send_message(msg,ephemeral=True)

class TicketCog(commands.Cog):
    def __init__(self,bot_instance):
        self.bot=bot_instance; self.auto_close_loop.start()
    async def cog_load(self): await self.restore_views()
    def cog_unload(self): self.auto_close_loop.cancel()
    async def restore_views(self):
        guilds=set()
        async for row in self.bot.db.rsl_tickets.find({}):
            self.bot.add_view(TicketActions(self,str(row["_id"]),closed=str(row.get("status"))=="closed")); guilds.add(str(row.get("guild_id","")))
        for gid in guilds:
            s=await settings_for(gid)
            if s["panel_channel_id"]: self.bot.add_view(TicketPanelView(self,s["types"]))
    async def open_ticket(self,guild,member,ticket_type,answers):
        s=await settings_for(guild.id)
        if not s["enabled"]: return "🎫 Ticket support is currently disabled."
        count=await self.bot.db.rsl_tickets.count_documents({"guild_id":str(guild.id),"user_id":str(member.id),"status":{"$ne":"closed"}})
        if count>=s["max_open_per_user"]: return f"❌ You already have the maximum of {s['max_open_per_user']} open tickets."
        existing=await self.bot.db.rsl_tickets.find_one({"guild_id":str(guild.id),"user_id":str(member.id),"type":str(ticket_type.get("key")),"status":{"$ne":"closed"}})
        if existing:
            ch=guild.get_channel(int(existing.get("channel_id",0))); return f"❌ You already have an open ticket: {ch.mention if ch else 'ticket record'}."
        role_ids=[str(x) for x in (ticket_type.get("staff_role_ids") or s["staff_role_ids"])]
        ow={guild.default_role:discord.PermissionOverwrite(view_channel=False),member:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)}
        if guild.me: ow[guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,read_message_history=True)
        for rid in role_ids:
            role=guild.get_role(int(rid)) if rid.isdigit() else None
            if role: ow[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)
        cid=str(ticket_type.get("category_id") or s["default_category_id"] or ""); cat=guild.get_channel(int(cid)) if cid.isdigit() else None
        if not isinstance(cat,discord.CategoryChannel): cat=None
        safe="".join(c.lower() if c.isalnum() else "-" for c in str(member.display_name))[:24].strip("-") or "player"
        ch=await guild.create_text_channel(f"ticket-{safe}",category=cat,overwrites=ow,reason="RSL ticket opened")
        now=time.time()
        doc={"guild_id":str(guild.id),"channel_id":str(ch.id),"user_id":str(member.id),"type":str(ticket_type.get("key") or "general"),"type_label":str(ticket_type.get("label") or "General Support"),"priority":str(ticket_type.get("priority") or "normal"),"status":"open","active":True,"category_id":str(cat.id) if cat else "","claimed_by":None,"created_at":now,"updated_at":now,"last_activity_at":now,"first_response_at":None,"closed_at":None,"answers":answers}
        ins=await self.bot.db.rsl_tickets.insert_one(doc); tid=str(ins.inserted_id)
        e=discord.Embed(title=f"🎫 {doc['type_label']}",description=f"Welcome, {member.mention}. Please describe the issue and provide evidence when relevant.",color=discord.Color.blurple())
        e.add_field(name="Priority",value=doc["priority"].title()); e.set_footer(text=f"RSL Ticket • {tid}")
        for k,v in answers.items():
            if v: e.add_field(name=str(k).upper(),value=v[:1024],inline=False)
        await ch.send(content=member.mention,embed=e,view=TicketActions(self,tid))
        await log_event(guild.id,tid,"opened",member.id,type=doc["type"])
        return f"✅ Your ticket is open: {ch.mention}"
    async def _close_ticket(self,guild_id,ticket_id,actor_id,reason="closed"):
        from bson import ObjectId
        oid=ObjectId(ticket_id) if ObjectId.is_valid(ticket_id) else ticket_id
        row=await self.bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(guild_id)})
        if not row or row.get("status")=="closed": return False
        now=time.time(); await self.bot.db.rsl_tickets.update_one({"_id":oid},{"$set":{"status":"closed","active":False,"closed_at":now,"updated_at":now,"last_activity_at":now}})
        ch=self.bot.get_channel(int(row.get("channel_id",0)))
        if isinstance(ch,discord.TextChannel):
            s=await settings_for(guild_id); cid=str(s["closed_category_id"]); cat=ch.guild.get_channel(int(cid)) if cid.isdigit() else None
            if isinstance(cat,discord.CategoryChannel):
                try: await ch.edit(category=cat,reason="RSL ticket closed")
                except Exception: pass
            try:
                await ch.set_permissions(ch.guild.default_role,view_channel=False,send_messages=False,reason="RSL ticket closed")
                member=ch.guild.get_member(int(row.get("user_id",0)))
                if member:
                    await ch.set_permissions(member,view_channel=True,send_messages=False,read_message_history=True,reason="RSL ticket closed")
            except Exception: pass
            try: await ch.send("🔒 This ticket has been closed. Staff may reopen it if needed.",view=TicketActions(self,ticket_id,closed=True))
            except Exception: pass
        await log_event(guild_id,ticket_id,"closed",actor_id,reason=reason); return True
    async def reopen(self,guild_id,ticket_id,actor_id):
        from bson import ObjectId
        oid=ObjectId(ticket_id) if ObjectId.is_valid(ticket_id) else ticket_id
        row=await self.bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(guild_id)})
        if not row: return False
        now=time.time(); await self.bot.db.rsl_tickets.update_one({"_id":oid},{"$set":{"status":"open","active":True,"closed_at":None,"updated_at":now,"last_activity_at":now}})
        ch=self.bot.get_channel(int(row.get("channel_id",0)))
        if isinstance(ch,discord.TextChannel):
            try: await ch.send("🔓 This ticket has been reopened.",view=TicketActions(self,ticket_id))
            except Exception: pass
        await log_event(guild_id,ticket_id,"reopened",actor_id); return True
    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        row=await self.bot.db.rsl_tickets.find_one({"guild_id":str(message.guild.id),"channel_id":str(message.channel.id),"status":{"$ne":"closed"}})
        if not row:
            return
        now=time.time()
        update={"last_activity_at":now,"updated_at":now}
        if str(message.author.id) != str(row.get("user_id")) and not row.get("first_response_at"):
            update["first_response_at"]=now
        await self.bot.db.rsl_tickets.update_one({"_id":row["_id"]},{"$set":update})

    @tasks.loop(minutes=15)
    async def auto_close_loop(self):
        now=time.time()
        async for row in self.bot.db.rsl_tickets.find({"status":{"$ne":"closed"}}):
            s=await settings_for(str(row.get("guild_id",""))); hours=s["auto_close_hours"]
            if hours>0 and now-float(row.get("last_activity_at") or row.get("updated_at") or now)>=hours*3600:
                await self._close_ticket(str(row["guild_id"]),str(row["_id"]),"system","inactivity_auto_close")
    @auto_close_loop.before_loop
    async def before_auto_close(self): await self.bot.wait_until_ready()

async def setup(bot_instance): await bot_instance.add_cog(TicketCog(bot_instance))
