"""RSL Discord Ticket Center."""
from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
import aiohttp
from pymongo.errors import DuplicateKeyError
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

def _localized_type(ticket_type, locale):
    loc=str(locale or "en-US").replace("_","-").lower()
    base=loc.split("-")[0]
    translations=ticket_type.get("translations") or {}
    data=translations.get(loc) or translations.get(base) or {}
    if not isinstance(data,dict): return ticket_type
    out=dict(ticket_type)
    for key in ("label","description","questions"):
        if key in data: out[key]=data[key]
    return out


async def _safe_webhook_url(url):
    """Allow only HTTPS webhook targets on publicly routable hosts."""
    value=str(url or "").strip()
    if not value or len(value)>2048: return None
    try:
        parsed=aiohttp.client_reqrep.URL(value)
        if parsed.scheme!="https" or parsed.username or parsed.password or parsed.port not in (None,443):
            return None
        host=parsed.host
        if not host: return None
        infos=await __import__("asyncio").get_running_loop().run_in_executor(None, socket.getaddrinfo, host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for info in infos:
            addr=info[4][0]
            ip=ipaddress.ip_address(addr)
            if not ip.is_global: return None
        return value
    except Exception:
        return None

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
        "auto_assign_enabled":bool(row.get("auto_assign_enabled",False)),
        "support_hours_enabled":bool(row.get("support_hours_enabled",False)),
        "support_hours_timezone":str(row.get("support_hours_timezone") or "UTC")[:64],
        "support_hours_start":str(row.get("support_hours_start") or "09:00")[:5],
        "support_hours_end":str(row.get("support_hours_end") or "17:00")[:5],
        "support_hours_days":[int(x) for x in row.get("support_hours_days",[0,1,2,3,4,5,6]) if str(x).isdigit() and 0<=int(x)<=6][:7],
        "webhook_url":str(row.get("webhook_url") or ""),
        "notify_player_dm":bool(row.get("notify_player_dm",True)),
        "types":(row.get("types") or DEFAULT_TYPES)[:25],
        "tags":[str(x)[:32] for x in (row.get("tags") or ["billing","bug","dispute","evidence","follow-up","priority","resolved","technical"])[:30]],
        "canned_responses":(row.get("canned_responses") or [{"key":"welcome","label":"Welcome","text":"Thanks for contacting RSL Support. A staff member will assist you shortly."},{"key":"evidence","label":"Evidence Request","text":"Please provide the relevant screenshots, video, match ID, and any other evidence available."},{"key":"resolved","label":"Resolved","text":"This issue appears to be resolved. If you still need help, reply here before the ticket is closed."}])[:30],
    }

async def notify_ticket(self,ticket_id,row,event,message=None,staff=False,player=False,webhook_payload=None):
    now=time.time()
    guild_id=str(row.get("guild_id") or "")
    destinations=[]
    if staff: destinations.append(("staff",message or "RSL ticket update."))
    if player: destinations.append(("player",message or "RSL ticket update."))
    if webhook_payload: destinations.append(("webhook",webhook_payload))
    delivered_any=False
    for destination,payload in destinations:
        key=f"{ticket_id}:{event}:{destination}"
        claimed=False
        try:
            await self.bot.db.rsl_ticket_notifications.insert_one({"event_key":key,"guild_id":guild_id,"ticket_id":str(ticket_id),"event":str(event),"destination":destination,"created_at":now,"status":"sending","attempts":1})
            claimed=True
        except DuplicateKeyError:
            existing=await self.bot.db.rsl_ticket_notifications.find_one({"event_key":key})
            if not existing: continue
            status=str(existing.get("status") or "")
            if status=="delivered": continue
            if status=="failed":
                result=await self.bot.db.rsl_ticket_notifications.update_one({"event_key":key,"guild_id":guild_id,"status":"failed"},{"$set":{"status":"sending","created_at":now,"retry_at":now},"$inc":{"attempts":1}})
                claimed=bool(result.modified_count)
            elif status=="sending" and now-float(existing.get("created_at") or now)>=300:
                result=await self.bot.db.rsl_ticket_notifications.update_one({"event_key":key,"guild_id":guild_id,"status":"sending","created_at":existing.get("created_at")},{"$set":{"status":"sending","created_at":now,"retry_at":now},"$inc":{"attempts":1}})
                claimed=bool(result.modified_count)
        if not claimed: continue
        delivered=False
        try:
            if destination=="staff":
                ch=self.bot.get_channel(int(row.get("channel_id",0)))
                if isinstance(ch,discord.TextChannel):
                    await ch.send(str(payload))
                    delivered=True
            elif destination=="player":
                user=self.bot.get_user(int(row.get("user_id",0))) or await self.bot.fetch_user(int(row.get("user_id",0)))
                await user.send(str(payload))
                delivered=True
            else:
                settings=await settings_for(str(row.get("guild_id","")))
                webhook=await _safe_webhook_url(settings.get("webhook_url"))
                if webhook:
                    timeout=aiohttp.ClientTimeout(total=5)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(webhook,json=payload,allow_redirects=False) as response:
                            delivered=200 <= int(response.status) < 300
        except Exception:
            delivered=False
        await self.bot.db.rsl_ticket_notifications.update_one({"event_key":key,"guild_id":guild_id},{"$set":{"status":"delivered" if delivered else "failed","delivered_at":time.time() if delivered else None}})
        delivered_any=delivered_any or delivered
    return delivered_any

async def choose_auto_assignee(guild,ticket_type,settings,db):
    role_ids=[str(x) for x in (ticket_type.get("staff_role_ids") or settings["staff_role_ids"])]
    candidates={}
    for rid in role_ids:
        role=guild.get_role(int(rid)) if rid.isdigit() else None
        if role:
            for m in role.members:
                if not m.bot and not getattr(m,"pending",False) and is_staff(m,role_ids):
                    candidates[m.id]=m
    if not candidates: return None
    counts={str(m.id):await db.rsl_tickets.count_documents({"guild_id":str(guild.id),"claimed_by":str(m.id),"status":{"$ne":"closed"},"active":True}) for m in candidates.values()}
    return min(candidates.values(),key=lambda m:(counts.get(str(m.id),0),str(m.id)))

async def log_event(guild_id,ticket_id,event,actor_id,**extra):
    await bot.db.rsl_ticket_events.insert_one({"guild_id":str(guild_id),"ticket_id":str(ticket_id),"event":str(event),"actor_id":str(actor_id),"created_at":time.time(),**extra})

async def ticket_staff_role_ids(ticket_type_key, settings):
    # Resolve the configured type from the current guild settings; empty type roles inherit global staff roles.
    for item in settings.get("types",[]):
        if str(item.get("key"))==str(ticket_type_key):
            roles=[str(x) for x in (item.get("staff_role_ids") or [])]
            return roles or [str(x) for x in settings.get("staff_role_ids",[])]
    return [str(x) for x in settings.get("staff_role_ids",[])]

def is_staff(member,role_ids):
    p=getattr(member,"guild_permissions",None)
    return bool(p and (p.administrator or p.manage_guild or p.manage_channels)) or any(str(r.id) in {str(x) for x in role_ids} for r in getattr(member,"roles",[]))

class TicketModal(discord.ui.Modal):
    def __init__(self,cog,ticket_type,locale="en-US"):
        ticket_type=_localized_type(ticket_type,locale)
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
        await interaction.response.send_modal(TicketModal(self.cog,item,getattr(interaction,"locale","en-US")))

class TicketPanelView(discord.ui.View):
    def __init__(self,cog,types):
        super().__init__(timeout=None); self.add_item(TicketPanelSelect(cog,types))

class TicketActions(discord.ui.View):
    def __init__(self,cog,ticket_id,closed=False,locked=False):
        super().__init__(timeout=None); self.cog=cog; self.ticket_id=str(ticket_id); self.locked=bool(locked)
        if closed:
            self.add_item(discord.ui.Button(label="Reopen",style=discord.ButtonStyle.success,custom_id=f"rsl:ticket:reopen:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Rating",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:rating:{self.ticket_id}"))
        else:
            self.add_item(discord.ui.Button(label="Claim",style=discord.ButtonStyle.primary,custom_id=f"rsl:ticket:claim:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Unclaim",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:unclaim:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Priority",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:priority:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Close",style=discord.ButtonStyle.danger,custom_id=f"rsl:ticket:close:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Unlock" if self.locked else "Lock",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:lock:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Note",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:note:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Assign",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:assign:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Transfer",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:transfer:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Members",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:members:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Tag",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:tag:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Reply",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:reply:{self.ticket_id}"))
            self.add_item(discord.ui.Button(label="Rating",style=discord.ButtonStyle.secondary,custom_id=f"rsl:ticket:rating:{self.ticket_id}"))
        for child in self.children:
            child.callback=self._dispatch
    async def _dispatch(self,interaction):
        action=interaction.data.get("custom_id","").split(":")[2]
        settings=await settings_for(str(interaction.guild.id)) if interaction.guild else {}
        ticket_row=None
        ticket_roles=settings.get("staff_role_ids",[])
        if interaction.guild and action!="rating":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            ticket_row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(interaction.guild.id)})
            ticket_roles=await ticket_staff_role_ids((ticket_row or {}).get("type"),settings)
        if action!="rating" and (not interaction.guild or not isinstance(interaction.user,discord.Member) or not is_staff(interaction.user,ticket_roles)):
            await interaction.response.send_message("Staff access is required for this ticket type.",ephemeral=True); return
        if action=="claim":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            result=await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id),"status":{"$ne":"closed"},"claimed_by":None},{"$set":{"claimed_by":str(interaction.user.id),"status":"assigned","updated_at":time.time(),"last_activity_at":time.time()}})
            if result.modified_count: await log_event(interaction.guild.id,self.ticket_id,"claim",interaction.user.id)
            msg="✅ Ticket claimed." if result.modified_count else "ℹ️ Ticket is already claimed."
        elif action=="unclaim":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            result=await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id),"status":{"$ne":"closed"},"claimed_by":str(interaction.user.id)},{"$set":{"claimed_by":None,"status":"open","updated_at":time.time(),"last_activity_at":time.time()}})
            if result.modified_count: await log_event(interaction.guild.id,self.ticket_id,"unclaim",interaction.user.id)
            msg="Ticket unclaimed." if result.modified_count else "You do not own the ticket claim."
        elif action=="lock":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(interaction.guild.id)})
            ch=interaction.guild.get_channel(int((row or {}).get("channel_id",0)))
            if isinstance(ch,discord.TextChannel):
                member=interaction.guild.get_member(int((row or {}).get("user_id",0)))
                locked=not bool((row or {}).get("locked",False))
                if member:
                    await ch.set_permissions(member,view_channel=True,send_messages=not locked,read_message_history=True,attach_files=not locked,reason="RSL ticket lock toggle")
                result=await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id),"status":{"$in":["open","assigned","investigating","awaiting_player","escalated"]},"locked":not locked},{"$set":{"locked":locked,"updated_at":time.time(),"last_activity_at":time.time()}})
                if result.modified_count: await log_event(interaction.guild.id,self.ticket_id,"locked" if locked else "unlocked",interaction.user.id)
                msg=("🔒 Ticket locked." if locked else "🔓 Ticket unlocked.") if result.modified_count else "ℹ️ Ticket state changed before this action completed."
            else: msg="❌ Ticket channel not found."
        elif action=="assign":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(interaction.guild.id)}) or {}
            current=str(row.get("claimed_by") or "")
            target=str(interaction.user.id)
            new_claim=None if current==target else target
            new_status="open" if new_claim is None else "assigned"
            result=await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id),"status":{"$in":["open","assigned","investigating","awaiting_player","escalated"]}},{"$set":{"claimed_by":new_claim,"status":new_status,"updated_at":time.time(),"last_activity_at":time.time()}})
            if result.modified_count: await log_event(interaction.guild.id,self.ticket_id,"unassigned" if new_claim is None else "assigned",interaction.user.id,assigned_to=new_claim)
            msg=("Ticket unassigned." if new_claim is None else "Ticket assigned to you.") if result.modified_count else "ℹ️ Ticket state changed before this action completed."
        elif action=="transfer":
            class TransferModal(discord.ui.Modal):
                staff_id=discord.ui.TextInput(label="Staff Discord user ID",placeholder="123456789012345678",max_length=25,required=True)
                async def on_submit(modal_self,modal_interaction):
                    from bson import ObjectId
                    oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
                    try: uid=int(str(modal_self.staff_id.value).strip())
                    except ValueError:
                        await modal_interaction.response.send_message("❌ Invalid Discord user ID.",ephemeral=True); return
                    target=modal_interaction.guild.get_member(uid)
                    if not isinstance(target,discord.Member) or not is_staff(target,ticket_roles):
                        await modal_interaction.response.send_message("❌ That member is not configured as RSL staff.",ephemeral=True); return
                    now=time.time()
                    await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(modal_interaction.guild.id),"status":{"$ne":"closed"}},{"$set":{"claimed_by":str(target.id),"status":"assigned","updated_at":now,"last_activity_at":now}})
                    await log_event(modal_interaction.guild.id,self.ticket_id,"transferred",modal_interaction.user.id,assigned_to=str(target.id))
                    await modal_interaction.response.send_message(f"🔄 Ticket transferred to <@{target.id}>.",ephemeral=True)
            await interaction.response.send_modal(TransferModal(title="Transfer RSL Ticket")); return
        elif action=="members":
            class MemberModal(discord.ui.Modal):
                user_id=discord.ui.TextInput(label="Discord user ID",placeholder="123456789012345678",max_length=25,required=True)
                async def on_submit(modal_self,modal_interaction):
                    from bson import ObjectId
                    oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
                    try: uid=int(str(modal_self.user_id.value).strip())
                    except ValueError:
                        await modal_interaction.response.send_message("❌ Invalid Discord user ID.",ephemeral=True); return
                    row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(modal_interaction.guild.id)}) or {}
                    ch=modal_interaction.guild.get_channel(int(row.get("channel_id",0)))
                    m=modal_interaction.guild.get_member(uid)
                    if not isinstance(ch,discord.TextChannel) or int(ch.guild.id) != int(modal_interaction.guild.id) or not m:
                        await modal_interaction.response.send_message("❌ Member or ticket channel not found in this server.",ephemeral=True); return
                    if m.bot:
                        await modal_interaction.response.send_message("❌ Bots cannot be added as ticket participants.",ephemeral=True); return
                    members=[str(x) for x in row.get("member_ids",[]) if str(x)!=str(uid)]
                    if str(uid) in [str(x) for x in row.get("member_ids",[])]:
                        await ch.set_permissions(m,overwrite=None,reason="RSL ticket member removed")
                        await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id)},{"$set":{"member_ids":members,"updated_at":time.time()}})
                        await log_event(modal_interaction.guild.id,self.ticket_id,"member_removed",modal_interaction.user.id,member_id=str(uid))
                        msg="👤 Member removed."
                    else:
                        members.append(str(uid))
                        await ch.set_permissions(m,view_channel=True,send_messages=True,read_message_history=True,attach_files=True,reason="RSL ticket member added")
                        await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id)},{"$set":{"member_ids":members,"updated_at":time.time()}})
                        await log_event(modal_interaction.guild.id,self.ticket_id,"member_added",modal_interaction.user.id,member_id=str(uid))
                        msg="👤 Member added."
                    await modal_interaction.response.send_message(msg,ephemeral=True)
            await interaction.response.send_modal(MemberModal(title="RSL Ticket Member"))
            return
        elif action=="tag":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            s=await settings_for(str(interaction.guild.id)); tags=s.get("tags",[])
            row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(interaction.guild.id)}) or {}; current=[str(x) for x in row.get("tags",[])]
            nxt=tags[(tags.index(current[0])+1)%len(tags)] if current and current[0] in tags else (tags[0] if tags else "general")
            if nxt in current: current.remove(nxt)
            else: current.append(nxt)
            await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id)},{"$set":{"tags":current,"updated_at":time.time()}})
            await log_event(interaction.guild.id,self.ticket_id,"tag_updated",interaction.user.id,tags=current)
            msg="🏷️ Tags: "+(", ".join(current) if current else "none")
        elif action=="reply":
            s=await settings_for(str(interaction.guild.id)); responses=s.get("canned_responses",[])
            class ReplyModal(discord.ui.Modal):
                key=discord.ui.TextInput(label="Canned response key",placeholder="welcome / evidence / resolved",max_length=64,required=True)
                async def on_submit(modal_self,modal_interaction):
                    item=next((x for x in responses if str(x.get("key"))==str(modal_self.key.value).strip()),None)
                    if not item:
                        await modal_interaction.response.send_message("❌ Canned response not found.",ephemeral=True); return
                    ch=modal_interaction.channel
                    if isinstance(ch,discord.TextChannel): await ch.send(str(item.get("text") or "")[:1900])
                    await log_event(modal_interaction.guild.id,self.ticket_id,"canned_response",modal_interaction.user.id,response_key=str(item.get("key")))
                    await modal_interaction.response.send_message("💬 Canned response sent.",ephemeral=True)
            await interaction.response.send_modal(ReplyModal(title="RSL Canned Response")); return
        elif action=="rating":
            from bson import ObjectId
            oid=ObjectId(self.ticket_id) if ObjectId.is_valid(self.ticket_id) else self.ticket_id
            row=await bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(interaction.guild.id)}) or {}
            if str(row.get("user_id"))!=str(interaction.user.id):
                await interaction.response.send_message("ℹ️ Ratings are submitted by the ticket owner.",ephemeral=True); return
            if isinstance(row.get("rating"),dict) and row.get("rating",{}).get("score"):
                await interaction.response.send_message("ℹ️ You have already rated this ticket.",ephemeral=True); return
            class RatingModal(discord.ui.Modal):
                score=discord.ui.TextInput(label="Rating (1-5)",placeholder="5",max_length=1,required=True)
                comment=discord.ui.TextInput(label="Optional feedback",style=discord.TextStyle.paragraph,max_length=1000,required=False)
                async def on_submit(modal_self,modal_interaction):
                    try: score_value=int(str(modal_self.score.value).strip())
                    except ValueError: score_value=0
                    if score_value<1 or score_value>5:
                        await modal_interaction.response.send_message("❌ Rating must be 1 through 5.",ephemeral=True); return
                    await bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(interaction.guild.id)},{"$set":{"rating":{"score":score_value,"comment":str(modal_self.comment.value or ""),"created_at":time.time()},"updated_at":time.time()}})
                    await log_event(modal_interaction.guild.id,self.ticket_id,"rating_submitted",modal_interaction.user.id,score=score_value)
                    await modal_interaction.response.send_message("⭐ Thanks for rating RSL Support.",ephemeral=True)
            await interaction.response.send_modal(RatingModal(title="RSL Support Rating")); return
        elif action=="note":
            class StaffNoteModal(discord.ui.Modal):
                note=discord.ui.TextInput(label="Private staff note",style=discord.TextStyle.paragraph,max_length=2000,required=True)
                async def on_submit(modal_self,modal_interaction):
                    await bot.db.rsl_ticket_events.insert_one({"guild_id":str(modal_interaction.guild.id),"ticket_id":self.ticket_id,"event":"staff_note","actor_id":str(modal_interaction.user.id),"note":str(modal_self.note.value),"created_at":time.time()})
                    await modal_interaction.response.send_message("📝 Private staff note saved.",ephemeral=True)
            await interaction.response.send_modal(StaffNoteModal(title="RSL Staff Note"))
            return
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
        elif action=="reopen":
            ok=await self.cog.reopen(str(interaction.guild.id),self.ticket_id,str(interaction.user.id))
            msg="🔓 Ticket reopened." if ok else "❌ Ticket could not be reopened."
        else:
            await interaction.response.send_message("❌ Unknown ticket action.",ephemeral=True); return
        await interaction.response.send_message(msg,ephemeral=True)

class TicketCog(commands.Cog):
    def __init__(self,bot_instance):
        self.bot=bot_instance; self.auto_close_loop.start()
    async def cog_load(self):
        try:
            await self.bot.db.rsl_ticket_notifications.create_index("event_key", unique=True, name="uniq_rsl_ticket_notification_event")
            await self.bot.db.rsl_ticket_notifications.create_index([("guild_id",1),("status",1),("retry_at",1)], name="idx_rsl_ticket_notification_retry")
        except Exception:
            pass
        await self.reconcile_provisioning()
        await self.reconcile_missing_channels()
        await self.restore_views()
    def cog_unload(self): self.auto_close_loop.cancel()
    async def restore_views(self):
        guilds=set()
        async for row in self.bot.db.rsl_tickets.find({"channel_id":{"$ne":""}}):
            guild_id=str(row.get("guild_id") or "")
            channel_id=str(row.get("channel_id") or "")
            guild=self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
            channel=guild.get_channel(int(channel_id)) if guild and channel_id.isdigit() else None
            if not isinstance(channel,discord.TextChannel):
                continue
            self.bot.add_view(TicketActions(self,str(row["_id"]),closed=str(row.get("status"))=="closed",locked=bool(row.get("locked",False))))
            guilds.add(guild_id)
        for gid in guilds:
            s=await settings_for(gid)
            if s["panel_channel_id"]:
                self.bot.add_view(TicketPanelView(self,s["types"]))
    async def open_ticket(self,guild,member,ticket_type,answers):
        s=await settings_for(guild.id)
        if not s["enabled"]: return "🎫 Ticket support is currently disabled."
        key=str(ticket_type.get("key") or "general")
        existing=await self.bot.db.rsl_tickets.find_one({"guild_id":str(guild.id),"user_id":str(member.id),"type":key,"active":True})
        if existing:
            ch=guild.get_channel(int(existing.get("channel_id",0))) if str(existing.get("channel_id","")).isdigit() else None
            return f"❌ You already have an open ticket: {ch.mention if ch else 'ticket record'}."
        count=await self.bot.db.rsl_tickets.count_documents({"guild_id":str(guild.id),"user_id":str(member.id),"status":{"$ne":"closed"},"active":True})
        if count>=s["max_open_per_user"]: return f"❌ You already have the maximum of {s['max_open_per_user']} open tickets."
        recent_cutoff=time.time()-300
        recent=await self.bot.db.rsl_tickets.count_documents({"guild_id":str(guild.id),"user_id":str(member.id),"created_at":{"$gte":recent_cutoff}})
        if recent>=2: return "⏳ Please wait a few minutes before opening another ticket."
        role_ids=[str(x) for x in (ticket_type.get("staff_role_ids") or s["staff_role_ids"])]
        ow={guild.default_role:discord.PermissionOverwrite(view_channel=False),member:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)}
        if guild.me: ow[guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,read_message_history=True)
        for rid in role_ids:
            role=guild.get_role(int(rid)) if rid.isdigit() else None
            if role: ow[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)
        cid=str(ticket_type.get("category_id") or s["default_category_id"] or ""); cat=guild.get_channel(int(cid)) if cid.isdigit() else None
        if not isinstance(cat,discord.CategoryChannel): cat=None
        now=time.time()
        doc={"guild_id":str(guild.id),"channel_id":"","user_id":str(member.id),"type":key,"type_label":str(ticket_type.get("label") or "General Support"),"priority":str(ticket_type.get("priority") or "normal"),"status":"provisioning","active":True,"category_id":str(cat.id) if cat else "","claimed_by":None,"created_at":now,"updated_at":now,"last_activity_at":now,"first_response_at":None,"closed_at":None,"reminder_sent_at":None,"sla_alerted_at":None,"locked":False,"member_ids":[],"tags":[],"answers":answers}
        try:
            ins=await self.bot.db.rsl_tickets.insert_one(doc)
        except Exception:
            existing=await self.bot.db.rsl_tickets.find_one({"guild_id":str(guild.id),"user_id":str(member.id),"type":key,"active":True})
            if existing:
                ch=guild.get_channel(int(existing.get("channel_id",0))) if str(existing.get("channel_id","")).isdigit() else None
                return f"❌ A ticket is already being opened: {ch.mention if ch else 'please try again shortly'}."
            return "❌ Ticket creation is temporarily busy. Please try again."
        tid=str(ins.inserted_id)
        try:
            ch=await guild.create_text_channel(f"ticket-{' '.join(str(member.display_name).split())[:24].lower().replace(' ','-') or 'player'}",category=cat,overwrites=ow,reason="RSL ticket opened")
            now=time.time()
            await self.bot.db.rsl_tickets.update_one({"_id":ins.inserted_id,"status":"provisioning"},{"$set":{"channel_id":str(ch.id),"status":"open","updated_at":now,"last_activity_at":now}})
        except Exception:
            await self.bot.db.rsl_tickets.update_one({"_id":ins.inserted_id},{"$set":{"status":"failed","active":False,"recovery_status":"channel_creation_failed","updated_at":time.time()}})
            try:
                await log_event(guild.id,tid,"provisioning_failed",member.id)
            except Exception: pass
            return "❌ Discord could not create the ticket channel. No active ticket was created; please try again."
        doc["_id"]=ins.inserted_id; doc["channel_id"]=str(ch.id); doc["status"]="open"
        auto_assignee=await choose_auto_assignee(guild,ticket_type,s,self.bot.db) if s.get("auto_assign_enabled") else None
        if auto_assignee:
            doc["claimed_by"]=str(auto_assignee.id); doc["status"]="assigned"
            await self.bot.db.rsl_tickets.update_one({"_id":ins.inserted_id,"guild_id":str(guild.id)},{"$set":{"claimed_by":str(auto_assignee.id),"status":"assigned","updated_at":time.time()}})
        e=discord.Embed(title=f"🎫 {doc['type_label']}",description=f"Welcome, {member.mention}. Please describe the issue and provide evidence when relevant.",color=discord.Color.blurple())
        e.add_field(name="Priority",value=doc["priority"].title()); e.set_footer(text=f"RSL Ticket • {tid}")
        for k,v in answers.items():
            if v: e.add_field(name=str(k).upper(),value=v[:1024],inline=False)
        try:
            await ch.send(content=f"{member.mention}"+(f" • Assigned to <@{auto_assignee.id}>" if auto_assignee else ""),embed=e,view=TicketActions(self,tid))
        except Exception:
            await self.bot.db.rsl_tickets.update_one({"_id":ins.inserted_id,"guild_id":str(guild.id)},{"$set":{"status":"orphaned","active":False,"recovery_status":"opening_message_failed","updated_at":time.time()}})
            return "❌ The ticket channel was created but could not be initialized. Staff can recover it from Ticket Center."
        await log_event(guild.id,tid,"opened",member.id,type=doc["type"])
        if auto_assignee: await log_event(guild.id,tid,"auto_assigned",auto_assignee.id,assigned_by="system")
        await self.bot.db.rsl_ticket_events.insert_one({"guild_id":str(guild.id),"ticket_id":tid,"event":"intake_snapshot","actor_id":str(member.id),"created_at":time.time(),"answers":answers,"locale":str(getattr(member,"locale","en-US"))})
        await self.notify_ticket(tid,doc,"opened",webhook_payload={"event":"ticket.opened","guild_id":str(guild.id),"ticket_id":tid,"type":doc["type"],"user_id":str(member.id),"priority":doc["priority"]})
        return f"✅ Your ticket is open: {ch.mention}"
    async def reconcile_ticket_permissions(self, guild, row, closed=False, locked=False):
        ch=guild.get_channel(int(row.get("channel_id",0)))
        if not isinstance(ch,discord.TextChannel): return False
        owner=guild.get_member(int(row.get("user_id",0)))
        member_ids={str(x) for x in row.get("member_ids",[])}
        staff_ids={str(x) for x in row.get("staff_role_ids",[])}
        if not staff_ids:
            s=await settings_for(guild.id); staff_ids={str(x) for x in s.get("staff_role_ids",[])}
        # Remove explicit user overwrites for ticket members no longer authorized.
        for target in list(ch.overwrites.keys()):
            if isinstance(target,discord.Member) and str(target.id) not in member_ids and target != owner and not target.bot:
                try: await ch.set_permissions(target,overwrite=None,reason="RSL ticket permission reconciliation")
                except Exception: pass
        if owner:
            await ch.set_permissions(owner,view_channel=True,send_messages=not closed and not locked,read_message_history=True,attach_files=not closed and not locked,reason="RSL ticket permission reconciliation")
        for uid in member_ids:
            m=guild.get_member(int(uid)) if uid.isdigit() else None
            if m:
                await ch.set_permissions(m,view_channel=True,send_messages=not closed and not locked,read_message_history=True,attach_files=not closed and not locked,reason="RSL ticket permission reconciliation")
        await ch.set_permissions(guild.default_role,view_channel=False,send_messages=False,reason="RSL ticket permission reconciliation")
        settings=await settings_for(guild.id)
        type_roles=[]
        for item in settings.get("types",[]):
            if str(item.get("key"))==str(row.get("type")):
                type_roles=[str(x) for x in (item.get("staff_role_ids") or [])]
                break
        role_ids=type_roles or [str(x) for x in settings.get("staff_role_ids",[])]
        for rid in role_ids:
            role=guild.get_role(int(rid)) if rid.isdigit() else None
            if role:
                await ch.set_permissions(role,view_channel=True,send_messages=True,read_message_history=True,attach_files=True,reason="RSL ticket permission reconciliation")
        return True

    async def _close_ticket(self,guild_id,ticket_id,actor_id,reason="closed"):
        from bson import ObjectId
        oid=ObjectId(ticket_id) if ObjectId.is_valid(ticket_id) else ticket_id
        now=time.time()
        result=await self.bot.db.rsl_tickets.update_one(
            {"_id":oid,"guild_id":str(guild_id),"status":{"$in":["open","assigned","investigating","awaiting_player","escalated"]},"active":True},
            {"$set":{"status":"closed","active":False,"closed_at":now,"updated_at":now,"last_activity_at":now}}
        )
        if not result.modified_count: return False
        row=await self.bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(guild_id)})
        if not row: return False
        ch=self.bot.get_channel(int(row.get("channel_id",0)))
        if isinstance(ch,discord.TextChannel):
            s=await settings_for(guild_id); cid=str(s["closed_category_id"]); cat=ch.guild.get_channel(int(cid)) if cid.isdigit() else None
            if isinstance(cat,discord.CategoryChannel):
                try: await ch.edit(category=cat,reason="RSL ticket closed")
                except Exception: pass
            try:
                await self.reconcile_ticket_permissions(ch.guild,row,closed=True,locked=False)
            except Exception: pass
            try: await ch.send("🔒 This ticket has been closed. Staff may reopen it if needed.",view=TicketActions(self,ticket_id,closed=True))
            except Exception: pass
        await log_event(guild_id,ticket_id,"closed",actor_id,reason=reason)
        s=await settings_for(guild_id)
        await self.notify_ticket(ticket_id,row,"closed",message="🔒 Your RSL support ticket has been closed. Staff may reopen it if needed.",player=s.get("notify_player_dm",True),webhook_payload={"event":"ticket.closed","guild_id":str(guild_id),"ticket_id":str(ticket_id),"reason":reason})
        return True
    async def recover(self,guild_id,ticket_id,actor_id):
        from bson import ObjectId
        oid=ObjectId(ticket_id) if ObjectId.is_valid(ticket_id) else ticket_id
        result=await self.bot.db.rsl_tickets.update_one(
            {"_id":oid,"guild_id":str(guild_id),"status":{"$in":["orphaned","failed"]},"active":False},
            {"$set":{"status":"recovering","recovery_status":"recovery_in_progress","updated_at":time.time()}}
        )
        if not result.modified_count: return False
        row=await self.bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(guild_id),"status":"recovering"})
        if not row: return False
        guild=self.bot.get_guild(int(guild_id))
        member=guild.get_member(int(row.get("user_id",0))) if guild else None
        if not guild or not member:
            await self.bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(guild_id),"status":"recovering"},{"$set":{"status":"failed","active":False,"recovery_status":"recovery_member_unavailable","updated_at":time.time()}})
            return False
        s=await settings_for(guild_id)
        types={str(x.get("key")):x for x in s["types"]}
        ticket_type=types.get(str(row.get("type")),{"staff_role_ids":s["staff_role_ids"],"category_id":row.get("category_id",""),"label":row.get("type_label","RSL Support"),"priority":row.get("priority","normal")})
        role_ids=[str(x) for x in (ticket_type.get("staff_role_ids") or s["staff_role_ids"])]
        ow={guild.default_role:discord.PermissionOverwrite(view_channel=False),member:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)}
        if guild.me: ow[guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,read_message_history=True)
        for rid in role_ids:
            role=guild.get_role(int(rid)) if rid.isdigit() else None
            if role: ow[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)
        cid=str(row.get("category_id") or ticket_type.get("category_id") or s["default_category_id"] or "")
        cat=guild.get_channel(int(cid)) if cid.isdigit() else None
        if not isinstance(cat,discord.CategoryChannel): cat=None
        safe="".join(x.lower() if x.isalnum() else "-" for x in str(member.display_name))[:24].strip("-") or "player"
        try:
            ch=await guild.create_text_channel(f"ticket-{safe}",category=cat,overwrites=ow,reason="RSL orphaned ticket recovery")
        except Exception:
            await self.bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(guild_id),"status":"recovering"},{"$set":{"status":"failed","active":False,"recovery_status":"recovery_channel_creation_failed","updated_at":time.time()}})
            return False
        now=time.time()
        await self.bot.db.rsl_tickets.update_one({"_id":oid,"guild_id":str(guild_id)},{"$set":{"channel_id":str(ch.id),"category_id":str(cat.id) if cat else "","status":"open","active":True,"recovery_status":"recovered","updated_at":now,"last_activity_at":now}})
        row["channel_id"]=str(ch.id)
        await self.reconcile_ticket_permissions(guild,row,closed=False,locked=False)
        await ch.send(content=member.mention,embed=discord.Embed(title=f"🔄 {row.get('type_label','RSL Support')} — Recovered",description="This ticket channel was recreated from its preserved RSL record. Please continue here.",color=discord.Color.blurple()),view=TicketActions(self,ticket_id))
        await log_event(guild_id,ticket_id,"recovered",actor_id,recovery_status="channel_recreated")
        return True
    async def reopen(self,guild_id,ticket_id,actor_id):
        from bson import ObjectId
        oid=ObjectId(ticket_id) if ObjectId.is_valid(ticket_id) else ticket_id
        now=time.time()
        result=await self.bot.db.rsl_tickets.update_one(
            {"_id":oid,"guild_id":str(guild_id),"status":"closed","active":False},
            {"$set":{"status":"open","active":True,"closed_at":None,"locked":False,"updated_at":now,"last_activity_at":now}}
        )
        if not result.modified_count: return False
        row=await self.bot.db.rsl_tickets.find_one({"_id":oid,"guild_id":str(guild_id)})
        if not row: return False
        ch=self.bot.get_channel(int(row.get("channel_id",0)))
        if isinstance(ch,discord.TextChannel):
            try:
                original_id=str(row.get("category_id") or "")
                original=ch.guild.get_channel(int(original_id)) if original_id.isdigit() else None
                if isinstance(original,discord.CategoryChannel): await ch.edit(category=original,reason="RSL ticket reopened")
                await self.reconcile_ticket_permissions(ch.guild,row,closed=False,locked=False)
                await ch.send("🔓 This ticket has been reopened.",view=TicketActions(self,ticket_id))
            except Exception: pass
        await log_event(guild_id,ticket_id,"reopened",actor_id)
        s=await settings_for(guild_id)
        await self.notify_ticket(ticket_id,row,"reopened",message="🔓 Your RSL support ticket has been reopened.",player=s.get("notify_player_dm",True),webhook_payload={"event":"ticket.reopened","guild_id":str(guild_id),"ticket_id":str(ticket_id)})
        return True
    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        row=await self.bot.db.rsl_tickets.find_one({"guild_id":str(message.guild.id),"channel_id":str(message.channel.id),"status":{"$ne":"closed"}})
        if not row:
            return
        now=time.time()
        update={"last_activity_at":now,"updated_at":now,"reminder_sent_at":None}
        if message.attachments:
            evidence=[]
            for attachment in message.attachments[:10]:
                fingerprint=hashlib.sha256(str(attachment.url).encode("utf-8","ignore")).hexdigest()
                evidence.append({"name":str(attachment.filename)[:200],"url":str(attachment.url)[:2000],"size":int(attachment.size or 0),"content_type":str(attachment.content_type or ""), "fingerprint":fingerprint})
            update["$evidence_append"]=evidence
        if str(message.author.id) != str(row.get("user_id")) and not row.get("first_response_at"):
            update["first_response_at"]=now
        evidence=update.pop("$evidence_append",None)
        update_doc={"$set":update}
        if evidence: update_doc["$push"]={"evidence":{"$each":evidence,"$slice":-100}}
        await self.bot.db.rsl_tickets.update_one({"_id":row["_id"],"guild_id":str(message.guild.id)},update_doc)

    async def reconcile_provisioning(self):
        now=time.time()
        cutoff=now-300
        async for row in self.bot.db.rsl_tickets.find({"status":{"$in":["provisioning","recovering"]}}):
            status=str(row.get("status") or "")
            started=float(row.get("updated_at") or row.get("created_at") or now)
            if started > cutoff:
                continue
            if status=="recovering":
                result=await self.bot.db.rsl_tickets.update_one(
                    {"_id":row["_id"],"status":"recovering"},
                    {"$set":{"status":"failed","active":False,"recovery_status":"stale_recovery","updated_at":now}}
                )
                if result.modified_count:
                    await log_event(row["guild_id"],str(row["_id"]),"recovery_stale","system",recovery_status="stale_recovery")
                continue
            if not bool(row.get("active")):
                continue
            result=await self.bot.db.rsl_tickets.update_one(
                {"_id":row["_id"],"status":"provisioning","active":True},
                {"$set":{"status":"failed","active":False,"recovery_status":"stale_provisioning","updated_at":now}}
            )
            if result.modified_count:
                await log_event(row["guild_id"],str(row["_id"]),"provisioning_stale","system",recovery_status="stale_provisioning")

    async def reconcile_missing_channels(self):
        async for row in self.bot.db.rsl_tickets.find({"status":{"$ne":"closed"},"active":True}):
            guild=self.bot.get_guild(int(row.get("guild_id",0)))
            if not guild: continue
            channel_id=int(row.get("channel_id",0))
            channel=guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel=await guild.fetch_channel(channel_id)
                except discord.NotFound:
                    await self.bot.db.rsl_tickets.update_one({"_id":row["_id"],"guild_id":str(row.get("guild_id")),"active":True},{"$set":{"status":"orphaned","active":False,"recovery_status":"channel_missing","updated_at":time.time()}})
                    await log_event(row["guild_id"],str(row["_id"]),"channel_missing","system",recovery_status="channel_missing")
                    continue
                except Exception:
                    continue
            if channel is None: continue
            
    @tasks.loop(minutes=15)
    async def auto_close_loop(self):
        now=time.time()
        await self.reconcile_provisioning()
        await self.reconcile_missing_channels()
        async for row in self.bot.db.rsl_tickets.find({"status":{"$ne":"closed"}}):
            s=await settings_for(str(row.get("guild_id","")))
            inactivity_age=support_elapsed_seconds(float(row.get("last_activity_at") or row.get("updated_at") or now),now,s)
            response_age=support_elapsed_seconds(float(row.get("created_at") or now),now,s)
            if s["reminder_hours"]>0 and inactivity_age>=s["reminder_hours"]*3600 and not row.get("reminder_sent_at"):
                ch=self.bot.get_channel(int(row.get("channel_id",0)))
                if isinstance(ch,discord.TextChannel):
                    await self.notify_ticket(str(row["_id"]),row,"inactivity_reminder",message="⏰ Ticket inactivity reminder: reply if you still need help; staff may close inactive tickets.",staff=True)
                result=await self.bot.db.rsl_tickets.update_one({"_id":row["_id"],"guild_id":str(row.get("guild_id")),"reminder_sent_at":None},{"$set":{"reminder_sent_at":now,"updated_at":now}})
                if result.modified_count:
                    await log_event(row["guild_id"],str(row["_id"]),"inactivity_reminder","system")
            sla=s["sla_minutes"]
            if sla>0 and not row.get("first_response_at") and response_age>=sla*60 and not row.get("sla_alerted_at"):
                ch=self.bot.get_channel(int(row.get("channel_id",0)))
                claimed=str(row.get("claimed_by") or "")
                mentions=f" <@{claimed}>" if claimed.isdigit() else ""
                await self.notify_ticket(str(row["_id"]),row,"sla_escalated",message=f"🚨 Staff alert: this ticket has reached its response SLA without a recorded staff response.{mentions}",staff=True,webhook_payload={"event":"ticket.sla_escalated","guild_id":row["guild_id"],"ticket_id":str(row["_id"]),"claimed_by":claimed or None})
                result=await self.bot.db.rsl_tickets.update_one({"_id":row["_id"],"guild_id":str(row.get("guild_id")),"sla_alerted_at":None},{"$set":{"status":"escalated","sla_alerted_at":now,"updated_at":now}})
                if result.modified_count:
                    await log_event(row["guild_id"],str(row["_id"]),"sla_escalated","system")
            hours=s["auto_close_hours"]
            if hours>0 and inactivity_age>=hours*3600:
                await self._close_ticket(str(row["guild_id"]),str(row["_id"]),"system","inactivity_auto_close")
    @auto_close_loop.before_loop
    async def before_auto_close(self): await self.bot.wait_until_ready()

async def setup(bot_instance): await bot_instance.add_cog(TicketCog(bot_instance))
def support_elapsed_seconds(start_ts,end_ts,settings):
    start=float(start_ts or end_ts); end=float(end_ts or start)
    if end<=start: return 0.0
    if not settings.get("support_hours_enabled"): return end-start
    tz_name=str(settings.get("support_hours_timezone") or "UTC")
    try: tz=ZoneInfo(tz_name)
    except Exception: tz=timezone.utc
    days={int(x) for x in settings.get("support_hours_days",[0,1,2,3,4,5,6]) if str(x).isdigit() and 0<=int(x)<=6}
    try:
        sh,sm=[int(x) for x in str(settings.get("support_hours_start","09:00")).split(":",1)]
        eh,em=[int(x) for x in str(settings.get("support_hours_end","17:00")).split(":",1)]
    except Exception: sh,sm,eh,em=9,0,17,0
    total=0.0
    cursor=datetime.fromtimestamp(start,tz).date()
    last=datetime.fromtimestamp(end,tz).date()
    while cursor<=last:
        if cursor.weekday() in days:
            a=datetime.combine(cursor,dt_time(sh,sm),tzinfo=tz).timestamp()
            b=datetime.combine(cursor,dt_time(eh,em),tzinfo=tz).timestamp()
            if b<a: b += 86400
            total += max(0.0,min(end,b)-max(start,a))
        cursor += timedelta(days=1)
    return total

